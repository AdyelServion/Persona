#!/usr/bin/env python
"""Run FastAPI persona API with uvicorn."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn

from persona_runtime.config import get_settings


def main() -> None:
    settings = get_settings()
    host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or settings.fastapi_port)
    uvicorn.run(
        "persona_runtime.api.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
