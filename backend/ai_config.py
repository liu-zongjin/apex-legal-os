"""AI provider configuration.

Runtime order:
1. Environment variables, suitable for deployment and packaging.
2. backend/local_ai_secrets.py, a private local file ignored by git.
3. Empty string, so callers can return a clear configuration error.

AI 增强偏好（默认服务商/默认模型/隐藏模型）保存在 local_ai_prefs.json，
由“AI API 管理”页面读写。
"""

from __future__ import annotations

import os
import json
import tempfile
import importlib.util
from pathlib import Path


def _load_local_secrets():
    secrets_path = Path(__file__).resolve().parent.parent / "local_ai_secrets.py"
    if not secrets_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("legal_kb_local_ai_secrets", str(secrets_path))
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_local_ai_secrets = _load_local_secrets()


def _secret(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    if _local_ai_secrets is not None:
        return getattr(_local_ai_secrets, name, default)
    return default


DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = _secret("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")

SILICONFLOW_API_KEY = _secret("SILICONFLOW_API_KEY")
SILICONFLOW_API_URL = _secret("SILICONFLOW_API_URL", "https://api.siliconflow.cn/v1/chat/completions")

SCNET_API_KEY = _secret("SCNET_API_KEY")
SCNET_API_URL = _secret("SCNET_API_URL", "https://api.scnet.cn/api/llm/v1/chat/completions")

ARK_API_KEY = _secret("ARK_API_KEY")
ARK_API_URL = _secret("ARK_API_URL", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")

OPENCODE_API_KEY = _secret("OPENCODE_API_KEY")
OPENCODE_API_URL = _secret("OPENCODE_API_URL", "https://opencode.ai/zen/go/v1/chat/completions")
# OpenCode Go now requires clients outside OpenCode itself to identify the client
# and send a stable session marker.  The local app identifier is intentionally
# non-secret and can be overridden by deployments that provide their own value.
OPENCODE_USER_AGENT = _secret("OPENCODE_USER_AGENT", "APEX-Legal-Knowledge-Base/1.0")
OPENCODE_SESSION_ID = _secret("OPENCODE_SESSION_ID", "apex-legal-kb")


def opencode_request_headers(api_key: str) -> dict[str, str]:
    """Return the headers required by the OpenCode Go gateway."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": OPENCODE_USER_AGENT,
        "x-opencode-session": OPENCODE_SESSION_ID,
    }

FINCHINA_API_KEY = _secret("FINCHINA_API_KEY")
FINCHINA_MCP_URL = os.environ.get(
    "FINCHINA_MCP_URL",
    "https://mcp.finchina.com/finchina-data-mcp-server/mcp",
)

# 法随·案例库远端 MCP。官方推荐的 Streamable HTTP 地址，无需 API Key。
ALURIS_MCP_URL = os.environ.get("ALURIS_MCP_URL", "https://aluris.top/mcp")
YUANDIAN_API_KEY = _secret("YUANDIAN_API_KEY").strip()
YUANDIAN_CASES_ENABLED = os.environ.get("YUANDIAN_CASES_ENABLED", "").strip().lower() in {
    "1", "true", "yes", "on"
}
YUANDIAN_CASE_SEARCH_URL = os.environ.get(
    "YUANDIAN_CASE_SEARCH_URL", "https://open.chineselaw.com/open/case_vector_search"
).strip()

# 北大法宝 MCP：授权值只从环境变量或本机私有密钥文件读取，绝不返回前端。
PKULAW_MCP_AUTHORIZATION = _secret("PKULAW_MCP_AUTHORIZATION").strip()

# 企查查 MCP：10 个 Streamable HTTP Server 共享同一 Authorization（含 Bearer 前缀）；
# qcc-document-mcp 本地 stdio 服务使用独立的环境变量。
QCC_MCP_AUTHORIZATION = _secret("QCC_MCP_AUTHORIZATION").strip()
QCC_DOCUMENT_AUTHORIZATION = _secret("QCC_DOCUMENT_AUTHORIZATION").strip()

# QQ 邮箱 MCP：IMAP 直连，授权码在 QQ 邮箱网页版开启 IMAP/SMTP 服务后生成。
QQ_MAIL_ADDRESS = _secret("QQ_MAIL_ADDRESS").strip()
QQ_MAIL_AUTH_CODE = _secret("QQ_MAIL_AUTH_CODE").strip()

# 腾讯企业邮箱 MCP：IMAP 直连，客户端专用密码在网页版「邮箱绑定」中生成。
EXMAIL_ADDRESS = _secret("EXMAIL_ADDRESS").strip()
# 企业微信邮箱可能同时存在自定义域地址和企业内部登录地址。保留
# EXMAIL_ADDRESS 作为发件人地址，使用 EXMAIL_LOGIN 进行 IMAP/SMTP 认证。
EXMAIL_LOGIN = _secret("EXMAIL_LOGIN").strip()
EXMAIL_AUTH_CODE = _secret("EXMAIL_AUTH_CODE").strip()

# 网易企业邮箱 MCP：IMAP 直连，客户端授权码在网页版「客户端设置」中生成。
NETEASE_EXMAIL_ADDRESS = _secret("NETEASE_EXMAIL_ADDRESS").strip()
NETEASE_EXMAIL_AUTH_CODE = _secret("NETEASE_EXMAIL_AUTH_CODE").strip()
# 网易官方网页端会话 Cookie（可选）：用于把大附件上传为真正的网易云附件。
# SMTP/IMAP 客户端授权码不能代替网页会话；未配置时由发信模块自动按页分卷兜底。
NETEASE_EXMAIL_WEB_COOKIE = _secret("NETEASE_EXMAIL_WEB_COOKIE").strip()


DEFAULT_AI_MODEL = "opencode:deepseek-flash"

# DeepSeek V4 Flash 已由 V4.1 Flash 取代。保留旧标识的读取迁移，确保既有
# 本地偏好和浏览器保存的模型选择会自动切换到新模型，而不会继续发起旧调用。
MODEL_ID_MIGRATIONS = {
    "deepseek-v4-flash": "deepseek-flash",
    "opencode:deepseek-v4-flash": "opencode:deepseek-flash",
}


def canonical_model_id(model: str) -> str:
    """返回当前可调用的模型标识，并迁移已废弃的本地保存值。"""
    return MODEL_ID_MIGRATIONS.get(str(model or ""), str(model or ""))

# ─────────────────────────────────────────────
# AI 增强模型目录（AI API 管理页与 AI 增强选择器共用）
# id 与 main.py 中 AI_PROVIDER_DEFINITIONS 的服务商一一对应
# ─────────────────────────────────────────────
ASK_MODEL_CATALOG = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "caption": "深度求索",
        "group": "DeepSeek V4",
        "models": [
            ("deepseek-flash", "DeepSeek V4.1 Flash"),
            ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("deepseek-chat", "DeepSeek V3（标准）"),
            ("deepseek-reasoner", "DeepSeek R1（深度推理）"),
        ],
    },
    {
        "id": "scnet",
        "name": "SCNet",
        "caption": "算网融合",
        "group": "超算互联网",
        "models": [
            ("scnet:MiniMax-M2.5", "超算·MiniMax M2.5"),
            ("scnet:DeepSeek-V3.1", "超算·DeepSeek V3.1"),
            ("scnet:DeepSeek-R1", "超算·DeepSeek R1"),
            ("scnet:Qwen3-Coder", "超算·Qwen3 Coder"),
            ("scnet:Qwen3-235B-A22B", "超算·Qwen3 235B"),
        ],
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "caption": "硅基流动",
        "group": "硅基流动",
        "models": [
            ("deepseek-ai/DeepSeek-V3", "硅基·DeepSeek V3"),
            ("deepseek-ai/DeepSeek-V3.2", "硅基·DeepSeek V3.2"),
            ("deepseek-ai/DeepSeek-R1", "硅基·DeepSeek R1"),
            ("Qwen/Qwen2.5-72B-Instruct", "通义千问 2.5（72B）"),
            ("Qwen/Qwen2.5-32B-Instruct", "通义千问 2.5（32B）"),
            ("Qwen/Qwen2.5-14B-Instruct", "通义千问 2.5（14B）"),
            ("Qwen/Qwen2.5-7B-Instruct", "通义千问 2.5（7B 快速）"),
            ("THUDM/glm-4-9b-chat", "智谱 GLM-4（9B）"),
            ("meta-llama/Meta-Llama-3.1-8B-Instruct", "Llama 3.1（8B）"),
            ("Pro/MiniMaxAI/MiniMax-M2.5", "MiniMax M2.5"),
        ],
    },
    {
        "id": "ark",
        "name": "Volcengine Ark",
        "caption": "火山方舟",
        "group": "豆包（火山引擎）",
        "models": [
            ("doubao:Doubao-Seed-2.0-pro", "豆包·Seed 2.0 Pro（深度推理）"),
            ("doubao:Doubao-Seed-2.0-lite", "豆包·Seed 2.0 Lite（均衡）"),
            ("doubao:Doubao-Seed-2.0-mini", "豆包·Seed 2.0 Mini（快速）"),
        ],
    },
    {
        "id": "workbuddy",
        "name": "WorkBuddy",
        "caption": "语义增强",
        "group": "AI 增强",
        "models": [
            ("workbuddy", "WorkBuddy 增强（语义深度检索）"),
        ],
    },
    {
        "id": "opencode",
        "name": "OpenCode Go",
        "caption": "通用网关",
        "group": "OpenCode Go",
        "models": [
            # OpenCode Go 网关模型目录以 /v1/models 实际返回为准。
            # 网关要求裸模型名（不带 opencode: 前缀），ai_client 会统一剥离前缀。
            ("opencode:deepseek-v4-pro", "OpenCode Go·DeepSeek V4 Pro"),
            ("opencode:deepseek-flash", "OpenCode Go·DeepSeek V4.1 Flash"),
            ("opencode:kimi-k3", "OpenCode Go·Kimi K3"),
            ("opencode:kimi-k2.7-code", "OpenCode Go·Kimi K2.7 Code"),
            ("opencode:kimi-k2.6", "OpenCode Go·Kimi K2.6"),
            ("opencode:kimi-k2.5", "OpenCode Go·Kimi K2.5"),
            ("opencode:glm-5.2", "OpenCode Go·GLM 5.2"),
            ("opencode:glm-5.1", "OpenCode Go·GLM 5.1"),
            ("opencode:glm-5", "OpenCode Go·GLM 5"),
            ("opencode:qwen3.8-max", "OpenCode Go·Qwen3.8 Max"),
            ("opencode:qwen3.7-max", "OpenCode Go·Qwen3.7 Max"),
            ("opencode:qwen3.7-plus", "OpenCode Go·Qwen3.7 Plus"),
            ("opencode:qwen3.6-plus", "OpenCode Go·Qwen3.6 Plus"),
            ("opencode:qwen3.5-plus", "OpenCode Go·Qwen3.5 Plus"),
            ("opencode:minimax-m3", "OpenCode Go·MiniMax M3"),
            ("opencode:minimax-m2.7", "OpenCode Go·MiniMax M2.7"),
            ("opencode:minimax-m2.5", "OpenCode Go·MiniMax M2.5"),
            ("opencode:mimo-v2.5-pro", "OpenCode Go·MiMo V2.5 Pro"),
            ("opencode:mimo-v2.5", "OpenCode Go·MiMo V2.5"),
            ("opencode:mimo-v2-pro", "OpenCode Go·MiMo V2 Pro（暂不可用）"),
            ("opencode:mimo-v2-omni", "OpenCode Go·MiMo V2 Omni（暂不可用）"),
            ("opencode:hy3", "OpenCode Go·Hy3"),
            ("opencode:hy3-preview", "OpenCode Go·Hy3 Preview（暂不可用）"),
            ("opencode:gpt-5.6-luna", "OpenCode Go·GPT-5.6 Luna（暂不可用）"),
            ("opencode:grok-4.5", "OpenCode Go·Grok 4.5（暂不可用）"),
        ],
    },
]

# 历史版本中未在 AI 增强选择器中展示的模型，默认隐藏（保持既有体验）。
# 官方 DeepSeek 模型默认隐藏：默认走 OpenCode Go 网关，避免静默消耗官方账户额度。
DEFAULT_HIDDEN_AI_MODELS = [
    "deepseek-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-14B-Instruct",
    "scnet:DeepSeek-V3.1",
    "scnet:DeepSeek-R1",
    "scnet:Qwen3-Coder",
    "scnet:Qwen3-235B-A22B",
]

# OpenCode Go 网关对部分模型有固定参数要求：temperature 只能传 1.0，
# 传其他值会返回 400。这里的 key 是去掉 opencode: 前缀后的裸模型名。
OPENCODE_FIXED_TEMPERATURE_MODELS = {"kimi-k3", "kimi-k2.7-code"}


def effective_temperature(model: str, temperature: float) -> float:
    """返回实际应提交给模型的 temperature（适配网关的固定参数限制）。"""
    if model in OPENCODE_FIXED_TEMPERATURE_MODELS:
        return 1.0
    return temperature

AI_PREFS_PATH = Path(__file__).resolve().parent.parent / "local_ai_prefs.json"

_AI_PREFS_DEFAULTS = {
    "default_provider": "deepseek",
    "default_model": DEFAULT_AI_MODEL,
    "hidden_models": list(DEFAULT_HIDDEN_AI_MODELS),
    "purpose_models": {},
}

# 各业务功能默认使用的 AI 模型。AI API 管理页可分别修改并保存，
# 保存后对应功能（利息参数识别、文章摘要、法答网核心结论、
# 研究项目备忘录、法律晨报、降级备用模型）即改用该网关+模型。
# 默认统一走 OpenCode Go 网关，避免静默消耗官方 DeepSeek 账户额度。
AI_PURPOSE_DEFAULTS = {
    "interest_parameters": "opencode:deepseek-flash",       # 利息计算参数文字识别
    "summary": "opencode:deepseek-flash",               # 文章摘要生成
    "fada_conclusion": "opencode:deepseek-flash",       # 法答网核心结论提炼
    "research_memo": "opencode:deepseek-flash",         # 研究项目备忘录自动生成
    "radar_digest": "opencode:deepseek-flash",          # 法律晨报 AI 摘要
    "automated_filing": "opencode:deepseek-flash",      # 自动化立案材料识别
    "fallback": "opencode:deepseek-flash",              # 降级备用模型（OpenCode Go）
}

AI_PURPOSE_LABELS = {
    "interest_parameters": "利息计算参数识别",
    "summary": "文章摘要",
    "fada_conclusion": "法答网核心结论",
    "research_memo": "研究项目备忘录",
    "radar_digest": "法律晨报",
    "automated_filing": "自动化立案识别",
    "fallback": "降级备用模型",
}


def load_ai_prefs() -> dict:
    if not AI_PREFS_PATH.exists():
        return dict(_AI_PREFS_DEFAULTS)
    try:
        with AI_PREFS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return dict(_AI_PREFS_DEFAULTS)
    merged = dict(_AI_PREFS_DEFAULTS)
    if isinstance(data, dict):
        if isinstance(data.get("default_provider"), str):
            merged["default_provider"] = data["default_provider"]
        if isinstance(data.get("default_model"), str):
            merged["default_model"] = canonical_model_id(data["default_model"])
        if isinstance(data.get("hidden_models"), list):
            merged["hidden_models"] = [canonical_model_id(item) for item in data["hidden_models"]]
        if isinstance(data.get("purpose_models"), dict):
            merged["purpose_models"] = {
                str(key): canonical_model_id(value) for key, value in data["purpose_models"].items()
            }
    return merged


def save_ai_prefs(prefs: dict) -> None:
    data = dict(_AI_PREFS_DEFAULTS)
    data.update({key: prefs[key] for key in ("default_provider", "default_model", "hidden_models") if key in prefs})
    data["default_model"] = canonical_model_id(data["default_model"])
    data["hidden_models"] = [canonical_model_id(item) for item in data["hidden_models"]]
    if isinstance(prefs.get("purpose_models"), dict):
        data["purpose_models"] = {
            str(key): canonical_model_id(value) for key, value in prefs["purpose_models"].items()
        }
    AI_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".local_ai_prefs.", suffix=".tmp", dir=str(AI_PREFS_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, AI_PREFS_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def effective_default_model() -> str:
    model = canonical_model_id(load_ai_prefs().get("default_model") or DEFAULT_AI_MODEL)
    return model if model in ALLOWED_MODELS else DEFAULT_AI_MODEL


def effective_purpose_model(purpose: str) -> str:
    """返回指定功能当前生效的模型；未单独设置时回退到该功能的默认模型。"""
    prefs = load_ai_prefs()
    selected = canonical_model_id((prefs.get("purpose_models") or {}).get(purpose, ""))
    if selected in ALLOWED_MODELS:
        return selected
    fallback = AI_PURPOSE_DEFAULTS.get(purpose, "")
    if fallback in ALLOWED_MODELS:
        return fallback
    return effective_default_model()


def ask_models(provider_id: str):
    for provider in ASK_MODEL_CATALOG:
        if provider["id"] == provider_id:
            return list(provider["models"])
    return []


def ask_model_label(model: str) -> str:
    model = canonical_model_id(model)
    for provider in ASK_MODEL_CATALOG:
        for candidate, label in provider["models"]:
            if candidate == model:
                return label
    return model

ALLOWED_MODELS = {
    "deepseek-v4-pro",
    "deepseek-flash",
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-V3.2",
    "deepseek-ai/DeepSeek-R1",
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen2.5-14B-Instruct",
    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "THUDM/glm-4-9b-chat",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "Pro/MiniMaxAI/MiniMax-M2.5",
    "scnet:DeepSeek-V3.1",
    "scnet:DeepSeek-R1",
    "scnet:Qwen3-Coder",
    "scnet:Qwen3-235B-A22B",
    "scnet:MiniMax-M2.5",
    "doubao:Doubao-Seed-2.0-pro",
    "doubao:Doubao-Seed-2.0-lite",
    "doubao:Doubao-Seed-2.0-mini",
    "workbuddy",
    "opencode:deepseek-v4-pro",
    "opencode:deepseek-flash",
    "opencode:kimi-k3",
    "opencode:kimi-k2.7-code",
    "opencode:kimi-k2.6",
    "opencode:kimi-k2.5",
    "opencode:glm-5.2",
    "opencode:glm-5.1",
    "opencode:glm-5",
    "opencode:qwen3.8-max",
    "opencode:qwen3.7-max",
    "opencode:qwen3.7-plus",
    "opencode:qwen3.6-plus",
    "opencode:qwen3.5-plus",
    "opencode:minimax-m3",
    "opencode:minimax-m2.7",
    "opencode:minimax-m2.5",
    "opencode:mimo-v2.5-pro",
    "opencode:mimo-v2.5",
    "opencode:mimo-v2-pro",
    "opencode:mimo-v2-omni",
    "opencode:hy3",
    "opencode:hy3-preview",
    "opencode:gpt-5.6-luna",
    "opencode:grok-4.5",
}
