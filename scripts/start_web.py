#!/usr/bin/env python
"""Production entrypoint: FastAPI on an internal port, Django on $PORT.

Render (and similar hosts) expose a single public port. The chat UI stays on
that port; Django continues to proxy to FastAPI on 127.0.0.1 so secrets never
reach the browser.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
pythonpath = str(ROOT)
existing = os.environ.get("PYTHONPATH", "")
if pythonpath not in existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = (
        pythonpath if not existing else pythonpath + os.pathsep + existing
    )

PUBLIC_PORT = os.environ.get("PORT", "8000")
API_PORT = os.environ.get("FASTAPI_PORT", "8001")
os.environ.setdefault("FASTAPI_BASE_URL", f"http://127.0.0.1:{API_PORT}")

_children: list[subprocess.Popen[bytes]] = []


def _stop_children() -> None:
    for proc in _children:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 10
    for proc in _children:
        remaining = max(0.1, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()


def _handle_signal(signum: int, _frame: object) -> None:
    _stop_children()
    raise SystemExit(128 + signum if signum else 1)


def _wait_for_api(url: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last_error = "not started"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return
        except URLError as exc:
            last_error = str(exc.reason if getattr(exc, "reason", None) else exc)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.5)
    raise SystemExit(f"FastAPI did not become ready at {url}: {last_error}")


def main() -> int:
    if os.environ.get("RUN_INGEST_ON_START", "").strip().lower() in {"1", "true", "yes"}:
        ingest = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ingest_persona.py")],
            cwd=ROOT,
            check=False,
        )
        if ingest.returncode != 0:
            return ingest.returncode

    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "persona_runtime.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(API_PORT),
        "--workers",
        "1",
        "--timeout-keep-alive",
        "75",
        "--log-level",
        "info",
    ]
    api = subprocess.Popen(api_cmd, cwd=ROOT)
    _children.append(api)
    atexit.register(_stop_children)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if api.poll() is not None:
        return api.returncode or 1

    _wait_for_api(f"http://127.0.0.1:{API_PORT}/health")

    django_cmd = [
        sys.executable,
        "-m",
        "gunicorn",
        "web.wsgi:application",
        "--bind",
        f"0.0.0.0:{PUBLIC_PORT}",
        "--workers",
        "1",
        "--threads",
        "4",
        "--timeout",
        "120",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
    ]
    try:
        return subprocess.call(django_cmd, cwd=ROOT)
    finally:
        _stop_children()


if __name__ == "__main__":
    raise SystemExit(main())
