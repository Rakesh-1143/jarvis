"""A small browser chat page for Jarvis (standard library only).

Open http://127.0.0.1:5050 after running:  python -m jarvis --web
The page can also use your browser's built-in speech recognition and voice.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = (Path(__file__).parent / "index.html").read_bytes()


def serve(assistant, host: str = "127.0.0.1", port: int = 5050) -> None:
    pending: list[str] = []
    lock = threading.Lock()

    def notify(msg: str) -> None:  # reminders show up in the page
        with lock:
            pending.append(msg)

    assistant.ctx.notify = notify
    assistant.start_background()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/notifications":
                with lock:
                    items, pending[:] = list(pending), []
                self._send(200, json.dumps({"messages": items}).encode())
            else:
                self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.path != "/api/chat":
                return self._send(404, b'{"error":"not found"}')
            try:
                length = int(self.headers.get("Content-Length", 0))
                text = json.loads(self.rfile.read(length) or b"{}").get("text", "")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, b'{"error":"bad request"}')
            reply = assistant.handle(str(text)[:2000])
            self._send(200, json.dumps({"reply": reply}).encode())

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Jarvis web UI running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        assistant.stop()
