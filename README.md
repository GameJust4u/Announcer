# BL9D LOLKA ANNOUNCER

Страничка с кнопками, которые отправляют объявления о ивентах в Discord через вебхук.

## Состав

- `send.html` — страничка (вебхука в ней нет, можно пушить спокойно)
- `server.py` — сервер-посредник, хранит вебхук и проверяет пароль
- `Procfile` — команда запуска для Railway
- `requirements.txt` — зависимостей нет, файл нужен Railway

## Переменные окружения

| Переменная | Что это | Пример |
|---|---|---|
| `DISCORD_WEBHOOK` | URL вебхука Discord (Настройки канала → Интеграции → Вебхуки) | `https://discord.com/api/webhooks/...` |
| `PAGE_PASSWORD` | Пароль для странички (если пусто — проверка отключена) | `lolka123` |
| `BOT_NAME` | Имя, от которого приходят сообщения | `BL9D BOT` |

## Локальный запуск

```bash
set DISCORD_WEBHOOK=твой_вебхук      # Windows (cmd)
export DISCORD_WEBHOOK=твой_вебхук   # Linux/macOS
python server.py
```

Открыть: http://localhost:8080

## Деплой на Railway

1. Залей репозиторий на GitHub.
2. Railway → New Project → Deploy from GitHub repo → выбери репозиторий.
3. Вкладка Variables: добавь `DISCORD_WEBHOOK`, `PAGE_PASSWORD`, `BOT_NAME`.
4. Вкладка Networking → Generate Domain — получишь публичную ссылку.

Важно: не публикуй пароль и вебхук, ссылку на страничку давай только своим.
