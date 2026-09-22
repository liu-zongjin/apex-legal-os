"""MCP 服务接入管理。

这些服务统一在「设置 → 管理 → MCP 服务」页面管理：查看已接入 /
未配置状态、维护本机私有配置中的授权信息，并对每个服务执行一步
标准的握手测试，确认连接与授权是否可用。

写回方式与 AI API 管理一致：值存放在 ``local_ai_secrets.py``（本机
私有文件，git 忽略）。部署时通过真实环境变量托管的值在线程中只读。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import ai_config
from . import aluris_mcp
from . import finchina_mcp
from . import national_law_mcp
from . import pkulaw_mcp
from . import qcc_mcp
from . import quark_drive_mcp
from . import qq_mail_mcp
from . import yuandian_mcp


class MCPConfigError(RuntimeError):
    pass


# 启动时已存在的真实环境变量即视为「部署托管」，页面只读。
_ORIGINAL_ENV = dict(os.environ)

_MCP_SERVERS: List[Dict[str, Any]] = [
    {
        "id": "aluris",
        "name": "法随·案例库",
        "caption": "最高人民法院公报案例检索",
        "url_name": "ALURIS_MCP_URL",
        "default_url": "https://aluris.top/mcp",
        "key_name": None,
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "",
        "tools": ["权威案例检索", "公报精确校验"],
        "color": "#b45309",
        "description": "通过深圳法随提供的案例检索服务，可检索最高人民法院公报案例等权威裁判内容。",
        "portal_url": "https://open.chineselaw.com/#solutions",
    },
    {
        "id": "national_law",
        "name": "国家法律法规数据库",
        "caption": "现行有效法规检索",
        "url_name": "NPC_LAW_DB_URL",
        "default_url": "https://flk.npc.gov.cn",
        "key_name": None,
        "protocol": "http_api",
        "url_label": "接口地址",
        "key_label": "",
        "tools": ["法规语义检索", "更新检测与回滚"],
        "color": "#168a73",
        "description": "全国人大法律法规数据库公开接口，用于检索与同步现行有效法规。",
    },
    {
        "id": "yuandian_case",
        "name": "元典·案例库",
        "caption": "案例语义检索与详情核验",
        "url_name": "YUANDIAN_CASE_MCP_URL",
        "default_url": "https://open.chineselaw.com/mcp/case/stream",
        "key_name": "YUANDIAN_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["权威案例检索", "普通案例检索", "案例详情核验", "账户余额"],
        "color": "#2563a6",
        "description": "元典开放性案例服务，覆盖权威案例与普通案例，可逐案调用详情接口核验。",
        "portal_url": "https://open.chineselaw.com/#solutions",
    },
    {
        "id": "yuandian_law",
        "name": "元典·法律法规",
        "caption": "法规语义检索",
        "url_name": "YUANDIAN_LAW_MCP_URL",
        "default_url": "https://open.chineselaw.com/mcp/law/stream",
        "key_name": "YUANDIAN_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["法规语义检索"],
        "color": "#2563a6",
        "description": "元典法律法规语义检索服务，与元典·案例库共享同一个授权密钥。",
        "portal_url": "https://open.chineselaw.com/#solutions",
    },
    {
        "id": "pkulaw_case",
        "name": "北大法宝·案例库",
        "caption": "权威案例检索",
        "url_name": "PKULAW_CASE_SEMANTIC_URL",
        "default_url": "https://apim-gateway.pkulaw.com/mcp-case-search-service",
        "key_name": "PKULAW_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["案例语义检索", "权威案例检索", "案例详情"],
        "color": "#5b52a3",
        "description": "北大法宝司法数据库案例检索服务，提供权威案例与法条引用能力。",
        "portal_url": "https://mcp.pkulaw.com/apis/1990710527638245376",
    },
    {
        "id": "pkulaw_law",
        "name": "北大法宝·法律法规",
        "caption": "法条检索与引用核验",
        "url_name": "PKULAW_LAW_SEARCH_URL",
        "default_url": "https://apim-gateway.pkulaw.com/mcp-law-search-service",
        "key_name": "PKULAW_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["法条检索", "条文详情", "引用核验"],
        "color": "#9c3d36",
        "description": "北大法宝法规数据库，支持法条检索与引用核验，与北大法宝·案例库共享授权密钥。",
        "portal_url": "https://mcp.pkulaw.com/apis/1990710527638245376",
    },
    {
        "id": "finchina",
        "name": "万得财汇",
        "caption": "企业工商信息核验",
        "url_name": "FINCHINA_MCP_URL",
        "default_url": "https://mcp.finchina.com/finchina-data-mcp-server/mcp",
        "key_name": "FINCHINA_API_KEY",
        "protocol": "finchina",
        "url_label": "MCP 地址",
        "key_label": "API Key",
        "tools": ["企业画像", "企业候选检索", "企业涉诉信息"],
        "color": "#3175d4",
        "description": "万得旗下企业信息服务，提供公司画像、股权与涉诉等企业信息核验。",
    },
    {
        "id": "quark_drive",
        "name": "夸克网盘",
        "caption": "个人网盘文件检索与问答",
        "url_name": "QUARK_DRIVE_SKILL_DIR",
        "default_url": str(Path.home() / ".codex" / "skills" / "quarkclouddrive"),
        "key_name": None,
        "protocol": "quark_skill",
        "url_label": "本机 Skill 位置",
        "key_label": "",
        "tools": ["网盘文件检索", "文件内容总结", "文件知识问答"],
        "color": "#ff6a00",
        "description": "使用已授权的夸克网盘官方 Skill，只读检索相关文件并基于文件内容回答问题。",
    },
    # ── 企查查开放 MCP：10 个 Streamable HTTP Server 共享 QCC_MCP_AUTHORIZATION ──
    {
        "id": "qcc_company",
        "name": "企查查·企业信息",
        "caption": "工商登记与股权核验",
        "url_name": "QCC_COMPANY_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/company/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["企业实体识别", "工商登记信息", "股东与股权结构", "实际控制人", "受益所有人", "对外投资", "年报与财务", "分支机构", "上市信息"],
        "color": "#0e9f8a",
        "description": "企查查企业基座：按完整企业名称或统一社会信用代码核验工商登记、股权、实控人与受益所有人等企业基本面。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_risk",
        "name": "企查查·司法风险",
        "caption": "涉诉与信用风险扫描",
        "url_name": "QCC_RISK_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/risk/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["35维风险扫描", "失信/被执行/限高", "裁判文书", "立案与开庭", "股权出质/冻结", "行政处罚", "经营异常", "税务风险"],
        "color": "#0e9f8a",
        "description": "企查查风控大脑：企业自身、关联方与关键人四类主体的司法及信用风险扫描，可逐维度下钻明细。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_ipr",
        "name": "企查查·知识产权",
        "caption": "商标专利著作权核验",
        "url_name": "QCC_IPR_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/ipr/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["商标", "专利", "著作权", "软件著作权", "域名与备案", "公众号/小程序/网店"],
        "color": "#0e9f8a",
        "description": "企查查知产引擎：企业商标、专利、著作权与互联网资产（公众号、小程序、网店）检索核验。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_operation",
        "name": "企查查·经营信息",
        "caption": "资质许可与经营动态",
        "url_name": "QCC_OPERATION_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/operation/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["资质许可", "招投标信息", "招聘信息", "舆情新闻", "信用评价", "抽查检查", "进出口"],
        "color": "#0e9f8a",
        "description": "企查查经营罗盘：企业资质、行政许可、信用评价、舆情与经营动态信息。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_history",
        "name": "企查查·历史信息",
        "caption": "历史记录与变更档案",
        "url_name": "QCC_HISTORY_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/history/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["历史工商变更", "历史风险记录", "历史任职与投资"],
        "color": "#0e9f8a",
        "description": "企查查历史存档：企业及关键人的历史变更与历史风险记录（需开通历史信息服务）。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_executive",
        "name": "企查查·董监高画像",
        "caption": "高管任职与个人风险",
        "url_name": "QCC_EXECUTIVE_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/executive/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["任职与在外任职", "历史任职", "对外投资", "持股与受益", "个人司法风险"],
        "color": "#0e9f8a",
        "description": "企查查董监高画像：企业高管/自然人的任职、投资、持股及个人司法风险，企业和自然人双锚定。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_regulation",
        "name": "企查查·法律法规",
        "caption": "法规法条检索与核验",
        "url_name": "QCC_REGULATION_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/regulation/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["法规检索", "法条关键词检索", "法条语义检索", "法规/法条详情", "引用核验"],
        "color": "#0e9f8a",
        "description": "企查查法律数据库：法规、法条检索与详情，以及法律文本引用核验。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_case",
        "name": "企查查·司法案例",
        "caption": "普通与权威案例检索",
        "url_name": "QCC_CASE_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/case/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["普通案例检索", "权威案例检索", "案例详情", "案号核验"],
        "color": "#0e9f8a",
        "description": "企查查司法案例库：按案由、法院、审级、日期检索普通与权威裁判文书，支持案号核验。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_tender",
        "name": "企查查·招投标",
        "caption": "标讯与拟建项目",
        "url_name": "QCC_TENDER_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/tender/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["标讯检索与详情", "拟建项目", "企业标讯"],
        "color": "#0e9f8a",
        "description": "企查查招标查查：招投标公告、拟建项目与企业标讯检索。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_document",
        "name": "企查查·智能文档",
        "caption": "PDF/图片/Office 文档解析",
        "url_name": "QCC_DOCUMENT_MCP_URL",
        "default_url": "https://agent.qcc.com/mcp/document/stream",
        "key_name": "QCC_MCP_AUTHORIZATION",
        "protocol": "streamable_http",
        "url_label": "MCP 地址",
        "key_label": "Authorization",
        "tools": ["提交文档解析", "查询解析结果"],
        "color": "#0e9f8a",
        "description": "企查查智能文档解析：提交 PDF、图片、Office、WPS 文档并异步查询解析结果。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qcc_document_mcp",
        "name": "企查查·本地文档服务",
        "caption": "npx 本地进程解析文档",
        "url_name": "QCC_DOCUMENT_MCP_URL",
        "default_url": "npx -y qcc-document-mcp",
        "key_name": "QCC_DOCUMENT_AUTHORIZATION",
        "protocol": "stdio",
        "url_label": "启动命令",
        "key_label": "Authorization",
        "tools": ["本地文档解析", "解析结果查询"],
        "color": "#0e9f8a",
        "description": "qcc-document 的本地接入形态：通过 npx 启动官方 qcc-document-mcp 进程解析本地文件，授权值从 QCC_DOCUMENT_AUTHORIZATION 读取。",
        "portal_url": "https://agent.qcc.com/profile/credit/recharge",
    },
    {
        "id": "qq_mail",
        "name": "QQ邮箱",
        "caption": "查收邮件与发票附件收集",
        "url_name": "QQ_MAIL_ADDRESS",
        "default_url": "",
        "key_name": "QQ_MAIL_AUTH_CODE",
        "protocol": "imap_mail",
        "adapter_account": "qq_mail",
        "url_label": "邮箱地址",
        "key_label": "IMAP 授权码",
        "tools": ["查收邮件", "读取邮件", "收集发票附件"],
        "color": "#1e6fd9",
        "description": "通过 IMAP 直连 QQ 邮箱（imap.qq.com），查收邮件、读取正文并下载发票等附件到本机 uploads/邮箱发票 目录。授权码在 QQ 邮箱网页版「设置 → 应用 → 应用管理 → IMAP/SMTP服务」生成。",
        "portal_url": "https://mail.qq.com",
    },
    {
        "id": "qq_exmail",
        "name": "腾讯企业邮箱",
        "caption": "企业邮件与发票附件收集",
        "url_name": "EXMAIL_ADDRESS",
        "default_url": "",
        "key_name": "EXMAIL_AUTH_CODE",
        "protocol": "imap_mail",
        "adapter_account": "qq_exmail",
        "url_label": "邮箱地址",
        "key_label": "客户端专用密码",
        "tools": ["查收邮件", "读取邮件", "收集发票附件"],
        "color": "#0e9f8a",
        "description": "通过 IMAP 直连腾讯企业邮箱（imap.exmail.qq.com），查收邮件、读取正文并下载发票等附件到本机 uploads/企业邮箱发票 目录。客户端专用密码在网页版「设置 → 邮箱绑定 → 客户端专用密码」生成（需管理员开启该功能）。",
        "portal_url": "https://exmail.qq.com",
    },
    {
        "id": "netease_exmail",
        "name": "网易企业邮箱",
        "caption": "网易企业邮件与发票附件收集",
        "url_name": "NETEASE_EXMAIL_ADDRESS",
        "default_url": "",
        "key_name": "NETEASE_EXMAIL_AUTH_CODE",
        "optional_key_name": "NETEASE_EXMAIL_WEB_COOKIE",
        "optional_key_label": "网页版会话 Cookie（云附件）",
        "protocol": "imap_mail",
        "adapter_account": "netease_exmail",
        "url_label": "邮箱地址",
        "key_label": "客户端授权码",
        "tools": ["查收邮件", "读取邮件", "收集发票附件"],
        "color": "#d64545",
        "description": "通过 IMAP 直连网易企业邮箱（imap.qiye.163.com），查收邮件、读取正文并下载发票等附件到本机 uploads/网易企业邮箱发票 目录。请先在网易企业邮箱网页版开启 IMAP/SMTP 并生成客户端授权码。",
        "portal_url": "https://mail.qiye.163.com/static/sirius-web/?version=1789102496212/#mailbox",
    },
]

_CONFIG_NAMES = tuple(sorted({
    name
    for server in _MCP_SERVERS
    for name in (
        server["url_name"],
        server["key_name"],
        server.get("optional_key_name"),
    )
    if name
} | {quark_drive_mcp.FOLDER_SCOPES_ENV}))

_LOCAL_SECRETS_PATH = Path(ai_config.__file__).resolve().parent.parent / "local_ai_secrets.py"

_TEST_RESULTS: Dict[str, Dict[str, Any]] = {}


def _definition(server_id: str) -> Dict[str, Any]:
    for server in _MCP_SERVERS:
        if server["id"] == server_id:
            return server
    raise KeyError(server_id)


def _local_value(name: str, default: str = "") -> str:
    local = getattr(ai_config, "_local_ai_secrets", None)
    value = getattr(local, name, "") if local is not None else ""
    return str(value or default)


def _current_value(name: str, default: str = "") -> str:
    if name in _ORIGINAL_ENV:
        return str(_ORIGINAL_ENV[name])
    if name in os.environ:
        return str(os.environ[name])
    return _local_value(name, default)


def _is_managed(name: str) -> bool:
    return name in _ORIGINAL_ENV


def _mask_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••••••••{value[-4:]}"


def _mail_address_error(server: Dict[str, Any], value: str) -> str:
    """Return a user-facing validation message for IMAP account fields."""
    if server.get("protocol") != "imap_mail" or not value:
        return ""
    candidate = str(value).strip()
    if (
        "@" not in candidate
        or "://" in candidate
        or "/" in candidate
        or "#" in candidate
    ):
        return (
            f"{server['name']}的邮箱地址应填写完整邮箱账号（例如 name@example.com），"
            "网页登录地址请点击卡片上的“后台”打开"
        )
    return ""


def _server_payload(server: Dict[str, Any]) -> Dict[str, Any]:
    key_name = server.get("key_name")
    optional_key_name = server.get("optional_key_name")
    url = _current_value(server["url_name"], server["default_url"])
    key = _current_value(key_name) if key_name else ""
    optional_key = _current_value(optional_key_name) if optional_key_name else ""
    test_result = _TEST_RESULTS.get(server["id"])
    configuration_error = _mail_address_error(server, url)
    configured = bool(url and (not key_name or key))
    protocol_label = {
        "streamable_http": "Streamable HTTP",
        "http_api": "公开网页接口",
        "finchina": "Streamable HTTP + x-api-key",
        "stdio": "本地进程（stdio）",
        "quark_skill": "本机 MCP 适配",
        "imap_mail": "IMAP 邮箱直连",
    }.get(server["protocol"], server["protocol"])
    payload = {
        "id": server["id"],
        "name": server["name"],
        "caption": server["caption"],
        "description": server["description"],
        "url": url,
        "configured": configured,
        "usable": bool(configured and not configuration_error),
        "has_key": bool(key),
        "configuration_error": configuration_error,
        "needs_key": bool(key_name),
        "key_masked": _mask_value(key) if key_name else "",
        "managed_url": _is_managed(server["url_name"]),
        "managed_key": _is_managed(key_name) if key_name else True,
        "url_label": server["url_label"],
        "key_label": server["key_label"],
        "optional_key_name": optional_key_name or "",
        "optional_key_label": server.get("optional_key_label", ""),
        "optional_key_masked": _mask_value(optional_key) if optional_key_name else "",
        "optional_key_set": bool(optional_key),
        "managed_optional_key": _is_managed(optional_key_name) if optional_key_name else True,
        "protocol_label": protocol_label,
        "tools": server["tools"],
        "color": server["color"],
        "test": test_result,
        "portal_url": server.get("portal_url", ""),
    }
    if server["id"] == "quark_drive":
        scopes = quark_drive_mcp.configured_scopes()
        payload["folder_scope_count"] = len(scopes)
        payload["folder_scope_names"] = [item["name"] for item in scopes]
        payload["usage"] = quark_drive_mcp.usage_status()
    return payload


def _write_local_settings(values: Dict[str, str]) -> None:
    """原子写回本机私有配置，保留其它大写字符串配置。"""
    preserved: Dict[str, str] = {}
    local = getattr(ai_config, "_local_ai_secrets", None)
    if local is not None:
        for name, item in vars(local).items():
            if name.isupper() and isinstance(item, str):
                preserved[name] = item
    preserved.update(values)
    lines = ['"""Private AI credentials managed by the Legal Knowledge Base UI."""', ""]
    for name in sorted(preserved):
        if not name:
            continue
        lines.append(f"{name} = {preserved[name]!r}")
    lines.append("")
    _LOCAL_SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".local_ai_secrets.", suffix=".tmp", dir=str(_LOCAL_SECRETS_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, _LOCAL_SECRETS_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _reload_runtime() -> None:
    """把本机私有配置同步进进程环境并重载各 MCP 适配器模块。

    部署托管（_ORIGINAL_ENV）的名称保持只读，不被覆盖。仅把用户
    通过页面保存的非托管配置推入 os.environ，并重载模块，使模块级
    ``from .ai_config import ...`` 的绑定变量也能拿到新值。
    """
    # local_ai_secrets.py 是通过 ai_config 的自定义加载器读取的；单纯
    # 重载各 MCP 模块不会刷新这个对象，保存后会出现“已写入但回读为空”。
    # 先重载 ai_config，确保刚落盘的文件夹范围进入当前进程。
    try:
        importlib.reload(ai_config)
    except Exception:
        pass
    local = getattr(ai_config, "_local_ai_secrets", None)
    for name in _CONFIG_NAMES:
        if name in _ORIGINAL_ENV:
            continue
        value = getattr(local, name, "") if local is not None else ""
        if isinstance(value, str) and value:
            os.environ[name] = value
    for name in _CONFIG_NAMES:
        setattr(ai_config, name, _current_value(name))
    for module in (
        aluris_mcp,
        finchina_mcp,
        national_law_mcp,
        pkulaw_mcp,
        qcc_mcp,
        qq_mail_mcp,
        yuandian_mcp,
    ):
        try:
            importlib.reload(module)
        except Exception:
            continue
    for name in _CONFIG_NAMES:
        if name in _ORIGINAL_ENV:
            continue
        if not _current_value(name):
            os.environ.pop(name, None)


# ──────────────────────────────────────────────────────────
# 连接测试
# ──────────────────────────────────────────────────────────

_INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "legal-knowledge-base", "version": "1.0.0"},
    },
}


def _parse_envelope(raw: str) -> Optional[Dict[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    candidates = []
    if raw.startswith("event:") or raw.startswith("data:"):
        candidates = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
    else:
        candidates = [raw]
    for value in reversed(candidates):
        if not value:
            continue
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


async def _stream_handshake(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 15.0) -> int:
    """发送 MCP initialize 握手并解析响应，成功返回响应延迟毫秒数。"""
    started = time.monotonic()
    combined_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if headers:
        combined_headers.update(headers)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(url, json=_INITIALIZE_PAYLOAD, headers=combined_headers)
        latency = int((time.monotonic() - started) * 1000)
    except httpx.TimeoutException as exc:
        raise MCPConfigError("连接超时，请检查地址或网络") from exc
    except httpx.HTTPStatusError as exc:
        raise MCPConfigError(f"连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise MCPConfigError("无法连接服务，请检查网络或地址") from exc
    if response.status_code >= 400:
        raise MCPConfigError(f"连接失败（HTTP {response.status_code}）")
    envelope = _parse_envelope(response.text)
    if envelope is None:
        raise MCPConfigError("服务未返回有效的 MCP 握手响应")
    return latency


async def _http_api_test(url: str, timeout: float = 15.0) -> int:
    """国家法律法规数据库：请求首页，确认站点可达。"""
    started = time.monotonic()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url.rstrip("/") + "/", headers=headers)
        latency = int((time.monotonic() - started) * 1000)
    except httpx.TimeoutException as exc:
        raise MCPConfigError("连接超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        raise MCPConfigError(f"连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise MCPConfigError("无法连接服务，请检查网络或地址") from exc
    if response.status_code >= 400:
        raise MCPConfigError(f"连接失败（HTTP {response.status_code}）")
    return latency


async def _finchina_test(url: str, api_key: str, timeout: float = 15.0) -> int:
    """万得财汇：发起握手并确认接口连通（接受服务端返回的错误信封）。"""
    started = time.monotonic()
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(url, json=_INITIALIZE_PAYLOAD, headers=headers)
        latency = int((time.monotonic() - started) * 1000)
    except httpx.TimeoutException as exc:
        raise MCPConfigError("连接超时，请检查授权或地址") from exc
    except httpx.HTTPStatusError as exc:
        raise MCPConfigError(f"连接失败（HTTP {exc.response.status_code}）") from exc
    except httpx.RequestError as exc:
        raise MCPConfigError("无法连接服务，请检查网络或地址") from exc
    if response.status_code >= 400:
        raise MCPConfigError(f"连接失败（HTTP {response.status_code}）")
    if not (response.text or "").strip():
        raise MCPConfigError("服务未返回有效响应")
    return latency


async def _stdio_handshake(
    command: str, extra_env: Optional[Dict[str, str]] = None, timeout: float = 45.0
) -> int:
    """本地 stdio MCP 服务：以子进程方式发送 initialize 握手并解析响应。

    ``command`` 为完整启动命令行（如 ``npx -y qcc-document-mcp``），
    按 shell 分词后在子进程中执行；授权等环境变量通过 ``extra_env`` 注入。
    """
    import asyncio
    import shlex

    parts = shlex.split(command)
    if not parts:
        raise MCPConfigError("启动命令为空")
    env = dict(os.environ)
    env.update(extra_env or {})
    started = time.monotonic()
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        request = json.dumps(_INITIALIZE_PAYLOAD).encode("utf-8") + b"\n"
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(request)
        await process.stdin.drain()
        lines: List[str] = []
        while True:
            remaining = max(0.5, timeout - (time.monotonic() - started))
            line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            if text.startswith("data:"):
                text = text[5:].strip()
            try:
                envelope = json.loads(text)
            except (TypeError, ValueError):
                continue
            if isinstance(envelope, dict) and envelope.get("id") == _INITIALIZE_PAYLOAD["id"]:
                if envelope.get("error"):
                    message = (envelope.get("error") or {}).get("message") or "初始化握手失败"
                    raise MCPConfigError(str(message))
                latency = int((time.monotonic() - started) * 1000)
                return latency
            if len(lines) > 64:
                break
            lines.append(text)
    except asyncio.TimeoutError as exc:
        raise MCPConfigError("本地进程握手超时，请确认 npx 可下载并启动该服务") from exc
    except MCPConfigError:
        raise
    except FileNotFoundError as exc:
        raise MCPConfigError(f"无法启动命令「{parts[0]}」，请确认已安装对应运行时") from exc
    except OSError as exc:
        raise MCPConfigError(f"本地进程启动失败：{exc}") from exc
    finally:
        if process is not None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
    raise MCPConfigError("本地服务未返回有效的 MCP 握手响应")


async def _run_test(server: Dict[str, Any]) -> Dict[str, Any]:
    url = _current_value(server["url_name"], server["default_url"])
    key_name = server.get("key_name")
    key = _current_value(key_name) if key_name else ""
    if not url:
        raise MCPConfigError("尚未配置服务地址")
    if key_name and not key:
        raise MCPConfigError("尚未配置授权信息，无法发起连接测试")
    address_error = _mail_address_error(server, url)
    if address_error:
        raise MCPConfigError(address_error)
    if server["protocol"] == "streamable_http":
        headers = {"Authorization": key} if key_name else None
        latency = await _stream_handshake(url, headers)
        return {"ok": True, "message": "连接正常", "latency_ms": latency}
    if server["protocol"] == "finchina":
        latency = await _finchina_test(url, key)
        return {"ok": True, "message": "连接正常", "latency_ms": latency}
    if server["protocol"] == "http_api":
        latency = await _http_api_test(url)
        return {"ok": True, "message": "站点可达", "latency_ms": latency}
    if server["protocol"] == "stdio":
        extra_env = {}
        if key_name:
            extra_env[key_name] = _current_value(key_name)
        latency = await _stdio_handshake(url, extra_env)
        return {"ok": True, "message": "本地进程可用", "latency_ms": latency}
    if server["protocol"] == "quark_skill":
        started = time.monotonic()
        await quark_drive_mcp.check_connection()
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": True, "message": "已授权且可用", "latency_ms": latency}
    if server["protocol"] == "imap_mail":
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        adapter_account = server.get("adapter_account") or server["id"]
        result = await loop.run_in_executor(
            None, qq_mail_mcp.check_connection, adapter_account
        )
        latency = int((time.monotonic() - started) * 1000)
        total = int(result.get("total") or 0)
        return {
            "ok": True,
            "message": f"登录成功，收件箱共 {total} 封邮件",
            "latency_ms": latency,
        }
    raise MCPConfigError("暂不支持该服务的连接检测")


async def test_mcp_server(server_id: str) -> Dict[str, Any]:
    server = _definition(server_id)
    try:
        result = await _run_test(server)
    except (MCPConfigError, qq_mail_mcp.QQMailMCPError, OSError) as exc:
        result = {"ok": False, "message": str(exc), "latency_ms": None}
    _TEST_RESULTS[server_id] = result
    return result


# ──────────────────────────────────────────────────────────
# 更新
# ──────────────────────────────────────────────────────────

class MCPServerUpdate(BaseModel):
    url: Optional[str] = None
    api_key: Optional[str] = None
    optional_api_key: Optional[str] = None
    clear_key: bool = False
    clear_optional_key: bool = False


class QuarkFolderSearch(BaseModel):
    keyword: str
    category: Optional[int] = None


class QuarkFolderBrowse(BaseModel):
    fid: str
    name: str = ""


class QuarkFolderScope(BaseModel):
    fid: str
    name: str


class QuarkFolderScopeUpdate(BaseModel):
    folders: List[QuarkFolderScope]


def update_mcp_server(server_id: str, payload: MCPServerUpdate) -> Dict[str, Any]:
    server = _definition(server_id)
    key_name = server.get("key_name")
    optional_key_name = server.get("optional_key_name")
    values: Dict[str, str] = {}
    for other in _MCP_SERVERS:
        values[other["url_name"]] = _current_value(other["url_name"], other["default_url"])
        if other["key_name"]:
            values[other["key_name"]] = _current_value(other["key_name"])
        if other.get("optional_key_name"):
            values[other["optional_key_name"]] = _current_value(other["optional_key_name"])
    if payload.url is not None:
        url = payload.url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="服务地址不能为空")
        address_error = _mail_address_error(server, url)
        if address_error:
            raise HTTPException(status_code=400, detail=address_error)
        if _is_managed(server["url_name"]):
            raise HTTPException(
                status_code=409, detail="该服务地址由系统环境变量托管，无法在页面中修改"
            )
        values[server["url_name"]] = url
    if payload.clear_key:
        if not key_name:
            raise HTTPException(status_code=400, detail="该服务不需要授权密钥")
        if _is_managed(key_name):
            raise HTTPException(status_code=409, detail="该授权由系统环境变量托管，无法在页面中清除")
        values[key_name] = ""
    elif payload.api_key is not None and payload.api_key.strip():
        if not key_name:
            raise HTTPException(status_code=400, detail="该服务不需要授权密钥")
        if _is_managed(key_name):
            raise HTTPException(status_code=409, detail="该授权由系统环境变量托管，无法在页面中修改")
        values[key_name] = payload.api_key.strip()
    if payload.clear_optional_key:
        if not optional_key_name:
            raise HTTPException(status_code=400, detail="该服务没有可选会话配置")
        if _is_managed(optional_key_name):
            raise HTTPException(status_code=409, detail="该会话由系统环境变量托管，无法在页面中清除")
        values[optional_key_name] = ""
    elif payload.optional_api_key is not None and payload.optional_api_key.strip():
        if not optional_key_name:
            raise HTTPException(status_code=400, detail="该服务没有可选会话配置")
        if _is_managed(optional_key_name):
            raise HTTPException(status_code=409, detail="该会话由系统环境变量托管，无法在页面中修改")
        optional_value = payload.optional_api_key.strip()
        if "\r" in optional_value or "\n" in optional_value:
            raise HTTPException(status_code=400, detail="网页会话 Cookie 不能包含换行")
        if len(optional_value) > 32768:
            raise HTTPException(status_code=400, detail="网页会话 Cookie 过长，请重新复制完整 Cookie")
        values[optional_key_name] = optional_value
    _write_local_settings(values)
    _reload_runtime()
    _TEST_RESULTS.pop(server_id, None)
    return {"success": True, "server": _server_payload(_definition(server_id))}


# ──────────────────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────────────────

def register_mcp_manager_routes(app, require_remote_management_enabled) -> None:
    router = APIRouter()

    @router.get("/api/mcp-servers")
    async def list_mcp_servers():
        payloads = [_server_payload(server) for server in _MCP_SERVERS]
        configured_count = sum(1 for item in payloads if item["usable"])
        pending_auth_count = sum(
            1 for item in payloads if item["needs_key"] and not item["has_key"]
        )
        return {
            "servers": payloads,
            "configured_count": configured_count,
            "total_count": len(payloads),
            "pending_auth_count": pending_auth_count,
            "security_note": (
                "MCP 授权信息仅保存在本机私有配置中，页面不会返回完整密钥。"
                "连接检测会向对应服务发送一次极短的握手请求。"
            ),
        }

    @router.put("/api/mcp-servers/{server_id}")
    async def update_mcp_server_endpoint(server_id: str, payload: MCPServerUpdate, request: Request):
        require_remote_management_enabled(request)
        try:
            return update_mcp_server(server_id, payload)
        except KeyError:
            raise HTTPException(status_code=404, detail="未找到该 MCP 服务")

    @router.post("/api/mcp-servers/{server_id}/test")
    async def test_mcp_server_endpoint(server_id: str, request: Request):
        require_remote_management_enabled(request)
        try:
            _definition(server_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="未找到该 MCP 服务")
        result = await test_mcp_server(server_id)
        if not result["ok"]:
            raise HTTPException(status_code=502, detail=result["message"])
        return result

    @router.post("/api/mcp-servers/{server_id}/cloud-session-test")
    async def test_cloud_session_endpoint(server_id: str, request: Request):
        require_remote_management_enabled(request)
        if server_id != "netease_exmail":
            raise HTTPException(status_code=404, detail="该服务不支持云附件会话检测")
        try:
            result = qq_mail_mcp.check_netease_cloud_session()
        except qq_mail_mcp.QQMailMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result

    @router.get("/api/quark-drive/folder-scopes")
    async def get_quark_folder_scopes():
        return {"folders": quark_drive_mcp.configured_scopes()}

    @router.post("/api/quark-drive/folders/search")
    async def search_quark_folders(payload: QuarkFolderSearch, request: Request):
        require_remote_management_enabled(request)
        try:
            folders = await quark_drive_mcp.search_items(payload.keyword, payload.category)
        except quark_drive_mcp.QuarkDriveMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"folders": folders}

    @router.post("/api/quark-drive/folders/browse")
    async def browse_quark_folder(payload: QuarkFolderBrowse, request: Request):
        require_remote_management_enabled(request)
        try:
            return await quark_drive_mcp.browse_folder(payload.fid, payload.name)
        except quark_drive_mcp.QuarkDriveMCPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.put("/api/quark-drive/folder-scopes")
    async def update_quark_folder_scopes(payload: QuarkFolderScopeUpdate, request: Request):
        require_remote_management_enabled(request)
        folders: List[Dict[str, str]] = []
        seen = set()
        for item in payload.folders[:100]:
            fid = item.fid.strip()
            name = item.name.strip()[:200]
            if not fid or not name or fid in seen:
                continue
            # 夸克 OAuth 文件夹 FID 可能以“~”开头；其余字符仍限定为
            # 官方当前使用的 URL 安全集，避免接受任意外部标识。
            if len(fid) > 200 or not all(char.isalnum() or char in "-~_" for char in fid):
                raise HTTPException(status_code=400, detail="文件夹信息无效，请重新搜索并选择")
            seen.add(fid)
            folders.append({"fid": fid, "name": name})
        _write_local_settings({
            quark_drive_mcp.FOLDER_SCOPES_ENV: json.dumps(folders, ensure_ascii=False)
        })
        _reload_runtime()
        return {"success": True, "folders": quark_drive_mcp.configured_scopes()}

    app.include_router(router)
