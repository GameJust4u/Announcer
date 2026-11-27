# -*- coding: utf-8 -*-
import os, json, time, math, hmac, hashlib, threading, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq
from urllib.parse import urlparse

# ---------- Настройки из переменных окружения ----------
WEBHOOK_1 = os.environ.get("DISCORD_WEBHOOK_1", "")
WEBHOOK_2 = os.environ.get("DISCORD_WEBHOOK_2", "")
PAGE_PASSWORD = os.environ.get("PAGE_PASSWORD", "")
BOT_NAME = os.environ.get("BOT_NAME", "BL9D BOT")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or uuid.uuid4().hex
PORT = int(os.environ.get("PORT", "8080"))

COOLDOWN = 15  # секунд паузы между отправками одного и того же

# Тексты кнопок живут здесь — менять их нужно только тут
BUTTON_TEXTS = {
    "excavations": "@everyone ⛏️ Раскопки",
    "ambush":      "@everyone  Засада",
    "siege":       "@everyone  Осада",
    "pandora_a":   "@everyone  Пандора А",
    "pandora_b":   "@everyone  Пандора Б",
}
# Какой вебхук использует каждая кнопка: 1 или 2
BUTTON_WEBHOOKS = {
    "excavations": 1,
    "ambush": 2,
    "siege": 2,
    "pandora_a": 2,
    "pandora_b": 2,
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- Антиспам: последняя отправка по каждому «слоту» ----------
last_sent = {}          # key -> epoch отправки
pending = {}            # key -> {'text', 'webhook', 'send_at', 'when_str'}
pending_lock = threading.Lock()
revoked = set()         # отозванные после «Выйти» токены

def webhook_url(num):
    return WEBHOOK_1 if num == 1 else WEBHOOK_2

def send_to_discord(text, num):
    url = webhook_url(num)
    if not url:
        raise RuntimeError("вебхук %d не задан на сервере" % num)
    payload = json.dumps({"content": text, "username": BOT_NAME}).encode("utf-8")
    req = urlreq.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlreq.urlopen(req, timeout=10) as resp:
        resp.read()

# ---------- Кука-сессия ----------
SESSION_TTL = 365 * 24 * 3600  # год

def make_token():
    exp = int(time.time()) + SESSION_TTL
    sig = hmac.new(SESSION_SECRET.encode(), ("auth:%d" % exp).encode(), hashlib.sha256).hexdigest()
    return "%d:%s" % (exp, sig)

def check_token(token):
    if token in revoked:
        return False
    try:
        exp_s, sig = token.split(":", 1)
        exp = int(exp_s)
    except Exception:
        return False
    good = hmac.new(SESSION_SECRET.encode(), ("auth:%d" % exp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp > time.time()

def get_cookie(handler, name):
    raw = handler.headers.get("Cookie", "")
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k == name:
                return v
    return None

def is_authorized(handler):
    if not PAGE_PASSWORD:
        return True
    tok = get_cookie(handler, "session")
    return bool(tok and check_token(tok))

# ---------- Планировщик ----------
def scheduler_loop():
    while True:
        now = time.time()
        due = []
        with pending_lock:
            for key in list(pending):
                if pending[key]["send_at"] <= now:
                    due.append((key, pending.pop(key)))
        for key, item in due:
            try:
                send_to_discord(item["text"], item["webhook"])
            except Exception as e:
                print("scheduled send failed:", e)
            last_sent[key] = time.time()  # антиспам действует и после таймера
        time.sleep(1)

threading.Thread(target=scheduler_loop, daemon=True).start()

# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self._json(404, {"error": "не найдено"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/send.html"):
            self._file(os.path.join(BASE_DIR, "send.html"), "text/html; charset=utf-8")
        elif path == "/manifest.webmanifest":
            self._file(os.path.join(BASE_DIR, "manifest.webmanifest"),
                       "application/manifest+json; charset=utf-8")
        elif path == "/icon-192.png":
            self._file(os.path.join(BASE_DIR, "icon-192.png"), "image/png")
        elif path == "/icon-512.png":
            self._file(os.path.join(BASE_DIR, "icon-512.png"), "image/png")
        elif path == "/api/auth":
            self._json(200, {"authed": is_authorized(self), "guest_mode": bool(PAGE_PASSWORD)})
        elif path == "/api/state":
            return self.api_state()
        else:
            self._json(404, {"error": "не найдено"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            return self.api_login()
        if path == "/api/logout":
            return self.api_logout()
        if path == "/api/send":
            return self.api_send()
        if path == "/api/cancel":
            return self.api_cancel()
        self._json(404, {"error": "не найдено"})

    def api_login(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "плохой запрос"})
        if not PAGE_PASSWORD:
            return self._json(200, {"ok": True})
        if data.get("password") != PAGE_PASSWORD:
            return self._json(401, {"error": "неверный пароль"})
        tok = make_token()
        self.send_response(200)
        self.send_header("Set-Cookie", "session=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (tok, SESSION_TTL))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def api_logout(self):
        tok = get_cookie(self, "session")
        if tok:
            revoked.add(tok)
            if len(revoked) > 1000:
                revoked.clear()
        self.send_response(200)
        self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def api_state(self):
        authed = is_authorized(self)
        now = time.time()
        plist = []
        cooldowns = {}
        with pending_lock:
            for key, item in pending.items():
                plist.append({
                    "key": key,
                    "text": item["text"],
                    "when_str": item["when_str"],
                    "send_at": int(item["send_at"]),
                    "channel": item["webhook"],
                })
        plist.sort(key=lambda x: x["send_at"])
        for key, ts in list(last_sent.items()):
            wait = COOLDOWN - (now - ts)
            if wait > 0:
                cooldowns[key] = int(math.ceil(wait))
        self._json(200, {
            "authed": authed,
            "guest_mode": bool(PAGE_PASSWORD),
            "pending": plist,
            "cooldowns": cooldowns,
        })

    def api_cancel(self):
        if not is_authorized(self):
            return self._json(401, {"error": "нужен вход"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "плохой запрос"})
        key = data.get("key", "")
        with pending_lock:
            if key in pending:
                pending.pop(key)
                return self._json(200, {"ok": True})
        return self._json(404, {"error": "такой отправки уже нет"})

    def api_send(self):
        authed = is_authorized(self)
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "плохой запрос"})

        button = data.get("button", "")
        text = ""
        webhook_num = None
        key = None

        if button == "custom":
            if not authed:
                return self._json(401, {"error": "нужен вход"})
            text = (data.get("text") or "").strip()
            if not text:
                return self._json(400, {"error": "пустое сообщение"})
            if len(text) > 1800:
                return self._json(400, {"error": "слишком длинное сообщение"})
            webhook_num = 1 if data.get("channel") == 1 else 2
            key = "custom:" + text
        elif button in BUTTON_TEXTS:
            # Гостям доступна только «Раскопки»
            if not authed and button != "excavations":
                return self._json(401, {"error": "нужен вход"})
            text = BUTTON_TEXTS[button]
            webhook_num = BUTTON_WEBHOOKS[button]
            key = button
        else:
            return self._json(400, {"error": "неизвестная кнопка"})

        now = time.time()

        # Отложенная отправка — доступна для любой кнопки
        sched_raw = (data.get("scheduled") or "").strip()
        send_at = None
        when_str = ""
        if sched_raw:
            if sched_raw.endswith("Z"):
                sched_raw = sched_raw[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(sched_raw)
                if dt.tzinfo is None:
                    return self._json(400, {"error": "время без пояса"})
                send_at = dt.timestamp()
                when_str = dt.strftime("%d.%m %H:%M")
            except ValueError:
                return self._json(400, {"error": "неправильная дата"})
            if send_at <= now + 5:
                return self._json(400, {"error": "время уже прошло"})

        # Проверка дубля таймера
        if send_at is not None:
            with pending_lock:
                if key in pending:
                    return self._json(409, {"error": "такое сообщение уже запланировано на " + pending[key]["when_str"]})
                pending[key] = {"text": text, "webhook": webhook_num, "send_at": send_at,
                                "when_str": when_str, "button": button}
            if not webhook_url(webhook_num):
                with pending_lock:
                    pending.pop(key, None)
                return self._json(500, {"error": "вебхук не настроен на сервере"})
            return self._json(200, {"ok": True, "scheduled": when_str})

        # Антиспам
        last = last_sent.get(key, 0)
        wait = COOLDOWN - (now - last)
        if wait > 0:
            return self._json(429, {"error": "слишком часто", "wait": int(wait) + 1})

        if not webhook_url(webhook_num):
            return self._json(500, {"error": "вебхук не настроен на сервере"})
        try:
            send_to_discord(text, webhook_num)
        except Exception as e:
            return self._json(502, {"error": "не удалось отправить: %s" % e})
        last_sent[key] = time.time()
        return self._json(200, {"ok": True, "wait": COOLDOWN})

if __name__ == "__main__":
    print("Listening on port", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
