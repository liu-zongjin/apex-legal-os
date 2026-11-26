"""Document generator pages, options, downloads and history."""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from functools import partial
from pathlib import Path
from typing import Callable, List

import aiofiles
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .document_rendering import (
    PowerAttorneyRequest, RepIdentityCertRequest, SuohanRequest,
    generate_power_attorney_docx, generate_rep_identity_cert_docx, generate_suohan_docx,
)
from .finchina_mcp import FinChinaError, lookup_company_profile_with_legal_representative_title


class SuohanOptionCreate(BaseModel):
    type: str  # court, client, lawyer, party, caseType, stage
    name: str
    phone: str = ""  # 仅用于lawyer
    province: str = ""  # 仅用于court
    city: str = ""  # 仅用于court
    category: str = ""  # 仅用于caseType


class ClientDetailsRequest(BaseModel):
    name: str
    details: dict


class AuthorityTemplateRequest(BaseModel):
    authorities: List[str]


class CustomEntrustTypeRequest(BaseModel):
    label: str


POWER_ATTORNEY_ENTRUST_TYPES = {
    "plaintiff", "defendant", "appellant", "appellee", "arbApplicant",
    "arbRespondent", "execApplicant", "execRespondent", "execObjection", "bankruptcy"
}


def _is_valid_power_attorney_entrust_type(conn: sqlite3.Connection, entrust_type: str) -> bool:
    """固定类别或用户创建的类别均可保存授权内容。"""
    if entrust_type in POWER_ATTORNEY_ENTRUST_TYPES:
        return True
    return conn.execute(
        "SELECT 1 FROM power_attorney_custom_entrust_types WHERE id=?", (entrust_type,)
    ).fetchone() is not None


def save_document_history(doc_type: str, data: dict, *, get_db: Callable[[], sqlite3.Connection]):
    """保存文档生成历史"""
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO document_history
                (doc_type, court, clients, lawyers, parties, case_type, stages,
                 case_number, date, lawyer_contacts, rep_name, rep_title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_type,
                data.get("court", ""),
                json.dumps(data.get("clients", []), ensure_ascii=False),
                json.dumps(data.get("lawyers", []), ensure_ascii=False),
                json.dumps(data.get("parties", []), ensure_ascii=False),
                data.get("caseType", ""),
                json.dumps(data.get("stages", []), ensure_ascii=False),
                data.get("caseNumber", ""),
                data.get("date", ""),
                json.dumps(data.get("lawyerContacts", []), ensure_ascii=False),
                str(data.get("repName") or ""),
                str(data.get("repTitle") or ""),
            ))
            conn.commit()
        except Exception as e:
            print(f"保存历史记录失败: {e}")


class RepDetailsRequest(BaseModel):
    repName: str
    clientName: str
    title: str = ""


def create_router(
    get_db: Callable[[], sqlite3.Connection],
    *,
    frontend_dir: Path,
) -> APIRouter:
    router = APIRouter()
    render_suohan = partial(generate_suohan_docx, get_db=get_db)
    render_power_attorney = partial(generate_power_attorney_docx, get_db=get_db, frontend_dir=frontend_dir)
    save_history = partial(save_document_history, get_db=get_db)

    @router.get("/suohan-generator")
    async def suohan_generator():
        """所函生成器页面"""
        file_path = frontend_dir / "suohan-generator.html"
        if file_path.exists():
            async with aiofiles.open(str(file_path), mode='r', encoding='utf-8') as f:
                content = await f.read()
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            return HTMLResponse(content=content, headers=headers)
        else:
            raise HTTPException(status_code=404, detail="所函生成器页面不存在")


    @router.get("/api/suohan/options")
    async def get_suohan_options(type: str = None):
        """获取所函备选库数据"""
        with get_db() as conn:
            cursor = conn.cursor()
            result = {}

            tables = {
                'court': ('suohan_courts', 'name, province, city'),
                'client': ('suohan_clients', 'name'),
                'lawyer': ('suohan_lawyers', 'name, phone'),
                'party': ('suohan_parties', 'name'),
                'caseType': ('suohan_case_types', 'name, category'),
                'stage': ('suohan_stages', 'name')
            }

            if type and type in tables:
                table, fields = tables[type]
                cursor.execute(f"SELECT {fields} FROM {table} ORDER BY name")
                rows = cursor.fetchall()
                if type == 'court':
                    result[type] = [{'name': r[0], 'province': r[1], 'city': r[2]} for r in rows]
                elif type == 'lawyer':
                    result[type] = [{'name': r[0], 'phone': r[1]} for r in rows]
                elif type == 'caseType':
                    result[type] = [{'name': r[0], 'category': r[1]} for r in rows]
                else:
                    result[type] = [{'name': r[0]} for r in rows]
            else:
                # 返回所有类型
                for t, (table, fields) in tables.items():
                    cursor.execute(f"SELECT {fields} FROM {table} ORDER BY name")
                    rows = cursor.fetchall()
                    if t == 'court':
                        result[t] = [{'name': r[0], 'province': r[1], 'city': r[2]} for r in rows]
                    elif t == 'lawyer':
                        result[t] = [{'name': r[0], 'phone': r[1]} for r in rows]
                    elif t == 'caseType':
                        result[t] = [{'name': r[0], 'category': r[1]} for r in rows]
                    else:
                        result[t] = [{'name': r[0]} for r in rows]

            return result


    @router.post("/api/suohan/options")
    async def add_suohan_option(option: SuohanOptionCreate):
        """添加所函备选库数据"""
        with get_db() as conn:
            cursor = conn.cursor()

            try:
                if option.type == 'court':
                    cursor.execute(
                        "INSERT INTO suohan_courts (name, province, city) VALUES (?, ?, ?)",
                        (option.name, option.province, option.city)
                    )
                elif option.type == 'client':
                    cursor.execute("INSERT INTO suohan_clients (name) VALUES (?)", (option.name,))
                elif option.type == 'lawyer':
                    cursor.execute(
                        "INSERT INTO suohan_lawyers (name, phone) VALUES (?, ?)",
                        (option.name, option.phone)
                    )
                elif option.type == 'party':
                    cursor.execute("INSERT INTO suohan_parties (name) VALUES (?)", (option.name,))
                elif option.type == 'caseType':
                    cursor.execute(
                        "INSERT INTO suohan_case_types (name, category) VALUES (?, ?)",
                        (option.name, option.category)
                    )
                elif option.type == 'stage':
                    cursor.execute("INSERT INTO suohan_stages (name) VALUES (?)", (option.name,))
                else:
                    raise HTTPException(status_code=400, detail="无效的数据类型")

                conn.commit()
                return {"success": True, "message": "添加成功"}
            except sqlite3.IntegrityError:
                raise HTTPException(status_code=400, detail="该项目已存在")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


    @router.delete("/api/suohan/options")
    async def delete_suohan_option(type: str, name: str):
        """删除所函备选库数据"""
        with get_db() as conn:
            cursor = conn.cursor()

            tables = {
                'court': 'suohan_courts',
                'client': 'suohan_clients',
                'lawyer': 'suohan_lawyers',
                'party': 'suohan_parties',
                'caseType': 'suohan_case_types',
                'stage': 'suohan_stages'
            }

            if type not in tables:
                raise HTTPException(status_code=400, detail="无效的数据类型")

            table = tables[type]
            cursor.execute(f"DELETE FROM {table} WHERE name = ?", (name,))
            conn.commit()

            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="未找到该项目")

            return {"success": True, "message": "删除成功"}


    @router.post("/api/suohan/generate")
    async def generate_suohan(request: SuohanRequest, artifact_only: bool = False):
        """生成所函文档"""
        try:
            if request.format == "word":
                content = render_suohan(request)
                media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                filename = f"所函_{request.court}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
            else:
                raise HTTPException(status_code=400, detail="暂不支持PDF格式")

            from fastapi.responses import StreamingResponse
            from io import BytesIO

            # 处理中文文件名（RFC 5987）
            from urllib.parse import quote
            filename_encoded = quote(filename)
            content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"
            from .document_bundle_artifacts import store_document_bundle_artifact
            artifact = store_document_bundle_artifact(
                get_db,
                content,
                filename,
                request.model_dump(),
            )

            # 文书合集页的直接用章流程不需要再次下载文件。返回 JSON 可避免
            # 反向代理或跨域响应处理过滤自定义响应头导致成品标识丢失。
            if artifact_only:
                return {
                    "artifact_id": artifact["artifact_id"],
                    "sha256": artifact["sha256"],
                    "filename": filename,
                }

            return StreamingResponse(
                BytesIO(content),
                media_type=media_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "X-APEX-Document-Artifact-Id": artifact["artifact_id"],
                    "X-APEX-Document-Artifact-Sha256": artifact["sha256"],
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成文档失败: {str(e)}")


    @router.get("/api/document-generators/client-profile")
    async def get_document_generator_client_profile(name: str = Query(..., min_length=1, max_length=200)):
        """Return the current profile from 案件管理→委托人管理 for document generators."""
        with get_db() as conn:
            row = conn.execute(
                """SELECT name, client_type, identity_code, address, legal_representative,
                      legal_representative_title, contact_person, phone, contacts_json
               FROM case_manager_clients WHERE name=?""",
                (name.strip(),),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="委托人管理中未找到该委托人")
        try:
            contacts = json.loads(row[8] or "[]")
            if not isinstance(contacts, list):
                contacts = []
        except (TypeError, ValueError, json.JSONDecodeError):
            contacts = []
        contacts = [
            {"name": str(item.get("name") or "").strip(), "phone": str(item.get("phone") or "").strip()}
            for item in contacts if isinstance(item, dict)
        ]
        contacts = [item for item in contacts if item["name"] or item["phone"]]
        return {
            "name": row[0], "client_type": row[1], "identity_code": row[2] or "",
            "address": row[3] or "", "legal_representative": row[4] or "",
            "legal_representative_title": row[5] or "",
            "contact_person": row[6] or "", "phone": row[7] or "",
            "contacts": contacts or ([{"name": (row[6] or "").strip(), "phone": (row[7] or "").strip()}] if (row[6] or row[7]) else []),
        }


    @router.post("/api/document-generators/finchina-profile")
    async def lookup_document_generator_finchina_profile(request: Request):
        """Explicit user-triggered 万得财汇 lookup; never called automatically."""
        body = await request.json()
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="请先输入企业名称")
        try:
            return await lookup_company_profile_with_legal_representative_title(name)
        except FinChinaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


    @router.get("/api/power-attorney/custom-entrust-types")
    async def get_custom_entrust_types():
        """获取用户新增的委托类别。"""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, label FROM power_attorney_custom_entrust_types ORDER BY created_at, label"
            ).fetchall()
        return {"types": [{"id": row[0], "label": row[1]} for row in rows]}


    @router.post("/api/power-attorney/custom-entrust-types")
    async def create_custom_entrust_type(request: CustomEntrustTypeRequest):
        """新增委托类别；新类别不携带任何默认授权内容。"""
        label = request.label.strip()
        if not label or len(label) > 50:
            raise HTTPException(status_code=400, detail="委托类别应为 1 至 50 个字符")
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id, label FROM power_attorney_custom_entrust_types WHERE label=?", (label,)
            ).fetchone()
            if existing:
                return {"id": existing[0], "label": existing[1], "created": False}
            entrust_type = f"custom_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO power_attorney_custom_entrust_types (id, label) VALUES (?, ?)",
                (entrust_type, label),
            )
            conn.commit()
        return {"id": entrust_type, "label": label, "created": True}


    @router.get("/api/power-attorney/authority-templates")
    async def get_authority_templates():
        """获取用户保存的各委托类别授权内容。"""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT entrust_type, authorities_json FROM power_attorney_authority_templates"
            ).fetchall()
        templates = {}
        for row in rows:
            try:
                values = json.loads(row[1] or "[]")
                templates[row[0]] = [str(item).strip() for item in values if str(item).strip()]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return {"templates": templates}


    @router.put("/api/power-attorney/authority-templates/{entrust_type}")
    async def save_authority_template(entrust_type: str, request: AuthorityTemplateRequest):
        """保存某一委托类别的默认授权内容。"""
        authorities = [item.strip() for item in request.authorities if item.strip()]
        if not authorities:
            raise HTTPException(status_code=400, detail="授权内容不能为空")
        with get_db() as conn:
            if not _is_valid_power_attorney_entrust_type(conn, entrust_type):
                raise HTTPException(status_code=400, detail="无效的委托类别")
            conn.execute(
                """INSERT INTO power_attorney_authority_templates (entrust_type, authorities_json, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(entrust_type) DO UPDATE SET
                 authorities_json=excluded.authorities_json, updated_at=CURRENT_TIMESTAMP""",
                (entrust_type, json.dumps(authorities, ensure_ascii=False)),
            )
            conn.commit()
        return {"success": True, "entrustType": entrust_type, "authorities": authorities}


    @router.get("/api/power-attorney/client-details")
    async def get_client_details():
        """获取所有委托人详细信息"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, type, credit_code, address, legal_representative, id_card, title FROM power_attorney_client_details")
            rows = cursor.fetchall()
            details = {}
            for row in rows:
                details[row[0]] = {
                    "type": row[1],
                    "creditCode": row[2],
                    "address": row[3],
                    "legalRepresentative": row[4],
                    "idCard": row[5],
                    "title": row[6] if len(row) > 6 else ""
                }
            return {"details": details}


    @router.post("/api/power-attorney/client-details")
    async def save_client_details(request: ClientDetailsRequest):
        """保存委托人详细信息"""
        with get_db() as conn:
            cursor = conn.cursor()
            details = request.details
            try:
                cursor.execute("""
                INSERT OR REPLACE INTO power_attorney_client_details
                (name, type, credit_code, address, legal_representative, id_card, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                    request.name,
                    details.get("type", "legal"),
                    details.get("creditCode", ""),
                    details.get("address", ""),
                    details.get("legalRepresentative", ""),
                    details.get("idCard", "")
                ))
                conn.commit()
                return {"success": True}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


    @router.get("/api/suohan/history")
    async def get_suohan_history():
        """获取所函历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, doc_type, court, clients, lawyers, parties, case_type, stages, case_number, date, lawyer_contacts
            FROM document_history
            WHERE doc_type = 'suohan'
            ORDER BY created_at DESC
            LIMIT 10
        """)
            rows = cursor.fetchall()
            history = []
            for row in rows:
                try:
                    clients = json.loads(row[3]) if row[3] else []
                    lawyers = json.loads(row[4]) if row[4] else []
                    parties = json.loads(row[5]) if row[5] else []
                    lawyer_contacts = json.loads(row[10]) if row[10] else []
                    history.append({
                        "id": row[0],
                        "court": row[2],
                        "clients": clients,
                        "lawyers": lawyers,
                        "parties": parties,
                        "caseType": row[6],
                        "stages": json.loads(row[7]) if row[7] else [],
                        "caseNumber": row[8],
                        "date": row[9],
                        "lawyerContacts": lawyer_contacts
                    })
                except:
                    continue
            return {"history": history}


    @router.delete("/api/suohan/history/{record_id}")
    async def delete_suohan_history(record_id: int):
        """删除所函历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM document_history WHERE id = ? AND doc_type = 'suohan'", (record_id,))
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="记录不存在")
            return {"ok": True}


    @router.post("/api/suohan/save-history")
    async def save_suohan_history(request: Request):
        """手动保存所函到历史记录"""
        try:
            data = await request.json()
            save_history('suohan', data)
            return {"ok": True, "message": "已保存到历史记录"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


    @router.get("/api/power-attorney/history")
    async def get_power_attorney_history():
        """获取授权委托书历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, doc_type, court, clients, lawyers, parties, case_type, stages, case_number, date, lawyer_contacts
            FROM document_history
            WHERE doc_type = 'power_attorney'
            ORDER BY created_at DESC
            LIMIT 10
        """)
            rows = cursor.fetchall()
            history = []
            for row in rows:
                try:
                    clients = json.loads(row[3]) if row[3] else []
                    lawyers = json.loads(row[4]) if row[4] else []
                    parties = json.loads(row[5]) if row[5] else []
                    lawyer_contacts = json.loads(row[10]) if row[10] else []
                    history.append({
                        "id": row[0],
                        "court": row[2],
                        "clients": clients,
                        "lawyers": lawyers,
                        "parties": parties,
                        "caseType": row[6],
                        "stages": json.loads(row[7]) if row[7] else [],
                        "caseNumber": row[8],
                        "date": row[9],
                        "lawyerContacts": lawyer_contacts
                    })
                except:
                    continue
            return {"history": history}


    @router.delete("/api/power-attorney/history/{record_id}")
    async def delete_power_attorney_history(record_id: int):
        """删除授权委托书历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM document_history WHERE id = ? AND doc_type = 'power_attorney'", (record_id,))
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="记录不存在")
            return {"ok": True}


    @router.post("/api/power-attorney/save-history")
    async def save_power_attorney_history(request: Request):
        """手动保存授权委托书到历史记录"""
        try:
            data = await request.json()
            save_history('power_attorney', data)
            return {"ok": True, "message": "已保存到历史记录"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


    @router.post("/api/power-attorney/generate")
    async def generate_power_attorney(request: PowerAttorneyRequest):
        """生成授权委托书文档"""
        try:
            content = render_power_attorney(request)

            # 保存历史记录
            save_history('power_attorney', {
                "clients": [request.clientName],
                "lawyers": [l['name'] for l in request.lawyers if l.get('name')],
                "parties": request.parties,
                "caseType": request.caseType,
                "caseNumber": request.caseNumber,
                "date": request.date,
                "lawyerContacts": request.lawyers
            })

            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename = f"授权委托书_{request.clientName}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.docx"

            from fastapi.responses import StreamingResponse
            from io import BytesIO
            from urllib.parse import quote

            filename_encoded = quote(filename)
            content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"

            return StreamingResponse(
                BytesIO(content),
                media_type=media_type,
                headers={"Content-Disposition": content_disposition}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成文档失败: {str(e)}")


    @router.get("/power-attorney-generator")
    async def power_attorney_generator():
        """授权委托书生成器页面"""
        file_path = frontend_dir / "power-attorney-generator.html"
        if file_path.exists():
            async with aiofiles.open(str(file_path), mode='r', encoding='utf-8') as f:
                content = await f.read()
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache"
            }
            return HTMLResponse(content=content, headers=headers)
        else:
            raise HTTPException(status_code=404, detail="授权委托书生成器页面不存在")


    @router.post("/api/rep-identity-cert/rep-details")
    async def save_rep_details(request: RepDetailsRequest):
        """保存法定代表人详情（用于自动填充）"""
        with get_db() as conn:
            cursor = conn.cursor()
            try:
                # 检查是否已存在该委托人记录
                cursor.execute("SELECT id FROM power_attorney_client_details WHERE name = ?", (request.clientName,))
                row = cursor.fetchone()

                if row:
                    # 更新现有记录
                    cursor.execute("""
                    UPDATE power_attorney_client_details
                    SET legal_representative = ?, title = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE name = ?
                """, (request.repName, request.title, request.clientName))
                else:
                    # 插入新记录
                    cursor.execute("""
                    INSERT INTO power_attorney_client_details
                    (name, type, credit_code, address, legal_representative, id_card, title)
                    VALUES (?, 'legal', '', '', ?, '', ?)
                """, (request.clientName, request.repName, request.title))

                conn.commit()
                return {"ok": True}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


    @router.get("/api/rep-identity-cert/history")
    async def get_rep_identity_cert_history():
        """获取法定代表人证明书历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, doc_type, clients, rep_name, rep_title, date
            FROM document_history
            WHERE doc_type = 'rep_identity_cert'
            ORDER BY created_at DESC, id DESC
            LIMIT 10
        """)
            rows = cursor.fetchall()
            history = []
            for row in rows:
                try:
                    clients = json.loads(row[2]) if row[2] else []
                    history.append({
                        "id": row[0],
                        "clients": clients,
                        "repName": row[3] or "",
                        "repTitle": row[4] or "",
                        "date": row[5] or ""
                    })
                except:
                    continue
            return {"history": history}


    @router.delete("/api/rep-identity-cert/history/{record_id}")
    async def delete_rep_identity_cert_history(record_id: int):
        """删除法定代表人证明书历史记录"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM document_history WHERE id = ? AND doc_type = 'rep_identity_cert'", (record_id,))
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="记录不存在")
            return {"ok": True}


    @router.post("/api/rep-identity-cert/save-history")
    async def save_rep_identity_cert_history(request: Request):
        """手动保存法定代表人证明书到历史记录"""
        try:
            data = await request.json()
            save_history('rep_identity_cert', {
                "clients": data.get("clients", []),
                "repName": data.get("repName", ""),
                "repTitle": data.get("repTitle", ""),
                "date": data.get("date", "")
            })
            return {"ok": True, "message": "已保存到历史记录"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


    @router.post("/api/rep-identity-cert/generate")
    async def generate_rep_identity_cert(request: RepIdentityCertRequest):
        """生成法定代表人身份证明书文档"""
        try:
            from io import BytesIO

            content = generate_rep_identity_cert_docx(request)

            # 保存历史记录
            save_history('rep_identity_cert', {
                "clients": [request.clientName],
                "repName": request.repName,
                "repTitle": request.repTitle,
                "date": request.date
            })

            from fastapi.responses import StreamingResponse
            from urllib.parse import quote

            media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            filename = f'法定代表人身份证明书-{request.clientName}.docx'
            filename_encoded = quote(filename)
            content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"

            return StreamingResponse(
                BytesIO(content),
                media_type=media_type,
                headers={"Content-Disposition": content_disposition}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"生成文档失败: {str(e)}")


    @router.get("/rep-identity-cert-generator")
    async def rep_identity_cert_generator():
        """法定代表人证明书生成器页面"""
        file_path = frontend_dir / "rep-identity-cert-generator.html"
        if file_path.exists():
            async with aiofiles.open(str(file_path), mode='r', encoding='utf-8') as f:
                content = await f.read()
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache"
            }
            return HTMLResponse(content=content, headers=headers)
        else:
            raise HTTPException(status_code=404, detail="法定代表人证明书生成器页面不存在")

    return router
