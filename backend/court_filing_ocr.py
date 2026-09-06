"""Protect the material -> parties transition in the APEX court browser.

The official file-upload component calls GET /layy/ocr on *every* Next click,
then reads layyxq. GET is a write here. A check in APEX before that click cannot
prevent the later duplicate. Hold the OCR response until reconciliation and
read-back finish, including popups/new tabs in the same browser context.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

OCR_PATH = "/yzw/yzw-zxfw-lafw/api/v3/layy/ocr"
OCR_ROUTE = re.compile(r"^https://zxfw\.court\.gov\.cn" + OCR_PATH + r"(?:\?.*)?$")
DETAIL_PATH = re.compile(r"^/yzw/yzw-zxfw-lafw/api/v3/layy/layyxq/([^/]+)/0$")
FILING_ROUTE = re.compile(r"^https://zxfw\.court\.gov\.cn/yzw/yzw-zxfw-lafw/api/v3/layy/(?:ocr|layyxq/[^/]+/0)(?:\?.*)?$")


def _clean(value):
    return re.sub(r"\s+", "", str(value or "")).upper()


def _single_character_change(a, b):
    if len(a) == len(b):
        changes = [(x, y) for x, y in zip(a, b) if x != y]
        return changes[0] if len(changes) == 1 else None
    if len(a) == len(b) + 1:
        return next(((a[i], "") for i in range(len(a)) if a[:i] + a[i + 1:] == b), None)
    if len(b) == len(a) + 1:
        return next((("", b[i]) for i in range(len(b)) if b[:i] + b[i + 1:] == a), None)
    return None


def _proven_organisation_ocr_variant(old, row):
    # OCR may omit one uncommon character (e.g. 菉). Require an organisation,
    # the same representative and full address (or the identical one-character
    # OCR error in that address). Different house numbers never qualify.
    # Never fuzzy-match people or use a similar name alone as deletion proof.
    a, b = _clean(old.get("dwmc")), _clean(row.get("dwmc"))
    address = _clean(old.get("dwzsd"))
    representative = _clean(old.get("fddbrxm"))
    changed = _single_character_change(a, b)
    other_address = _clean(row.get("dwzsd"))
    if (min(len(a), len(b)) < 8 or not address or not representative or not changed
            or not other_address
            or (address != other_address and _single_character_change(address, other_address) != changed)
            or representative != _clean(row.get("fddbrxm"))):
        return False
    return True


def _identity(row):
    def clean(value):
        return re.sub(r"\s+", "", str(value or "")).upper()
    return (clean(row.get("ssdw")), clean(row.get("xm") or row.get("dwmc")),
            clean(row.get("zjhm") or row.get("zzhm")))


def duplicate_ids(before, after, agents):
    """Keep pre-OCR, documented IDs; never guess by array order or party type.

    Names alone across roles are not identity evidence. Conflicting document
    numbers and ambiguous same-name parties must remain for human review.
    Protect IDs referenced by agents or another party as well.
    """
    protected = set()
    for row in agents:
        protected.update(str(row.get("bdlrid") or "").split(","))
    protected.update(str(row.get("pcGlbgId") or "") for row in after)
    originals = {str(row.get("id")): row for row in before if row.get("id") and _identity(row)[2]}
    result = []
    for row in after:
        row_id = str(row.get("id") or "")
        role, name, document = _identity(row)
        if not row_id or row_id in originals or row_id in protected or not role or not name:
            continue
        matches = [old for old in originals.values()
                   if _identity(old)[0] == role
                   and (_identity(old)[1] == name
                        or (not document and _proven_organisation_ocr_variant(old, row)))
                   and (not document or _identity(old)[2] == document)]
        if len(matches) != 1:
            continue
        old = matches[0]
        # With no document, conflicting addresses are evidence of ambiguity.
        address = re.sub(r"\s+", "", str(row.get("dz") or row.get("dwzsd") or ""))
        old_address = re.sub(r"\s+", "", str(old.get("dz") or old.get("dwzsd") or ""))
        if (not document and address and old_address and address != old_address
                and not _proven_organisation_ocr_variant(old, row)):
            continue
        result.append(row_id)
    return result


async def reconcile_after_ocr(draft_id, before, call, *, include_detail=False):
    path = f"/yzw-zxfw-lafw/api/v3/layy/layyxq/{draft_id}/0"
    detail = await call("GET", path)
    if not isinstance(detail, dict) or not isinstance(detail.get("dsrs"), list):
        raise RuntimeError("无法回读识别后的官网当事人")
    layy = detail.get("layy") or {}
    if layy.get("id") != draft_id or layy.get("zt") != "11800007-100":
        raise RuntimeError("仅允许校正当前待提交草稿")
    rows = detail["dsrs"]
    original_ids = {str(row["id"]) for row in before if row.get("id") and _identity(row)[2]}
    if not original_ids.issubset({str(row.get("id")) for row in rows}):
        raise RuntimeError("识别后原有当事人标识发生变化，请核对草稿")
    removed = duplicate_ids(before, rows, detail.get("dlrs") or [])
    for row_id in removed:
        await call("DELETE", f"/yzw-zxfw-lafw/api/v3/layy/dsr/{draft_id}/{row_id}")
    if removed:
        detail = await call("GET", path)
        if not isinstance(detail, dict) or not isinstance(detail.get("dsrs"), list):
            raise RuntimeError("无法核验官网去重结果")
        ids = {str(row.get("id")) for row in detail["dsrs"]}
        if ids.intersection(removed) or not original_ids.issubset(ids):
            raise RuntimeError("官网尚未确认当事人去重结果")
    if duplicate_ids(before, detail["dsrs"], []):
        raise RuntimeError("重复卡存在关联关系，需核对后再继续")
    return (len(removed), detail) if include_detail else len(removed)


def make_ocr_handler(get_db, call, log):
    locks = {}

    async def handle(route):
        request = route.request
        parsed = urlsplit(request.url)
        detail_match = DETAIL_PATH.fullmatch(parsed.path)
        if request.method != "GET" or parsed.hostname != "zxfw.court.gov.cn" or (parsed.path != OCR_PATH and not detail_match):
            await route.continue_()
            return
        draft_ids = [detail_match[1]] if detail_match else parse_qs(parsed.query).get("layyId", [])
        if len(draft_ids) != 1:
            await route.continue_()
            return
        draft_id = draft_ids[0]
        with get_db() as conn:
            job = conn.execute(
                "SELECT id,status FROM automated_filing_jobs WHERE json_extract(facts_json,'$.api_draft_id')=?",
                (draft_id,),
            ).fetchone()
        if not job:
            await route.continue_()
            return
        async with locks.setdefault(draft_id, asyncio.Lock()):
            try:
                # Do not race an unfinished Token API workflow or silently
                # replay a timed-out OCR request through route.continue_().
                with get_db() as conn:
                    status = conn.execute("SELECT status FROM automated_filing_jobs WHERE id=?", (job["id"],)).fetchone()[0]
                if status != "api_service_address_generated":
                    if detail_match:
                        await route.continue_()
                        return
                    raise RuntimeError("请等待 APEX 当事人写入完成后再进入下一步")
                if detail_match:
                    response = await route.fetch(timeout=90000, max_retries=0, max_redirects=0)
                    body = await response.json()
                    if response.status != 200 or not isinstance(body, dict) or body.get("code") != 200:
                        await route.fulfill(response=response)
                        return
                    page_detail = body.get("data")
                    if not isinstance(page_detail, dict) or not isinstance(page_detail.get("dsrs"), list):
                        raise RuntimeError("无法核验官网页面当事人数据")
                    removed, verified = await reconcile_after_ocr(draft_id, page_detail["dsrs"], call, include_detail=True)
                    # A prior cleanup can have removed a row while this page
                    # response still contains it. Only discard proven copies;
                    # never silently hide an unknown/manual card from the UI.
                    obsolete = set(duplicate_ids(verified["dsrs"], page_detail["dsrs"], page_detail.get("dlrs") or []))
                    verified_ids = {row.get("id") for row in verified["dsrs"]}
                    if any(row.get("id") not in verified_ids and row.get("id") not in obsolete
                           for row in page_detail["dsrs"]):
                        raise RuntimeError("官网页面与回读数据尚未一致，请重新打开草稿")
                    page_detail["dsrs"] = verified["dsrs"]
                    log("info", f"官网页面当事人数据已核验：{len(verified['dsrs'])} 张，清理 {removed} 张，过期重复卡 {len(obsolete)} 张（APEX 任务 {job['id']}）")
                    # Deliver the actual verified rows to the wizard's
                    # sessionStorage, not just a successful OCR response.
                    headers = {key: value for key, value in response.headers.items()
                               if key.lower() not in {"content-length", "content-encoding", "etag"}}
                    headers["cache-control"] = "no-store"
                    await route.fulfill(response=response, headers=headers, json=body)
                    return
                before = await call("GET", f"/yzw-zxfw-lafw/api/v3/layy/layyxq/{draft_id}/0")
                if (not isinstance(before, dict) or not isinstance(before.get("dsrs"), list)
                        or (before.get("layy") or {}).get("id") != draft_id
                        or (before.get("layy") or {}).get("zt") != "11800007-100"):
                    raise RuntimeError("无法确认当前官网待提交草稿")
                response = await route.fetch(timeout=90000, max_retries=0, max_redirects=0)
                body = await response.json()
                if response.status != 200 or not isinstance(body, dict) or body.get("code") != 200:
                    await route.fulfill(response=response)
                    return
                removed = await reconcile_after_ocr(draft_id, before["dsrs"], call)
                if removed and not body.get("data"):
                    # The site's null branch reuses stale sessionStorage
                    # instead of reading layyxq. Do not advance with stale cards.
                    raise RuntimeError("已清理重复当事人，请重新打开草稿后继续")
                log("info", f"官网下一步识别已核验，清理重复当事人 {removed} 张（APEX 任务 {job['id']}）")
                await route.fulfill(response=response)
            except Exception as exc:
                log("warning", f"官网识别后当事人核验未完成，已停止进入下一页（APEX 任务 {job['id']}）")
                # A failed guard must neither release a success nor retry the
                # write. The court's normal API error handling displays this.
                await route.fulfill(status=409, content_type="application/json", body=json.dumps({
                    "code": 409, "message": (str(exc) if isinstance(exc, RuntimeError) else
                        "APEX 未完成当事人防重复核验，请在 APEX 复核草稿后重新打开；本次未进入下一页。"),
                }, ensure_ascii=False))

    return handle
