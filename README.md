# BL9D LOLKA ANNOUNCER 💬

Страничка с кнопками, которая отправляет анонсы ивентов в Discord-канал через вебхук.

## Как это устроено

- `send.html` — страничка с кнопками. Секретов не содержит.
- `server.py` — сервер-посредник. Хранит вебхук (из переменных окружения) и
  пересылает сообщения в Discord.
- Пароль вводится один раз на устройство: сервер выдаёт куку на год,
  дальше страничка открывается сразу с кнопками.

## Переменные окружения (Railway → Variables)

| Переменная | Что это | Обязательна |
|---|---|---|
| `DISCORD_WEBHOOK` | URL вебхука Discord | да |
| `PAGE_PASSWORD` | Пароль для доступа к страничке | нет (если пусто — доступ всем) |
| `SESSION_SECRET` | Любая случайная строка для подписи куки | нет, но лучше задать |
| `BOT_NAME` | Имя, от которого приходят сообщения | нет (по умолч. `BL9D BOT`) |

## Локальный запуск

```bash
# Windows (cmd):
set DISCORD_WEBHOOK=твой_вебхук
set PAGE_PASSWORD=мойпароль
python server.py

# Linux/macOS:
DISCORD_WEBHOOK=твой_вебхук PAGE_PASSWORD=мойпароль python server.py
```

Открыть: http://localhost:8080

## Деплой на Railway

1. Залей файлы на GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. Variables: добавь `DISCORD_WEBHOOK`, `PAGE_PASSWORD`, `SESSION_SECRET`, `BOT_NAME`.
4. Networking → Generate Domain — получишь публичную ссылку.
5. Открой ссылку, введи пароль один раз — готово.

⚠️ Если `SESSION_SECRET` не задан, он генерируется при каждом запуске, и после
перезапуска пароль придётся ввести заново. Лучше задать что-то вроде
`df8k2j9fsd7fk23`.
