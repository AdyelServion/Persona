#!/usr/bin/env python
"""Development-only ngrok tunnel to Django (port 8000). Key never sent to browser."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyngrok import conf, ngrok

from persona_runtime.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.ngrok_key:
        raise SystemExit("NGROK_KEY is required for the optional local tunnel.")
    conf.get_default().auth_token = settings.ngrok_key
    tunnel = ngrok.connect(settings.django_port, "http")
    print(f"ngrok tunnel: {tunnel.public_url} -> http://127.0.0.1:{settings.django_port}")
    print("Press Ctrl+C to stop.")
    try:
        ngrok_process = ngrok.get_ngrok_process()
        ngrok_process.proc.wait()
    except KeyboardInterrupt:
        ngrok.kill()


if __name__ == "__main__":
    main()
