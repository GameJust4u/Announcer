import hashlib
import hmac
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Все секреты приходят из переменных окружения — в коде их нет.
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "")
BOT_NAME = os.environ.get("BOT_NAME", "BL9D BOT")
PAGE_PASSWORD = os.environ.get("PAGE_PASSWORD", "")

# Секрет для подписи авторизационной куки.
# Если не задан — генерируется при каждом запуске (тогда после перезапуска
# придётся один раз ввести пароль заново). На Railway лучше задать явно.
SESSION_SECRET = os.environ.get("SESSION_SECRET", os.urandom(16).hex())

PORT = int(os.environ.get("PORT", 8080))

with open("send.html", encoding="utf-8") as f:
    PAGE = f.read()


def auth_token() -> str:
    """Токен, который выдаётся в куку после успешного входа."""
    return hmac.new(SESSION_SECRET.encode(), b"bl9d-auth-v1", hashlib.sha256).hexdigest()


def parse_cookie(header: str) -> dict:
    cookies = {}
    for part in header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k] = v
    return cookies


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/html; charset=utf-8", extra_headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj, extra_headers=None):
        self._send(code, json.dumps(obj), "application/json", extra_headers)

    def _authorized(self) -> bool:
        # Если пароль не задан — доступ открыт всем.
        if not PAGE_PASSWORD:
            return True
        token = parse_cookie(self.headers.get("Cookie", "")).get("bl9d_auth", "")
        return hmac.compare_digest(token, auth_token())

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE)
        elif self.path == "/check":
            self._json(200, {"ok": True} if self._authorized() else {"ok": False})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            data = {}

        if self.path == "/login":
            if not PAGE_PASSWORD:
                self._json(200, {"ok": True})
                return
            password = str(data.get("password", ""))
            if password == PAGE_PASSWORD:
                # Кука на год, HttpOnly — JS её не видит.
                cookie = (
                    "bl9d_auth=%s; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"
                    % auth_token()
                )
                self._json(200, {"ok": True}, [("Set-Cookie", cookie)])
            else:
                self._json(401, {"error": "wrong password"})
            return

        if self.path == "/send":
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return

            text = str(data.get("text", "")).strip()[:2000]
            if not text:
                self._json(400, {"error": "empty"})
                return

            payload = json.dumps({"content": text, "username": BOT_NAME}).encode("utf-8")
            try:
                req = Request(
                    WEBHOOK_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urlopen(req, timeout=10)
            except HTTPError as e:
                print("Discord error:", e.code, e.read().decode(errors="ignore"))
                self._json(502, {"error": "webhook failed"})
                return
            except URLError as e:
                print("Network error:", e)
                self._json(502, {"error": "network failed"})
                return

            self._json(200, {"ok": True})
            return

        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    mode = "открытый доступ" if not PAGE_PASSWORD else "с паролем"
    print(f"Запущено на порту {PORT}, режим: {mode}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
