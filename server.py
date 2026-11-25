import hashlib
import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ============ Конфигурация из переменных окружения ============
# Railway -> Variables. Ничего секретного в коде нет.
WEBHOOKS = {
    "1": os.environ.get("DISCORD_WEBHOOK_1", ""),  # канал для «Раскопок»
    "2": os.environ.get("DISCORD_WEBHOOK_2", ""),  # канал для остальных
}
BOT_NAME = os.environ.get("BOT_NAME", "BL9D BOT")
PAGE_PASSWORD = os.environ.get("PAGE_PASSWORD", "")  # пусто = авторизация выключена
SESSION_SECRET = os.environ.get("SESSION_SECRET") or os.urandom(32).hex()
SESSION_TTL = 365 * 24 * 3600  # кука на год
PORT = int(os.environ.get("PORT", 8080))

# Какая кнопка на какой вебхук летит. Перевесить кнопку = поменять цифру.
BUTTON_WEBHOOKS = {
    "raskopki": "1",
    "zasada": "2",
    "osada": "2",
    "pandora_a": "2",
    "pandora_b": "2",
}

# Тексты кнопок живёт на сервере — страничка просто называет кнопку.
BUTTON_TEXTS = {
    "raskopki": "@everyone⛏РАСКОПКИ!",
    "zasada":   "@everyone ЗАСАДА!",
    "osada":    "@everyone 🏰 ОСАДА!",
    "pandora_a": "🅰️ ПАНДОРА А",
    "pandora_b": "🅱️ ПАНДОРА Б",
}

# ============ Статика ============
with open("send.html", encoding="utf-8") as f:
    PAGE = f.read()
with open("manifest.webmanifest", encoding="utf-8") as f:
    MANIFEST = f.read()
ICONS = {}
for name in ("icon-192.png", "icon-512.png"):
    with open(name, "rb") as f:
        ICONS[name] = f.read()

# ============ Сессии ============
def make_token():
    ts = str(int(time.time()))
    sig = hmac.new(SESSION_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"

def check_token(token):
    try:
        ts, sig = token.split(".", 1)
    except ValueError:
        return False
    good = hmac.new(SESSION_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        if time.time() - int(ts) > SESSION_TTL:
            return False
    except ValueError:
        return False
    return True

# ============ Discord ============
def send_to_discord(webhook_url, text):
    if not webhook_url:
        raise RuntimeError("webhook не задан")
    payload = json.dumps({"content": text[:2000], "username": BOT_NAME}).encode("utf-8")
    req = Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
    urlopen(req, timeout=10)

# ============ Отложенные сообщения ============
# Живут в памяти: при перезапуске Railway расписание сбрасывается.
def parse_schedule(value):
    # клиент присылает ISO с Z (UTC)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

def schedule_message(delay, webhook_url, text):
    def job():
        try:
            send_to_discord(webhook_url, text)
            print(f"[ok] отложенное отправлено: {text[:40]}")
        except Exception as e:
            print(f"[fail] отложенное не ушло: {e}")
    threading.Timer(delay, job).start()

# ============ HTTP ============
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="text/html; charset=utf-8", extra_headers=None):
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj, extra_headers=None):
        self._send(code, json.dumps(obj), "application/json", extra_headers)

    def _authorized(self):
        # пароль не задан — авторизация выключена
        if not PAGE_PASSWORD:
            return True
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("bl9d_session="):
                return check_token(part.split("=", 1)[1])
        return False

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE)
        elif self.path == "/manifest.webmanifest":
            self._send(200, MANIFEST, "application/manifest+json")
        elif self.path == "/icon-192.png":
            self._send(200, ICONS["icon-192.png"], "image/png")
        elif self.path == "/icon-512.png":
            self._send(200, ICONS["icon-512.png"], "image/png")
        elif self.path == "/auth-status":
            self._json(200, {"authed": self._authorized()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "bad request"})
            return

        if self.path == "/login":
            if not PAGE_PASSWORD:
                self._json(200, {"ok": True})
                return
            if data.get("password") == PAGE_PASSWORD:
                token = make_token()
                cookie = (
                    f"bl9d_session={token}; Max-Age={SESSION_TTL}; Path=/; "
                    "HttpOnly; Secure; SameSite=Lax"
                )
                self._json(200, {"ok": True}, {"Set-Cookie": cookie})
            else:
                self._json(401, {"error": "wrong password"})
            return

        if self.path == "/send":
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return

            text = str(data.get("text", "")).strip()[:2000]
            button_id = data.get("button")

            # для кнопок текст определяет сервер
            if button_id and button_id in BUTTON_TEXTS:
                text = BUTTON_TEXTS[button_id]
            if not text:
                self._json(400, {"error": "empty"})
                return

            # канал: по кнопке или из явного выбора (для своих сообщений)
            if button_id and button_id in BUTTON_WEBHOOKS:
                channel = BUTTON_WEBHOOKS[button_id]
            else:
                channel = data.get("channel") if data.get("channel") in WEBHOOKS else "2"
            webhook_url = WEBHOOKS[channel]

            # расписание
            schedule = data.get("schedule")
            if schedule:
                try:
                    ts = parse_schedule(schedule)
                    delay = ts - time.time()
                    if delay < -5:
                        self._json(400, {"error": "time in the past"})
                        return
                    if delay > 0:
                        schedule_message(delay, webhook_url, text)
                    else:
                        send_to_discord(webhook_url, text)
                    self._json(200, {"ok": True, "scheduled": True})
                except (ValueError, TypeError):
                    self._json(400, {"error": "bad schedule"})
                except (HTTPError, URLError, RuntimeError) as e:
                    print("Discord error:", e)
                    self._json(502, {"error": "webhook failed"})
                return

            # обычная отправка
            try:
                send_to_discord(webhook_url, text)
            except HTTPError as e:
                print("Discord error:", e.code, e.read().decode(errors="ignore"))
                self._json(502, {"error": "webhook failed"})
                return
            except (URLError, RuntimeError) as e:
                print("Network error:", e)
                self._json(502, {"error": "webhook failed"})
                return
            self._json(200, {"ok": True})
            return

        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args)


if __name__ == "__main__":
    print(f"BL9D LOLKA ANNOUNCER запущен на порту {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
