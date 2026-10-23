"""Local APEX routes for MingSi 所函用章 applications.

This module deliberately keeps the MingSi session on the server side.  It
resolves labels and workflow people from MingSi at runtime, uploads the exact
short-lived artifact created by the document bundle endpoint, and records a
local idempotency key before making a remote application.
"""
from __future__ import annotations

import datetime as dt
import asyncio
import json
import mimetypes
import sqlite3
from typing import Any, Callable, Dict, Iterable, List

from fastapi import File, Form, HTTPException, UploadFile

from .document_bundle_artifacts import get_document_bundle_artifact, mark_artifact_consumed
from .mingsi_client import MingsiClient, _account_id, _now
from .business_profile import chapter_approver


CHAPTER_FILE_LABEL = "所函"
SEAL_LABEL = "公章"
MAX_COPIES = 100
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
QUICK_MAX_FILES = 10
QUICK_MAX_FILE_BYTES = 200 * 1024 * 1024
QUICK_ALLOWED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".csv", ".ppt", ".pptx", ".wps", ".txt", ".zip", ".rar",
})
# 明思把“文件子类”和“其他需申请文件”分成两套字典。不同机构往往只
# 配置后者的少数通用项，因此未配置同名项时按语义回退到实时返回的编号，
# 绝不把某个机构的 commondataid 写死在本地。
QUICK_FILE_TYPE_ALIASES = {
    "其他合同": ("业务合同",),
    "业务合同（补充或重签）": ("业务合同",),
    "律师函": ("所函",),
    "法律意见书": ("所函",),
    "其他": ("所函",),
}
QUICK_GENERIC_FILE_TYPE_LABELS = ("所函", "业务合同", "介绍信", "出庭函", "授权书")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normal_label(value: Any) -> str:
    return "".join(_text(value).split())


def _walk_dicts(value: Any, ancestors: tuple[dict[str, Any], ...] = ()) -> Iterable[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    if isinstance(value, dict):
        yield value, ancestors
        next_ancestors = ancestors + (value,)
        for child in value.values():
            yield from _walk_dicts(child, next_ancestors)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, ancestors)


def _label(item: dict[str, Any]) -> str:
    for key in (
        "commondataname", "chaptertypename", "casetypename", "sealtypename",
        "name", "label", "text", "title", "typename",
    ):
        if _text(item.get(key)):
            return _text(item[key])
    return ""


def _id(item: dict[str, Any], keys: tuple[str, ...] = ()) -> str:
    candidates = keys or (
        "commondataid", "chaptertypeid", "casetypeid", "sealtypeid",
        "personid", "personId", "caseid", "id", "value",
    )
    for key in candidates:
        value = item.get(key)
        if value is not None and _text(value):
            return _text(value)
    return ""


def _named_nodes(payload: Any, target: str) -> list[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    expected = _normal_label(target)
    return [(item, ancestors) for item, ancestors in _walk_dicts(payload) if _normal_label(_label(item)) == expected]


def _person_id(item: dict[str, Any]) -> str:
    return _id(item, ("personid", "personId", "userid", "userId", "id", "value"))


def _person_name(item: dict[str, Any]) -> str:
    for key in ("personname", "personName", "username", "userName", "name", "label"):
        if _text(item.get(key)):
            return _text(item[key])
    return ""


def _people(payload: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item, _ in _walk_dicts(payload):
        name, person_id = _person_name(item), _person_id(item)
        if not name or not person_id or person_id in seen:
            continue
        seen.add(person_id)
        result.append({"id": person_id, "name": name})
    return result


def _profile_object(profile: Any) -> dict[str, Any]:
    if isinstance(profile, dict) and isinstance(profile.get("person"), dict):
        return profile["person"]
    return profile if isinstance(profile, dict) else {}


def _profile_name(profile: Any) -> str:
    person = _profile_object(profile)
    return _person_name(person)


def _profile_id(profile: Any) -> str:
    return _person_id(_profile_object(profile))


def _department_ids(profile: Any) -> list[str]:
    person = _profile_object(profile)
    values: list[Any] = []
    for key in ("departmentids", "departmentIds", "departmentid", "departmentId", "deptid", "deptId"):
        value = person.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value is not None and _text(value):
            values.append(value)
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def _first_value(payload: Any, keys: tuple[str, ...]) -> Any:
    wanted = set(keys)
    for item, _ in _walk_dicts(payload):
        for key in wanted:
            if key in item and item[key] is not None:
                return item[key]
    return None


def _first_dict(payload: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    wanted = set(keys)
    for item, _ in _walk_dicts(payload):
        for key in wanted:
            value = item.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _chapter_type_candidates(chapter_types: Any, file_types: Any) -> list[dict[str, Any]]:
    file_matches = _named_nodes(file_types, CHAPTER_FILE_LABEL)
    if len(file_matches) != 1:
        raise HTTPException(status_code=502, detail="明思中未能唯一确认文件类型“所函”")
    file_node, _ = file_matches[0]
    file_id = _id(file_node, ("commondataid", "chapterfileid", "id", "value"))
    if not file_id:
        raise HTTPException(status_code=502, detail="明思“所函”配置缺少必要的动态编号")

    candidates: list[dict[str, Any]] = []
    for type_node, ancestors in _named_nodes(chapter_types, CHAPTER_FILE_LABEL):
        small_id = _id(type_node, ("chaptertype", "chapterType", "smallid", "smallId", "casetypeid", "commondataid", "id", "value"))
        big_id = _id(type_node, ("chapterbigtype", "chapterbigtypeid", "bigtype", "bigType", "parentid", "parentId"))
        category_label = ""
        if not big_id:
            for parent in reversed(ancestors):
                big_id = _id(parent, ("chapterbigtype", "chapterbigtypeid", "bigtype", "bigType", "commondataid", "casetypeid", "id", "value"))
                if big_id:
                    break
        for parent in reversed(ancestors):
            category_label = _label(parent)
            if category_label:
                break
        if not small_id or not big_id:
            continue
        candidates.append({
            "big_id": big_id,
            "small_id": small_id,
            "label": CHAPTER_FILE_LABEL,
            "category_label": category_label,
            "file_item": {"commondataid": file_id, "commondataname": CHAPTER_FILE_LABEL},
        })
    return candidates


def _chapter_type_config(chapter_types: Any, file_types: Any) -> dict[str, Any]:
    """Resolve a label when MingSi exposes exactly one matching category.

    The live system currently has two ``所函`` children.  Callers that can
    query category details should use ``_resolve_chapter_type`` so the
    duplicate label can be disambiguated by configuration rather than by an
    internal ID.
    """
    candidates = _chapter_type_candidates(chapter_types, file_types)
    if len(candidates) != 1:
        raise HTTPException(status_code=502, detail="明思中未能唯一确认“所函”的用章分类")
    return candidates[0]


async def _resolve_chapter_type(client: MingsiClient, chapter_types: Any, file_types: Any) -> dict[str, Any]:
    candidates = _chapter_type_candidates(chapter_types, file_types)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise HTTPException(status_code=502, detail="明思中未能唯一确认“所函”的用章分类")

    # ``所函`` is duplicated under business and non-business use章 in the
    # current MingSi configuration.  The requested default is the business
    # category, so prefer its live parent label.  This uses the label returned
    # by MingSi and never embeds an environment-specific category ID.
    business = [
        candidate for candidate in candidates
        if _normal_label(candidate.get("category_label")) == "业务用章"
    ]
    if len(business) == 1:
        return business[0]

    # Keep a semantic fallback for installations that renamed the parent
    # category: this feature always binds the request to a related project,
    # so select the category whose live detail requires a related case.
    case_required: list[dict[str, Any]] = []
    for candidate in candidates:
        detail_response = await client.authenticated(
            "/sys/syscommondataCasetype/getChapterDetailed",
            params={"casetypeid": candidate["small_id"]},
        )
        detail = _first_dict(detail_response, ("chapterDetailed", "chapterdetail", "chapterDetail"))
        if _normal_label(detail.get("isrecase")) == "REQUIRED":
            case_required.append(candidate)
    if len(case_required) == 1:
        return case_required[0]
    raise HTTPException(status_code=502, detail="明思中存在多个“所函”用章分类，无法按案件关联配置唯一确认")


def _seal_config(seals: Any) -> dict[str, str]:
    matches = _named_nodes(seals, SEAL_LABEL)
    if len(matches) != 1:
        raise HTTPException(status_code=502, detail="明思中未能唯一确认印章类型“公章”")
    seal_id = _id(matches[0][0], ("sealtypeid", "sealTypeId", "commondataid", "id", "value"))
    if not seal_id:
        raise HTTPException(status_code=502, detail="明思“公章”配置缺少必要编号")
    return {"id": seal_id, "label": SEAL_LABEL}


def _project_records(payload: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item, _ in _walk_dicts(payload):
        case_id = _id(item, ("caseid", "caseId", "id"))
        name = _text(item.get("casename") or item.get("caseName") or item.get("name"))
        if not case_id or not name or case_id in seen:
            continue
        seen.add(case_id)
        result.append({
            "id": case_id,
            "name": name,
            "casecode": _text(item.get("casecode") or item.get("caseCode") or item.get("case_no")),
            "department_id": _text(item.get("departmentid") or item.get("departmentId") or item.get("deptid")),
            "allcasename": _text(item.get("allcasename") or item.get("allCaseName")),
        })
    return result


def _total(payload: Any, fallback: int) -> int:
    value = _first_value(payload, ("total", "totalCount", "count"))
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _uploaded_files(payload: Any) -> list[dict[str, Any]]:
    for item, _ in _walk_dicts(payload):
        value = item.get("file")
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
        if isinstance(value, dict):
            return [value]
    for item, _ in _walk_dicts(payload):
        for key in ("files", "fileList", "filelist", "epmsAttachfilesEntityList"):
            value = item.get(key)
            if isinstance(value, list) and all(isinstance(entry, dict) for entry in value):
                return value
    return []


def _chapter_id(payload: Any) -> str:
    for item, _ in _walk_dicts(payload):
        for key in ("chapterid", "chapterId", "chapter_id", "chapterID"):
            if key in item and _text(item[key]):
                return _text(item[key])
    if isinstance(payload, dict):
        # saveChapter has returned both ``{data: {chapterid: ...}}`` and a
        # scalar ``{data: 42715}`` in different MingSi deployments.  Accept
        # only the response's known result containers so an unrelated nested
        # ``id`` cannot be mistaken for an application ID.
        for key in ("id", "chapter_id", "chapterID"):
            if _text(payload.get(key)):
                return _text(payload[key])
        for container_key in ("data", "result"):
            value = payload.get(container_key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and _text(value):
                return _text(value)
            if isinstance(value, dict):
                for key in ("id", "chapter_id", "chapterID"):
                    if _text(value.get(key)):
                        return _text(value[key])
    return ""


def _chapter_records(payload: Any) -> list[dict[str, Any]]:
    """Extract chapter rows from MingSi's several pagination shapes.

    The live endpoint currently returns ``list=[records, pager]``.  Some
    deployments wrap that value under ``data`` or use ``records``/``rows``.
    Only dictionaries that carry an application ID are considered rows, so a
    pager dictionary cannot be mistaken for a chapter.
    """
    chapter_id_keys = ("chapterid", "chapterId", "chapter_id", "chapterID", "id")

    def collect(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            rows = [
                item for item in value
                if isinstance(item, dict) and any(_text(item.get(key)) for key in chapter_id_keys)
            ]
            if rows:
                return rows
            for child in value:
                rows = collect(child)
                if rows:
                    return rows
            return []
        if isinstance(value, dict):
            for key in ("records", "rows", "list", "data", "result"):
                if key in value:
                    rows = collect(value[key])
                    if rows:
                        return rows
        return []

    return collect(payload)


def _chapter_record_value(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in record and _text(record[key]):
            return _text(record[key])
    return ""


def _chapter_record_date(record: dict[str, Any]) -> str:
    value = _chapter_record_value(record, (
        "chapterapplydate", "chapterApplyDate", "applydate", "applyDate",
        "createdate", "createDate", "createtime", "createTime", "adddate", "addDate",
    ))
    return value.replace("T", " ").split(" ", 1)[0]


def _chapter_record_matches(
    record: dict[str, Any],
    *,
    project_id: str,
    project_name: str,
    chapter_type_id: str,
    chapter_type_label: str,
    chapter_big_type_id: str,
    copies: int,
    applicant_name: str,
    remark: str,
) -> str:
    chapter_id = _id(record, ("chapterid", "chapterId", "chapter_id", "chapterID", "id"))
    if not chapter_id:
        return ""

    record_project = _chapter_record_value(record, (
        "caseid", "caseId", "caseID", "projectid", "projectId", "projectID",
    ))
    if record_project:
        if _normal_label(record_project) != _normal_label(project_id):
            return ""
    else:
        record_project_name = _chapter_record_value(record, ("casename", "caseName", "projectname", "projectName"))
        record_project_code = _chapter_record_value(record, ("casecode", "caseCode", "case_no"))
        names_match = bool(record_project_name and project_name and (
            _normal_label(record_project_name) == _normal_label(project_name)
            or _normal_label(record_project_name) in _normal_label(project_name)
            or _normal_label(project_name) in _normal_label(record_project_name)
        ))
        codes_match = bool(record_project_code and project_name and _normal_label(record_project_code) in _normal_label(project_name))
        if not (names_match or codes_match):
            return ""

    record_big_type = _chapter_record_value(record, (
        "chapterbigtype", "chapterBigType", "chapterbigtypeid", "chapterBigTypeId",
        "bigtype", "bigType",
    ))
    if chapter_big_type_id and record_big_type and _normal_label(record_big_type) != _normal_label(chapter_big_type_id):
        return ""

    record_type = _chapter_record_value(record, (
        "chaptertype", "chapterType", "chaptertypes", "chapterTypeId", "casetypeid", "caseTypeId",
    ))
    expected_types = {_normal_label(chapter_type_id), _normal_label(chapter_type_label or CHAPTER_FILE_LABEL)}
    if record_type and _normal_label(record_type) not in expected_types:
        return ""

    apply_date = _chapter_record_date(record)
    if apply_date != dt.date.today().isoformat():
        return ""

    record_copies = _chapter_record_value(record, ("chaptercopies", "chapterCopies", "copies", "copyNumber"))
    try:
        if not record_copies or int(record_copies) != copies:
            return ""
    except (TypeError, ValueError):
        return ""

    record_applicant = _chapter_record_value(record, (
        "chapterapplypsnname", "chapterApplyPsnName", "applypsnname", "applyPsnName", "personname", "personName",
    ))
    if applicant_name and record_applicant and _normal_label(record_applicant) != _normal_label(applicant_name):
        return ""

    if remark:
        record_remark = _chapter_record_value(record, ("chapterremark", "chapterRemark", "remark"))
        if record_remark and _normal_label(record_remark) != _normal_label(remark):
            return ""

    return chapter_id


async def _find_recent_chapter_id(
    client: MingsiClient,
    *,
    project_id: str,
    project_name: str = "",
    chapter_type_id: str,
    copies: int,
    applicant_name: str,
    chapter_type_label: str = "",
    chapter_big_type_id: str = "",
    remark: str = "",
) -> str:
    """Recover an ID when saveChapter acknowledges without returning one.

    MingSi's save endpoint can return only ``code/msg``.  The list endpoint
    is used strictly as a read-only reconciliation step.  MingSi's
    ``chaptertypes`` filter is not consistent across deployments, so an empty
    filtered result is followed by a project-wide read.  Rows are matched by
    project, live type/category, date, copies and applicant, and the newest
    matching row wins by preserving MingSi's response order.
    """
    filtered_query = {
        "page": 1,
        "limit": 20,
        "mychapter": 1,
        "caseid": project_id,
        "chaptertypes": chapter_type_id,
    }
    broad_query = {key: value for key, value in filtered_query.items() if key != "chaptertypes"}
    queries = [filtered_query, broad_query] if chapter_type_id else [broad_query]

    for attempt, delay in enumerate((0, 0.35, 0.9)):
        if delay:
            await asyncio.sleep(delay)
        for query_index, query in enumerate(queries):
            try:
                response = await client.authenticated("/case/chapter/getChapterListPage", data=query)
            except HTTPException:
                # An installation may reject the optional type filter.  The
                # project-wide query is still a safe read-only fallback.
                if query_index < len(queries) - 1:
                    continue
                raise
            for record in _chapter_records(response):
                chapter_id = _chapter_record_matches(
                    record,
                    project_id=project_id,
                    project_name=project_name,
                    chapter_type_id=chapter_type_id,
                    chapter_type_label=chapter_type_label,
                    chapter_big_type_id=chapter_big_type_id,
                    copies=copies,
                    applicant_name=applicant_name,
                    remark=remark,
                )
                if chapter_id:
                    return chapter_id
        if attempt == 2:
            break
    return ""


def _audit_form(payload: Any) -> dict[str, Any]:
    form = _first_dict(payload, ("chapterForm", "chapterform"))
    if form:
        return form
    entity = _first_dict(payload, ("epmsChapterEntity",))
    return {"epmsChapterEntity": entity} if entity else {}


def _audit_entity(form: dict[str, Any]) -> dict[str, Any]:
    value = form.get("epmsChapterEntity")
    return value if isinstance(value, dict) else form


def _form_or_payload_value(form: dict[str, Any], payload: Any, key: str, default: Any = None) -> Any:
    value = form.get(key)
    return value if value is not None else (_first_value(payload, (key,)) if payload is not None else default)


def _task_step(payload: Any) -> Any:
    progress = _first_value(payload, ("processProgressFormList",))
    if isinstance(progress, list):
        for item in progress:
            if isinstance(item, dict) and str(item.get("state")) == "0":
                return item.get("taskstepnum")
    return _first_value(payload, ("taskstepnum",))


def _file_list(value: Any, fallback: dict[str, Any] | None) -> list[dict[str, str]]:
    entries = value if isinstance(value, list) else []
    result: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = _id(entry, ("commondataid", "value", "id"))
        label = _text(entry.get("commondataname") or entry.get("label") or entry.get("name"))
        if item_id and label:
            result.append({"commondataid": item_id, "commondataname": label})
    return result or ([fallback] if fallback else [])


def _candidate_permission(profile: Any) -> bool:
    person = _profile_object(profile)
    for key in ("canApprove", "canApproval", "isApprover", "isAuditor", "approvalPermission", "approvalpermission"):
        if key in person and person[key] in (False, 0, "0", "false", "False"):
            return False
    return True


def _quick_type_options(chapter_types: Any, file_types: Any) -> list[dict[str, Any]]:
    """将明思章类型树转换为截图所示的大类/子类选择结构。"""
    file_items: dict[str, dict[str, str]] = {}
    for item, _ in _walk_dicts(file_types):
        label = _label(item)
        item_id = _id(item, ("commondataid", "chapterfileid", "id", "value"))
        if label and item_id and _normal_label(label) not in file_items:
            file_items[_normal_label(label)] = {"commondataid": item_id, "commondataname": label}

    categories: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    for item, _ in _walk_dicts(chapter_types):
        category_label = _label(item)
        category_id = _id(item, ("commondataid", "chapterbigtype", "chapterbigtypeid", "casetypeid", "id", "value"))
        children = item.get("children") or item.get("child") or item.get("items") or item.get("list")
        if not category_label or not category_id or not isinstance(children, list):
            continue
        subtypes: list[dict[str, Any]] = []
        seen_subtypes: set[str] = set()
        for child in children:
            if not isinstance(child, dict):
                continue
            subtype_label = _label(child)
            subtype_id = _id(child, ("commondataid", "chaptertype", "chaptertypeid", "casetypeid", "id", "value"))
            if not subtype_label or not subtype_id or subtype_id in seen_subtypes:
                continue
            seen_subtypes.add(subtype_id)
            normalized_subtype = _normal_label(subtype_label)
            # “其他” is the primary chapter subtype itself.  MingSi's
            # standard form treats “其他需申请文件” as an optional checkbox;
            # do not silently add a generic “所函” item for this subtype.
            file_item = None if normalized_subtype == "其他" else file_items.get(normalized_subtype)
            if file_item is None and normalized_subtype != "其他":
                for alias in QUICK_FILE_TYPE_ALIASES.get(normalized_subtype, ()):
                    file_item = file_items.get(_normal_label(alias))
                    if file_item is not None:
                        break
            if file_item is None and normalized_subtype != "其他":
                for generic_label in QUICK_GENERIC_FILE_TYPE_LABELS:
                    file_item = file_items.get(_normal_label(generic_label))
                    if file_item is not None:
                        break
            subtypes.append({
                "id": subtype_id,
                "name": subtype_label,
                "file_item": file_item,
                "file_item_fallback": normalized_subtype not in file_items and file_item is not None,
            })
        if category_id in seen_categories:
            continue
        seen_categories.add(category_id)
        categories.append({"id": category_id, "name": category_label, "subtypes": subtypes})
    return categories


async def _quick_metadata(client: MingsiClient) -> dict[str, Any]:
    profile = _profile_object(await client.profile())
    person_id = _profile_id(profile)
    if not person_id:
        raise HTTPException(status_code=502, detail="明思未返回当前登录用户")
    chapter_types = await client.authenticated("/sys/syscommondataCasetype/chapterTypeList")
    file_types = await client.authenticated(
        "/sys/syscommondata/paymentList",
        data={"page": 1, "limit": -1, "commondatatype": "CHAPTERFILELIST"},
    )
    seals = await client.authenticated("/sys/syscommondata/getSealTypeList")
    categories = _quick_type_options(chapter_types, file_types)
    if not categories:
        raise HTTPException(status_code=502, detail="明思未返回可用的文件类型")
    return {"profile": profile, "categories": categories, "seal_type": _seal_config(seals)}


def _quick_selected_type(metadata: dict[str, Any], category_id: str, subtype_id: str) -> dict[str, Any]:
    for category in metadata["categories"]:
        if category["id"] != category_id:
            continue
        for subtype in category["subtypes"]:
            if subtype["id"] == subtype_id:
                if not subtype.get("file_item") and _normal_label(subtype.get("name")) != "其他":
                    raise HTTPException(status_code=502, detail=f"明思未返回可用的通用上传编号，无法提交文件子类“{subtype['name']}”")
                return {
                    "big_id": category["id"], "small_id": subtype["id"],
                    "label": subtype["name"], "category_label": category["name"],
                    "file_item": subtype["file_item"],
                    "file_item_fallback": bool(subtype.get("file_item_fallback")),
                }
    raise HTTPException(status_code=422, detail="所选文件类型不是明思当前可用的类型")


async def _load_metadata(client: MingsiClient, approver_name: str) -> dict[str, Any]:
    if not _normal_label(approver_name):
        raise HTTPException(status_code=422, detail="请先在本地数据库配置用章审批人")
    profile = _profile_object(await client.profile())
    person_id = _profile_id(profile)
    if not person_id:
        raise HTTPException(status_code=502, detail="明思未返回当前登录用户")
    chapter_types = await client.authenticated("/sys/syscommondataCasetype/chapterTypeList")
    file_types = await client.authenticated(
        "/sys/syscommondata/paymentList",
        data={"page": 1, "limit": -1, "commondatatype": "CHAPTERFILELIST"},
    )
    seals = await client.authenticated("/sys/syscommondata/getSealTypeList")
    file_type = await _resolve_chapter_type(client, chapter_types, file_types)
    seal_type = _seal_config(seals)
    auditor_result = await client.authenticated(
        "/case/chapter/getAuditor",
        data={
            "casetypeid": file_type["small_id"],
            "personid": person_id,
            "departmentids": _department_ids(profile),
        },
    )
    approvers = _people(auditor_result)
    huang = [item for item in approvers if _normal_label(item["name"]) == _normal_label(approver_name)]
    if len(huang) != 1:
        raise HTTPException(status_code=502, detail="请在本地数据库配置可唯一确认的用章审批人")
    current_is_huang = _normal_label(_profile_name(profile)) == _normal_label(approver_name)
    return {
        "profile": profile,
        "file_type": file_type,
        "seal_type": seal_type,
        "approvers": approvers,
        "huang": huang[0],
        "approval_available": current_is_huang and _candidate_permission(profile),
    }


def _submission_result(row: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, str]] = []
    try:
        raw = json.loads(row.get("next_approver_candidates_json") or "[]")
        if isinstance(raw, list):
            candidates = [item for item in raw if isinstance(item, dict)]
    except (TypeError, ValueError):
        candidates = []
    return {
        "ok": row.get("status") in {"approved", "pending"},
        "status": row.get("status", "unknown"),
        "message": row.get("message", ""),
        "artifact_id": row.get("artifact_id", ""),
        "chapter_id": row.get("chapter_id", ""),
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "copies": int(row.get("copies") or 1),
        "next_approvers": candidates,
        "next_approver": {
            "id": row.get("next_approver_id", ""),
            "name": row.get("next_approver_name", ""),
        } if row.get("next_approver_id") else None,
    }


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row) if hasattr(row, "keys") else dict(row)


def _get_submission(get_db: Callable[[], Any], artifact_id: str, project_id: str, copies: int) -> dict[str, Any] | None:
    with get_db() as conn:
        return _row_dict(conn.execute(
            "SELECT * FROM mingsi_chapter_submissions WHERE artifact_id=? AND project_id=? AND copies=?",
            (artifact_id, project_id, copies),
        ).fetchone())


def _insert_submission(get_db: Callable[[], Any], *, artifact: dict[str, Any], account_id: str, project_id: str, project_name: str, copies: int) -> dict[str, Any]:
    stamp = _now()
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO mingsi_chapter_submissions
                   (artifact_id, request_hash, account_id, project_id, project_name, copies, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'submitting', ?, ?)""",
                (artifact["artifact_id"], artifact["request_hash"], account_id, project_id, project_name, copies, stamp, stamp),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        existing = _get_submission(get_db, artifact["artifact_id"], project_id, copies)
        if existing:
            return existing
        raise
    return _get_submission(get_db, artifact["artifact_id"], project_id, copies) or {}


def _update_submission(get_db: Callable[[], Any], artifact_id: str, project_id: str, copies: int, *, status: str, message: str = "", chapter_id: str = "", next_approver_id: str = "", next_approver_name: str = "", candidates: list[dict[str, str]] | None = None) -> dict[str, Any]:
    stamp = _now()
    with get_db() as conn:
        conn.execute(
            """UPDATE mingsi_chapter_submissions
               SET status=?, message=?, chapter_id=CASE WHEN ? <> '' THEN ? ELSE chapter_id END,
                   next_approver_id=?, next_approver_name=?, next_approver_candidates_json=?, updated_at=?
               WHERE artifact_id=? AND project_id=? AND copies=?""",
            (status, message[:1000], chapter_id, chapter_id, next_approver_id, next_approver_name, json.dumps(candidates or [], ensure_ascii=False), stamp, artifact_id, project_id, copies),
        )
        conn.commit()
    return _get_submission(get_db, artifact_id, project_id, copies) or {
        "artifact_id": artifact_id, "project_id": project_id, "copies": copies, "status": status, "message": message,
    }


def _remote_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        if isinstance(exc.detail, dict):
            return _text(exc.detail.get("message") or exc.detail.get("detail")) or "明思操作失败"
        return _text(exc.detail) or "明思操作失败"
    return _text(exc) or "明思操作失败"


def register_mingsi_chapter_routes(app: Any, get_db: Callable[[], Any], client_factory: Callable[[], MingsiClient] = MingsiClient) -> None:
    client = client_factory()

    @app.get("/api/mingsi-chapters/bootstrap")
    async def bootstrap():
        metadata = await _load_metadata(client, chapter_approver(get_db))
        return {
            "status": client.status(),
            "person": metadata["profile"],
            "file_type": {key: metadata["file_type"][key] for key in ("big_id", "small_id", "label")},
            "seal_type": metadata["seal_type"],
            "first_approver": metadata["huang"],
            "approval_available": metadata["approval_available"],
            "approvers": metadata["approvers"],
        }

    @app.get("/api/mingsi-chapters/projects")
    async def projects(keyword: str = "", page: int = 1, limit: int = 20):
        current_page, page_size = max(1, int(page)), min(max(1, int(limit)), 100)
        result = await client.authenticated(
            "/case/filing/getRelatedProjectListPage",
            data={"limit": page_size, "page": current_page, "casename": _text(keyword), "casemark": "CHAPTER"},
        )
        items = _project_records(result)
        return {"items": items, "total": _total(result, len(items)), "page": current_page, "limit": page_size}

    @app.get("/api/mingsi-chapters/quick-bootstrap")
    async def quick_bootstrap():
        metadata = await _quick_metadata(client)
        return {
            "status": client.status(),
            "person": metadata["profile"],
            "categories": [
                {
                    "id": category["id"],
                    "name": category["name"],
                    "subtypes": [
                        {"id": subtype["id"], "name": subtype["name"]}
                        for subtype in category["subtypes"]
                    ],
                }
                for category in metadata["categories"]
            ],
            "seal_type": metadata["seal_type"],
        }

    @app.post("/api/mingsi-chapters/quick-submit")
    async def quick_submit(
        category_id: str = Form(...),
        subtype_id: str = Form(...),
        project_id: str = Form(...),
        project_name: str = Form(""),
        department_id: str = Form(""),
        copies: int = Form(1),
        remark: str = Form(""),
        files: List[UploadFile] = File(...),
    ):
        category_id, subtype_id, project_id = _text(category_id), _text(subtype_id), _text(project_id)
        if not category_id or not subtype_id:
            raise HTTPException(status_code=422, detail="请选择完整的文件类型")
        if not project_id:
            raise HTTPException(status_code=422, detail="请选择相关项目")
        if not files or len(files) > QUICK_MAX_FILES:
            raise HTTPException(status_code=422, detail=f"请上传 1-{QUICK_MAX_FILES} 个文件")
        try:
            copies = int(copies)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="份数必须是正整数") from exc
        if copies < 1 or copies > MAX_COPIES:
            raise HTTPException(status_code=422, detail=f"份数应为 1-{MAX_COPIES}")

        metadata = await _quick_metadata(client)
        file_type = _quick_selected_type(metadata, category_id, subtype_id)
        profile = metadata["profile"]
        auditor_result = await client.authenticated(
            "/case/chapter/getAuditor",
            data={
                "casetypeid": subtype_id,
                "personid": _profile_id(profile),
                "departmentids": _department_ids(profile),
            },
        )
        approvers = _people(auditor_result)
        approver_name = chapter_approver(get_db)
        first_approver = next(
            (item for item in approvers if _normal_label(item["name"]) == _normal_label(approver_name)),
            approvers[0] if approvers else None,
        )

        upload_parts: list[tuple[str, tuple[str, bytes, str]]] = []
        for upload in files:
            filename = _text(upload.filename)
            extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if not filename or extension not in QUICK_ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=422, detail=f"不支持上传文件类型：{filename or '未命名文件'}")
            content = await upload.read()
            if not content:
                raise HTTPException(status_code=422, detail=f"文件“{filename}”为空")
            if len(content) > QUICK_MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail=f"文件“{filename}”超过 200 MB")
            mime_type = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            upload_parts.append(("files", (filename, content, mime_type)))

        selected_department_id = _text(department_id)
        if not selected_department_id:
            departments = _department_ids(profile)
            selected_department_id = departments[0] if departments else ""
        if not selected_department_id:
            raise HTTPException(status_code=502, detail="明思未返回当前申请部门")

        # A previous request may have been accepted by MingSi even though its
        # save response omitted the ID.  Reconcile before uploading/saving so
        # a retry can continue that application instead of creating a second
        # one.  This is deliberately best-effort: a new request can still be
        # submitted if the read-only reconciliation endpoint is unavailable.
        chapter_id = ""
        try:
            chapter_id = await _find_recent_chapter_id(
                client,
                project_id=project_id,
                project_name=_text(project_name),
                chapter_type_id=file_type["small_id"],
                chapter_type_label=file_type["label"],
                chapter_big_type_id=file_type["big_id"],
                copies=copies,
                applicant_name=_profile_name(profile),
                remark=_text(remark),
            )
        except Exception:
            chapter_id = ""

        chapter_entity = {
            "chapterbigtype": file_type["big_id"],
            "chaptertype": file_type["small_id"],
            "departmentid": selected_department_id,
            "chaptercode": "",
            "caseid": project_id,
            "chapterapplypsnid": _profile_id(profile),
            "chapterapplypsnname": _profile_name(profile),
            "chapterapplydate": dt.date.today().isoformat(),
            "chaptercopies": copies,
            "chaptertendering": "",
            "receiving": "",
            "chapterremark": _text(remark),
            "conflictresult": "",
            "providerid": "",
            "contractamount": 0,
            "contractpayinfo": "",
            "chapterway": "",
            "issendsmg": "",
        }
        uploaded: list[dict[str, Any]] = []
        save_body = {
            "chapterfilelist": [file_type["file_item"]] if file_type.get("file_item") else [],
            "epmsChapterEntity": chapter_entity,
            "epmsChapterInvolveEntityList": [],
            "epmsAttachfilesEntityList": uploaded,
            "epmsSubsidiaryAttachfilesEntityList": [],
            "sealids": [metadata["seal_type"]["id"]],
            "auditorlist": [first_approver["id"]] if first_approver else [],
            "crossbranchDeptmentList": [],
            "subjectnameList": [],
            "useChapterTypeList": [],
            "epmsShimoViewEntityList": [],
            "epmsFxqIndividualAccountEntityList": [],
        }
        try:
            if not chapter_id:
                uploaded = _uploaded_files(await client.authenticated("/sys/oss/upload", files=upload_parts))
                if len(uploaded) != len(files):
                    raise HTTPException(status_code=502, detail="明思文件上传返回数量与本地文件不一致")
                save_body["epmsAttachfilesEntityList"] = uploaded
                save_response = await client.authenticated("/case/chapter/saveChapter", data=save_body)
                chapter_id = _chapter_id(save_response)
                if not chapter_id:
                    chapter_id = await _find_recent_chapter_id(
                        client,
                        project_id=project_id,
                        project_name=_text(project_name),
                        chapter_type_id=file_type["small_id"],
                        chapter_type_label=file_type["label"],
                        chapter_big_type_id=file_type["big_id"],
                        copies=copies,
                        applicant_name=_profile_name(profile),
                        remark=_text(remark),
                    )
            if not chapter_id:
                raise HTTPException(status_code=502, detail="明思已接收申请，但未能确认申请编号，请在明思中核对")

            first_is_current = bool(first_approver) and (
                _profile_id(profile) == first_approver["id"]
                or _normal_label(_profile_name(profile)) == _normal_label(first_approver["name"])
            )
            if not first_is_current:
                next_response = await client.authenticated("/case/chapter/getNextAuditor", params={"chapterid": chapter_id})
                next_approvers = _people(next_response)
                return {
                    "ok": True,
                    "status": "pending",
                    "approved": False,
                    "message": f"已提交，等待{first_approver['name'] if first_approver else '下一位审批人'}审批",
                    "chapter_id": chapter_id,
                    "next_approvers": next_approvers,
                }

            audit_response = await client.authenticated("/case/chapter/getChapterAudit", params={"chapterid": chapter_id})
            next_response = await client.authenticated("/case/chapter/getNextAuditor", params={"chapterid": chapter_id})
            next_approvers = _people(next_response)
            if not next_approvers:
                return {
                    "ok": True,
                    "status": "pending",
                    "approved": False,
                    "message": "已提交，明思暂未返回下一级审批人",
                    "chapter_id": chapter_id,
                    "next_approvers": [],
                }
            form = _audit_form(audit_response)
            audit_entity = _audit_entity(form)
            if not audit_entity.get("chapterid"):
                audit_entity = {**_first_dict(audit_response, ("epmsChapterEntity",)), **audit_entity}
            taskstepnum = _task_step(audit_response)
            if taskstepnum is None:
                raise HTTPException(status_code=502, detail="明思未返回当前审批步骤")
            approval_entity = {
                key: audit_entity.get(key, chapter_entity.get(key))
                for key in (
                    "chapterid", "chapterbigtype", "chaptertype", "departmentid", "caseid",
                    "chapterapplypsnid", "chapterapplypsnname", "chapterapplydate", "chaptercopies",
                    "chaptertendering", "receiving", "chapterremark", "providerid", "contractamount",
                    "contractpayinfo", "conflictresult", "approvalstatus", "chapterway", "issendsmg",
                )
            }
            approval_entity["chapterid"] = chapter_id
            approval_entity["chaptercopies"] = int(approval_entity.get("chaptercopies") or copies)
            approval_entity["contractamount"] = float(approval_entity.get("contractamount") or 0)
            approval_body = {
                "chapterfilelist": _file_list(_form_or_payload_value(form, audit_response, "chapterfilelist"), file_type.get("file_item")),
                "epmsChapterEntity": approval_entity,
                "epmsChapterInvolveEntityList": _form_or_payload_value(form, audit_response, "epmsChapterInvolveEntityList") or [],
                "epmsAttachfilesEntityList": _form_or_payload_value(form, audit_response, "epmsAttachfilesEntityList") or uploaded,
                "sealids": _form_or_payload_value(form, audit_response, "sealids") or [metadata["seal_type"]["id"]],
                "auditorlist": [next_approvers[0]["id"]],
                "comments": "",
                "taskstepnum": taskstepnum,
                "crossbranchDeptmentList": _form_or_payload_value(form, audit_response, "crossbranchDeptmentList") or [],
                "subjectnameList": _form_or_payload_value(form, audit_response, "subjectnameList") or [],
                "useChapterTypeList": _form_or_payload_value(form, audit_response, "useChapterTypeList") or [],
                "epmsShimoViewEntityList": _form_or_payload_value(form, audit_response, "epmsShimoViewEntityList") or [],
                "epmsSubsidiaryAttachfilesEntityList": _form_or_payload_value(form, audit_response, "epmsSubsidiaryAttachfilesEntityList") or [],
                "epmsFxqIndividualAccountEntityList": _form_or_payload_value(form, audit_response, "epmsFxqIndividualAccountEntityList") or [],
                "tasktype": "用章流程",
            }
            await client.authenticated("/case/chapter/chapterApproved", data=approval_body)
            return {
                "ok": True,
                "status": "approved",
                "approved": True,
                "message": f"{file_type['label']}已提交并完成审批",
                "chapter_id": chapter_id,
                "next_approvers": next_approvers,
                "next_approver": next_approvers[0],
            }
        except HTTPException:
            raise
        except Exception as exc:
            message = _remote_error(exc)
            if chapter_id:
                message = f"{message}（申请编号：{chapter_id}，请在明思中核对）"
            raise HTTPException(status_code=502, detail=message) from exc

    @app.post("/api/mingsi-chapters/submit-and-approve")
    async def submit_and_approve(body: Dict[str, Any]):
        artifact_id = _text(body.get("artifact_id"))
        project_id = _text(body.get("project_id"))
        if not artifact_id:
            raise HTTPException(status_code=422, detail="请先生成文书合集")
        if not project_id:
            raise HTTPException(status_code=422, detail="请选择相关项目")
        try:
            copies = int(body.get("copies", 1))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="份数必须是正整数") from exc
        if copies < 1 or copies > MAX_COPIES:
            raise HTTPException(status_code=422, detail=f"份数应为 1-{MAX_COPIES}")

        artifact = get_document_bundle_artifact(get_db, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=410, detail="文书成品已过期，请重新生成文书合集")
        project_name = _text(body.get("project_name"))
        existing = _get_submission(get_db, artifact_id, project_id, copies)
        if existing:
            return _submission_result(existing)
        if artifact.get("consumed_at"):
            raise HTTPException(status_code=409, detail="该所函成品已提交过用章申请，请重新生成后再提交")
        # Resolve all dynamic labels, the applicant and Huang Hao before
        # creating the idempotency row.  A missing/expired login must not leave
        # a permanently "submitting" record that blocks a later retry.
        metadata = await _load_metadata(client, chapter_approver(get_db))
        project_name = project_name or project_id
        account_status = client.status()
        account_id = _text(account_status.get("account_id"))
        if not account_id:
            # This is a deterministic, non-sensitive fallback for injected
            # test clients; the production client always returns account_id.
            account_id = _account_id(_text(account_status.get("account")))
        submission = _insert_submission(
            get_db,
            artifact=artifact,
            account_id=account_id,
            project_id=project_id,
            project_name=project_name,
            copies=copies,
        )
        if submission.get("status") != "submitting":
            return _submission_result(submission)

        chapter_id = ""
        candidates: list[dict[str, str]] = []
        remote_save_attempted = False
        try:
            profile = metadata["profile"]
            project_name = project_name or _text(body.get("project_name")) or project_id
            department_id = _text(body.get("department_id"))
            if not department_id:
                departments = _department_ids(profile)
                department_id = departments[0] if departments else ""
            if not department_id:
                raise HTTPException(status_code=502, detail="明思未返回相关项目或当前申请部门")
            upload_response = await client.authenticated(
                "/sys/oss/upload",
                files=[("files", (artifact["suohan_filename"], artifact["suohan_content"], DOCX_MIME))],
            )
            uploaded = _uploaded_files(upload_response)
            if not uploaded:
                raise HTTPException(status_code=502, detail="明思未返回所函附件实体")

            applicant_id = _profile_id(profile)
            chapter_entity = {
                "chapterbigtype": metadata["file_type"]["big_id"],
                "chaptertype": metadata["file_type"]["small_id"],
                "departmentid": department_id,
                # The MingSi form sends an empty value while the UI displays
                # its auto-generated-code placeholder; do not send that
                # placeholder text as business data.
                "chaptercode": "",
                "caseid": project_id,
                "chapterapplypsnid": applicant_id,
                "chapterapplypsnname": _profile_name(profile),
                "chapterapplydate": dt.date.today().isoformat(),
                "chaptercopies": copies,
                "chaptertendering": "",
                "receiving": "",
                "chapterremark": "",
                "conflictresult": "",
                "providerid": "",
                "contractamount": 0,
                "contractpayinfo": "",
                "chapterway": "",
                "issendsmg": "",
            }
            save_body = {
                "chapterfilelist": [metadata["file_type"]["file_item"]],
                "epmsChapterEntity": chapter_entity,
                "epmsChapterInvolveEntityList": [],
                "epmsAttachfilesEntityList": uploaded,
                "epmsSubsidiaryAttachfilesEntityList": [],
                "sealids": [metadata["seal_type"]["id"]],
                "auditorlist": [metadata["huang"]["id"]],
                "crossbranchDeptmentList": [],
                "subjectnameList": [],
                "useChapterTypeList": [],
                "epmsShimoViewEntityList": [],
                "epmsFxqIndividualAccountEntityList": [],
            }
            remote_save_attempted = True
            save_response = await client.authenticated("/case/chapter/saveChapter", data=save_body)
            chapter_id = _chapter_id(save_response)
            if not chapter_id:
                try:
                    chapter_id = await _find_recent_chapter_id(
                        client,
                        project_id=project_id,
                        project_name=_text(project_name),
                        chapter_type_id=metadata["file_type"]["small_id"],
                        chapter_type_label=metadata["file_type"]["label"],
                        chapter_big_type_id=metadata["file_type"]["big_id"],
                        copies=copies,
                        applicant_name=_profile_name(profile),
                    )
                except Exception as exc:
                    raise HTTPException(status_code=502, detail="明思已接收用章申请，但查询申请编号失败，请在明思中核对") from exc
            if not chapter_id:
                raise HTTPException(status_code=502, detail="明思已接收用章申请，但未能唯一确认申请编号，请在明思中核对")
            mark_artifact_consumed(get_db, artifact_id)

            if not metadata["approval_available"]:
                # The applicant is not allowed to impersonate Huang Hao, but
                # the next-step candidates are still useful to the user and
                # are returned for transparency.
                next_response = await client.authenticated("/case/chapter/getNextAuditor", params={"chapterid": chapter_id})
                candidates = _people(next_response)
                selected = candidates[0] if candidates else None
                row = _update_submission(
                    get_db, artifact_id, project_id, copies, status="pending", chapter_id=chapter_id,
                    next_approver_id=selected["id"] if selected else "",
                    next_approver_name=selected["name"] if selected else "",
                    message=f"已提交，等待{metadata['huang']['name']}审批",
                    candidates=candidates,
                )
                return _submission_result(row)

            audit_response = await client.authenticated("/case/chapter/getChapterAudit", params={"chapterid": chapter_id})
            next_response = await client.authenticated("/case/chapter/getNextAuditor", params={"chapterid": chapter_id})
            candidates = _people(next_response)
            if not candidates:
                row = _update_submission(
                    get_db, artifact_id, project_id, copies, status="pending", chapter_id=chapter_id,
                    message="已提交，明思暂未返回下一级审批人", candidates=candidates,
                )
                return _submission_result(row)
            requested_next = _text(body.get("next_approver_id"))
            selected = next((item for item in candidates if item["id"] == requested_next), None) if requested_next else candidates[0]
            if requested_next and selected is None:
                raise HTTPException(status_code=422, detail="下一级审批人不在明思返回的候选范围内")

            form = _audit_form(audit_response)
            audit_entity = _audit_entity(form)
            if not audit_entity.get("chapterid"):
                audit_entity = {**_first_dict(audit_response, ("epmsChapterEntity",)), **audit_entity}
            taskstepnum = _task_step(audit_response)
            if taskstepnum is None:
                raise HTTPException(status_code=502, detail="明思未返回当前审批步骤")
            approval_entity = {
                key: audit_entity.get(key, chapter_entity.get(key))
                for key in (
                    "chapterid", "chapterbigtype", "chaptertype", "departmentid", "caseid",
                    "chapterapplypsnid", "chapterapplypsnname", "chapterapplydate", "chaptercopies",
                    "chaptertendering", "receiving", "chapterremark", "providerid", "contractamount",
                    "contractpayinfo", "conflictresult", "approvalstatus", "chapterway", "issendsmg",
                )
            }
            approval_entity["chapterid"] = chapter_id
            approval_entity["chaptercopies"] = int(approval_entity.get("chaptercopies") or copies)
            approval_entity["contractamount"] = float(approval_entity.get("contractamount") or 0)
            approval_body = {
                "chapterfilelist": _file_list(_form_or_payload_value(form, audit_response, "chapterfilelist"), metadata["file_type"]["file_item"]),
                "epmsChapterEntity": approval_entity,
                "epmsChapterInvolveEntityList": _form_or_payload_value(form, audit_response, "epmsChapterInvolveEntityList") or [],
                "epmsAttachfilesEntityList": _form_or_payload_value(form, audit_response, "epmsAttachfilesEntityList") or uploaded,
                "sealids": _form_or_payload_value(form, audit_response, "sealids") or [metadata["seal_type"]["id"]],
                "auditorlist": [selected["id"]],
                "comments": _text(body.get("comments")),
                "taskstepnum": taskstepnum,
                "crossbranchDeptmentList": _form_or_payload_value(form, audit_response, "crossbranchDeptmentList") or [],
                "subjectnameList": _form_or_payload_value(form, audit_response, "subjectnameList") or [],
                "useChapterTypeList": _form_or_payload_value(form, audit_response, "useChapterTypeList") or [],
                "epmsShimoViewEntityList": _form_or_payload_value(form, audit_response, "epmsShimoViewEntityList") or [],
                "epmsSubsidiaryAttachfilesEntityList": _form_or_payload_value(form, audit_response, "epmsSubsidiaryAttachfilesEntityList") or [],
                "epmsFxqIndividualAccountEntityList": _form_or_payload_value(form, audit_response, "epmsFxqIndividualAccountEntityList") or [],
                "tasktype": "用章流程",
            }
            await client.authenticated("/case/chapter/chapterApproved", data=approval_body)
            # One bounded read confirms that the approval endpoint itself was
            # accepted without polling or creating another application.
            await client.authenticated("/case/chapter/getChapterAudit", params={"chapterid": chapter_id})
            row = _update_submission(
                get_db, artifact_id, project_id, copies, status="approved", chapter_id=chapter_id,
                next_approver_id=selected["id"], next_approver_name=selected["name"],
                message=f"所函已提交并完成{metadata['huang']['name']}审批", candidates=candidates,
            )
            return _submission_result(row)
        except Exception as exc:
            status = "unknown" if chapter_id or remote_save_attempted else "failed"
            row = _update_submission(
                get_db, artifact_id, project_id, copies, status=status, chapter_id=chapter_id,
                message=_remote_error(exc), candidates=candidates,
            )
            if isinstance(exc, HTTPException) and exc.status_code == 422:
                raise
            raise HTTPException(status_code=502, detail=_remote_error(exc)) from exc
