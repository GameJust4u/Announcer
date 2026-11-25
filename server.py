import json
import os
import hmac
import hashlib
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# --- Секретная часть: всё из переменных окружения, в коде секретов нет ---
WEBHOOK_1 = os.environ.get("DISCORD_WEBHOOK_1", "")   # канал для "Раскопки"
WEBHOOK_2 = os.environ.get("DISCORD_WEBHOOK_2", "")   # канал для всего остального
BOT_NAME = os.environ.get("BOT_NAME", "BL9D BOT")
PAGE_PASSWORD = os.environ.get("PAGE_PASSWORD", "")   # пустая = без пароля
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or os.urandom(32).hex()
PORT = int(os.environ.get("PORT", "8080"))

WEBHOOKS = {"1": WEBHOOK_1, "2": WEBHOOK_2}

# Какая кнопка в какой канал
BUTTON_WEBHOOKS = {
    "raskopki": "1",
    "zasada": "2",
    "osada": "2",
    "pandora_a": "2",
    "pandora_b": "2",
}

with open("send.html", encoding="utf-8") as f:
    PAGE = f.read()

scheduled = []          # [{"at": epoch, "text": str, "target": "1"|"2"}]
sched_lock = threading.Lock()


def _sign(value):
    return hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _check_cookie(handler):
    cookie = handler.headers.get("Cookie", "")
    token = ""
    for part in cookie.split(";"):
        if part.strip().startswith("auth="):
            token = part.strip()[5:]
    return _check_token(token)


def _check_token(token):
    if not PAGE_PASSWORD:
        return True
    return hmac.compare_digest(token or "", _sign(PAGE_PASSWORD))


def send_to_webhook(target, text):
    url = WEBHOOKS.get(target)
    if not url:
        raise RuntimeError("Вебхук для канала %s не настроен" % target)
    payload = json.dumps({"content": text, "username": BOT_NAME}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    urlopen(req, timeout=10)


def scheduler_loop():
    while True:
        now = time.time()
        due = []
        with sched_lock:
            still = []
            for item in scheduled:
                if item["at"] <= now:
                    due.append(item)
                else:
                    still.append(item)
            scheduled[:] = still
        for item in due:
            try:
                send_to_webhook(item["target"], item["text"])
                print("Отправлено отложенное:", item["text"][:50])
            except Exception as e:
                print("Ошибка отложенной отправки:", e)
        time.sleep(2)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj, extra_headers=None):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for h, v in (extra_headers or []):
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        data = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "bad request"})
            return

        if self.path == "/login":
            if not PAGE_PASSWORD:
                self._json(200, {"ok": True})
                return
            if hmac.compare_digest(str(body.get("password", "")), PAGE_PASSWORD):
                token = _sign(PAGE_PASSWORD)
                self._json(200, {"ok": True}, extra_headers=[
                    ("Set-Cookie", "auth=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax" % token)
                ])
            else:
                self._json(401, {"error": "wrong password"})
            return

        if self.path != "/send":
            self._json(404, {"error": "not found"})
            return

        if not _check_cookie(self):
            self._json(401, {"error": "unauthorized"})
            return

        text = str(body.get("text", "")).strip()[:2000]
        if not text:
            self._json(400, {"error": "empty"})
            return

        button = body.get("button")
        if button in BUTTON_WEBHOOKS:
            target = BUTTON_WEBHOOKS[button]
        else:
            target = body.get("target") if body.get("target") in WEBHOOKS else "2"

        send_at = body.get("send_at")
        if send_at:
            try:
                at = float(send_at)
            except (TypeError, ValueError):
                self._json(400, {"error": "bad send_at"})
                return
            if at <= time.time():
                self._json(400, {"error": "time in the past"})
                return
            if at > time.time() + 365 * 24 * 3600:
                self._json(400, {"error": "too far ahead"})
                return
            with sched_lock:
                scheduled.append({"at": at, "text": text, "target": target})
            self._json(200, {"ok": True, "scheduled": True})
            return

        try:
            send_to_webhook(target, text)
        except HTTPError as e:
            print("Discord error:", e.code, e.read().decode(errors="ignore"))
            self._json(502, {"error": "webhook failed"})
            return
        except (URLError, RuntimeError) as e:
            print("Ошибка отправки:", e)
            self._json(502, {"error": "send failed"})
            return

        self._json(200, {"ok": True, "scheduled": False})


if __name__ == "__main__":
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Запущено на порту %d" % PORT)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
