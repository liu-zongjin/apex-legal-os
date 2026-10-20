"""One business implementation, explicit platform capability differences."""
from __future__ import annotations

import sys

WINDOWS_DISABLED = frozenset({"icloud_contacts", "icloud_calendar", "biometric", "finder_tags",
                              "recording", "quark", "feishu", "messages_sync"})


def enabled(name: str) -> bool:
    return not (sys.platform == "win32" and name in WINDOWS_DISABLED)


def snapshot():
    return {"platform": "windows" if sys.platform == "win32" else sys.platform,
            "disabled": sorted(WINDOWS_DISABLED) if sys.platform == "win32" else [],
            "judicial_message_input": "manual" if sys.platform == "win32" else "messages"}


def register_routes(app):
    @app.get("/api/platform-capabilities")
    def platform_capabilities():
        return snapshot()

    from starlette.responses import JSONResponse
    @app.middleware('http')
    async def enforce_platform_capabilities(request, call_next):
        if sys.platform == 'win32':
            path = request.url.path
            excluded = ('/api/recording', '/recording', '/api/quark', '/api/feishu',
                        '/api/case-manager/calendar/', '/api/case-manager/contacts/sync')
            if path.startswith(excluded) or '/biometric' in path:
                return JSONResponse({'detail': 'Windows 版不提供此功能'}, status_code=501)
        return await call_next(request)
