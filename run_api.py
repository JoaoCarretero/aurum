#!/usr/bin/env python3
"""Run the NEXUS API server."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    import uvicorn

    from api.server import app

    host = (os.environ.get("AURUM_API_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int((os.environ.get("AURUM_API_PORT") or "8000").strip() or "8000")
    docs_enabled = _env_flag("AURUM_API_EXPOSE_DOCS", default=False)

    print("\n  NEXUS - AURUM Finance API")
    print(f"  http://{host}:{port}")
    if docs_enabled:
        print(f"  http://{host}:{port}/docs")
    print("")

    uvicorn.run(app, host=host, port=port)
