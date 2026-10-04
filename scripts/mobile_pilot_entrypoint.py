"""Container entry point for the disposable, anonymous Stella mobile pilot."""

from __future__ import annotations

import os

import uvicorn

from backend.anonymous_pilot import prepare_anonymous_pilot


def main() -> None:
    os.environ.setdefault("APEX_ANONYMOUS_PILOT", "1")
    prepare_anonymous_pilot()
    from backend.main import app

    uvicorn.run(
        app,
        host=os.environ.get("LEGAL_KB_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
