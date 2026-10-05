# Мини-CRM заявок рекламного агентства

Лиды собираются в одну CRM из трёх источников:
- Telegram-бот с анкетой;
- личный Telegram менеджера;
- ручная форма.

Лиды размечаются тегами (автоматически по источнику и услуге, плюс вручную) и фильтруются по тегу.

- Документ к сдаче (набросок и разбор): [docs/submission.md](docs/submission.md)
- Набросок продукта: [docs/product-sketch.md](docs/product-sketch.md)
- Журнал решений: [docs/decisions-log.md](docs/decisions-log.md)

Стек: Python 3.12, FastAPI, Jinja2, aiogram 3, Telethon, SQLite. Веб, бот и юзербот работают в одном процессе.

## Локальный запуск

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env   # заполнить BOT_TOKEN и остальное
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Откройте http://localhost:8000 и войдите под логином и паролем из `ADMIN_LOGIN` / `ADMIN_PASSWORD` (по умолчанию `demo` / `demo`).

Тесты: `.\.venv\Scripts\python -m pytest -q tests`

## Настройка Telegram

1. **Бот (пункт 1).** Создайте бота в @BotFather и положите токен в `BOT_TOKEN`. Напишите боту `/id` с аккаунта менеджера и положите число в `MANAGER_CHAT_IDS`: туда будут приходить уведомления о новых лидах.
2. **Личный Telegram (пункт 2), без Premium.**
   - Получите `api_id` и `api_hash` на https://my.telegram.org/apps и положите их в `TG_API_ID` / `TG_API_HASH`.
   - Выполните `.\.venv\Scripts\python -m app.tg_login`, введите телефон, код и пароль 2FA. Положите напечатанную строку в `TG_SESSION`.
   - Перезапустите приложение. Теперь, если аккаунту-менеджеру напишет новый человек не из контактов, в CRM появится лид с тегом `личный tg`.
3. **Личный Telegram с Premium (альтернатива).** В BotFather включите Bot Settings > Business Mode. Затем в Telegram откройте Настройки > Telegram Business > Чат-боты и подключите этого бота. Менять код не нужно.

Polling может работать только в одном экземпляре на токен. Не запускайте локальную копию одновременно с задеплоенной.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен бота; пустой — CRM работает без бота |
| `MANAGER_CHAT_IDS` | chat id для уведомлений, через запятую |
| `PUBLIC_URL` | адрес CRM для ссылок в уведомлениях |
| `ADMIN_LOGIN`, `ADMIN_PASSWORD` | вход в CRM |
| `SECRET_KEY` | подпись cookie сессии |
| `DB_PATH` | путь к SQLite |
| `SEED_DEMO` | `1` — при пустой базе создать демо-лидов с тегом «демо» |
| `TELEGRAM_PROXY` | прокси для Bot API, если Telegram недоступен |
| `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` | юзербот для личного Telegram |
| `TG_SKIP_CONTACTS` | `1` — не делать лидов из переписки с контактами |

## Деплой

**Railway** (сборка из `Dockerfile` по репозиторию на GitHub):

1. New Project > Deploy from GitHub repo, выбрать этот репозиторий.
2. Settings > Volumes > Add Volume с путём `/data`. База лежит в `/data/crm.db` и переживает передеплой.
3. Variables: `BOT_TOKEN`, `MANAGER_CHAT_IDS`, `ADMIN_LOGIN`, `ADMIN_PASSWORD`, `SECRET_KEY`, `PUBLIC_URL` (адрес сервиса на Railway), при необходимости `TG_API_ID`, `TG_API_HASH`, `TG_SESSION`.
4. Settings > Networking > Generate Domain, порт `8080`.

После каждого push в `main` Railway пересобирает приложение сам.

**VPS с Docker:** заполните `.env` и выполните `docker compose up -d --build`. Приложение слушает `127.0.0.1:8080`. Выпустите его наружу через nginx с HTTPS и укажите `PUBLIC_URL`. Если сервер в РФ и `api.telegram.org` с него недоступен, задайте `TELEGRAM_PROXY`.
