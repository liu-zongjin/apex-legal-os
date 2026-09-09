"""Small security defaults for the local knowledge-base server."""

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple


BIOMETRIC_LOGIN_TTL_SECONDS = 120
_BIOMETRIC_LOGIN_BRIDGE_SECRET = os.environ.get(
    "LEGAL_KB_BIOMETRIC_BRIDGE_SECRET", "apex-login-biometric-2026-v1"
)
_biometric_login_challenges: Dict[str, float] = {}
_biometric_login_tickets: Dict[str, float] = {}
_biometric_login_lock = threading.Lock()


def get_bind_host() -> str:
    """Bind to localhost by default; opt into LAN exposure with LEGAL_KB_HOST."""
    return os.environ.get("LEGAL_KB_HOST", "127.0.0.1")


def get_allowed_origins() -> List[str]:
    raw = os.environ.get("LEGAL_KB_CORS_ORIGINS", "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_private_mode() -> bool:
    """Private deployment mode for a Tailscale-only personal server."""
    return _truthy("LEGAL_KB_PRIVATE_MODE")


def is_loopback_client(host: Optional[str]) -> bool:
    """Trust only the socket peer address, never forwarded client headers."""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return host.strip().lower() == "localhost"


def is_local_access_trusted(client_host: Optional[str]) -> bool:
    """Allow local native-shell access only outside the private-server mode.

    A Tailscale Serve reverse proxy reaches the loopback-only backend from
    127.0.0.1, just like the native shell. Private mode must therefore keep
    its login requirement even for loopback connections; otherwise every
    remote Serve request would silently bypass authentication.
    """
    return is_loopback_client(client_host) and not is_private_mode()


def allow_remote_management() -> bool:
    """Whether risky desktop/local management actions are enabled remotely."""
    return _truthy("LEGAL_KB_ALLOW_REMOTE_MANAGEMENT") or not is_private_mode()


def get_basic_auth_credentials() -> Optional[Tuple[str, str]]:
    """Return configured Basic Auth credentials, if password protection is enabled."""
    password = os.environ.get("LEGAL_KB_ACCESS_PASSWORD", "")
    if not password:
        return None
    return os.environ.get("LEGAL_KB_ACCESS_USER", "lawyer"), password


def get_access_user() -> str:
    credentials = get_basic_auth_credentials()
    return credentials[0] if credentials else "lawyer"


def check_basic_auth_header(header: Optional[str]) -> bool:
    credentials = get_basic_auth_credentials()
    if not credentials:
        return True
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    user, password = decoded.split(":", 1)
    expected_user, expected_password = credentials
    return hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_password)


def authenticate_access_credentials(user: str, password: str) -> bool:
    credentials = get_basic_auth_credentials()
    if not credentials:
        return True
    expected_user, expected_password = credentials
    return hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_password)


def get_session_cookie_name() -> str:
    return "legal_kb_session"


def _session_secret() -> str:
    credentials = get_basic_auth_credentials()
    if not credentials:
        return "legal-kb-local"
    user, password = credentials
    return f"{user}:{password}:{os.environ.get('LEGAL_KB_SESSION_SECRET', '')}"


def create_session_token(user: str) -> str:
    ts = str(int(time.time()))
    payload = f"{user}:{ts}"
    sig = hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def check_session_cookie(token: Optional[str], max_age_seconds: int = 30 * 24 * 60 * 60) -> bool:
    credentials = get_basic_auth_credentials()
    if not credentials:
        return True
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        user, ts_text, sig = decoded.rsplit(":", 2)
        ts = int(ts_text)
    except Exception:
        return False
    if int(time.time()) - ts > max_age_seconds:
        return False
    expected_user, _ = credentials
    if not hmac.compare_digest(user, expected_user):
        return False
    payload = f"{user}:{ts_text}"
    expected_sig = hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def create_access_token() -> str:
    """Stable private-network access token for browsers that forget cookies."""
    sig = hmac.new(_session_secret().encode("utf-8"), b"legal-kb-access-link", hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(sig.encode("ascii")).decode("ascii").rstrip("=")


def check_access_token(token: Optional[str]) -> bool:
    if not get_basic_auth_credentials():
        return True
    if not token:
        return False
    return hmac.compare_digest(token, create_access_token())


def is_biometric_login_enabled() -> bool:
    """Whether Touch ID may be used to create an APEX access session."""
    return os.environ.get("LEGAL_KB_BIOMETRIC_LOGIN_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }


def create_biometric_login_challenge() -> str:
    """Create a short-lived proof request for the trusted macOS shell."""
    now = time.time()
    challenge = secrets.token_urlsafe(32)
    with _biometric_login_lock:
        _purge_expired_biometric_login_proofs(now)
        _biometric_login_challenges[challenge] = now + BIOMETRIC_LOGIN_TTL_SECONDS
    return challenge


def complete_biometric_login_challenge(challenge: str, secret: str) -> Optional[str]:
    """Exchange a native-shell Touch ID proof for a one-use browser ticket."""
    if not challenge or not hmac.compare_digest(str(secret or ""), _BIOMETRIC_LOGIN_BRIDGE_SECRET):
        return None
    now = time.time()
    with _biometric_login_lock:
        _purge_expired_biometric_login_proofs(now)
        deadline = _biometric_login_challenges.pop(challenge, None)
        if deadline is None or deadline < now:
            return None
        ticket = secrets.token_urlsafe(32)
        _biometric_login_tickets[ticket] = now + BIOMETRIC_LOGIN_TTL_SECONDS
    return ticket


def consume_biometric_login_ticket(ticket: str) -> bool:
    """Consume a one-use Touch ID login ticket exactly once."""
    if not ticket:
        return False
    now = time.time()
    with _biometric_login_lock:
        _purge_expired_biometric_login_proofs(now)
        deadline = _biometric_login_tickets.pop(ticket, None)
    return deadline is not None and deadline >= now


def _purge_expired_biometric_login_proofs(now: float) -> None:
    for store in (_biometric_login_challenges, _biometric_login_tickets):
        expired = [value for value, deadline in store.items() if deadline < now]
        for value in expired:
            store.pop(value, None)
