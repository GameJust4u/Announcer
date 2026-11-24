import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Все секреты — только через переменные окружения, в коде их нет.
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "")
BOT_NAME = os.environ.get("BOT_NAME", "BL9D BOT")
PAGE_PASSWORD = os.environ.get("PAGE_PASSWORD", "")  # пусто = проверка отключена
PORT = int(os.environ.get("PORT", "8080"))

with open("send.html", encoding="utf-8") as f:
    PAGE = f.read()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, PAGE)

    def do_POST(self):
        if self.path != "/send":
            self._send(404, '{"error": "not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(data["text"]).strip()
            password = str(data.get("password", ""))
        except Exception:
            self._send(400, '{"error": "bad request"}', "application/json")
            return

        if PAGE_PASSWORD and password != PAGE_PASSWORD:
            self._send(401, '{"error": "wrong password"}', "application/json")
            return
        if not WEBHOOK_URL:
            self._send(500, '{"error": "webhook not configured"}', "application/json")
            return
        if not text:
            self._send(400, '{"error": "empty"}', "application/json")
            return

        payload = json.dumps({"content": text[:2000], "username": BOT_NAME}).encode("utf-8")
        try:
            req = Request(
                WEBHOOK_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urlopen(req, timeout=10)
        except HTTPError as e:
            print("Discord error:", e.code, e.read().decode(errors="ignore"))
            self._send(502, '{"error": "webhook failed"}', "application/json")
            return
        except URLError as e:
            print("Network error:", e)
            self._send(502, '{"error": "network failed"}', "application/json")
            return

        self._send(200, '{"ok": true}', "application/json")


if __name__ == "__main__":
    print(f"Запущено на порту {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
