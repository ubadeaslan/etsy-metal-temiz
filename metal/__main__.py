"""`python -m metal`: start the local panel and open it in the browser (Windows, macOS, Linux)."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORTS = range(8765, 8775)


def is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "posix":  # a port just closed may be taken again; on Windows this flag would share a used one
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def install_on(port: int) -> str | None:
    """The install id of the panel answering on this port (None: nothing, or another program)."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/panel", timeout=2) as resp:
            data = json.loads(resp.read())
        return data.get("install") if data.get("app") == "etsy-metal" else None
    except (OSError, ValueError, AttributeError):
        return None


def pick_port(own_install: str) -> tuple[int | None, bool]:
    """(port, already running). Another copy of the panel on this computer keeps its own port and its own
    designs: this copy takes the next free one."""
    for port in PORTS:
        if is_free(port):
            return port, False
        if install_on(port) == own_install:
            return port, True
    return None, False


def open_when_ready(port: int) -> None:
    for _ in range(120):
        if install_on(port):
            webbrowser.open(f"http://{HOST}:{port}")
            return
        time.sleep(0.5)


def main() -> int:
    if sys.version_info < (3, 11):
        print(f"Python 3.11 ya da daha yenisi gerekiyor (bu: {sys.version.split()[0]}).")
        return 1
    for stream in (sys.stdout, sys.stderr):  # a console that has no "ı" must not stop the panel
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    import uvicorn

    from .web.app import INSTALL_ID, app

    port, running = pick_port(INSTALL_ID)
    if port is None:
        print(f"{PORTS[0]}-{PORTS[-1]} arasında boş port yok; açık kalmış panelleri kapatıp tekrar dene.")
        return 1
    url = f"http://{HOST}:{port}"
    browser = not os.environ.get("METAL_NO_BROWSER")
    if running:
        print(f"Panel zaten açık: {url}")
        if browser:
            webbrowser.open(url)
        return 0
    print(f"Panel: {url}\nKapatmak için bu pencereyi kapat (ya da Ctrl+C).")
    if browser:
        threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
    try:
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:  # Ctrl+C is the normal way out
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
