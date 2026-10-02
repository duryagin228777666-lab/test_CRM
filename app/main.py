import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from . import leads
from .bot import build_bot
from .config import settings
from .db import init_db
from .web import LoginRequired, router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("crm")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_demo:
        leads.seed_demo()

    polling = None
    if settings.bot_token:
        bot, dp = build_bot()
        polling = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False,
                             allowed_updates=dp.resolve_used_update_types())
        )
        log.info("Telegram bot polling started")
    else:
        log.warning("BOT_TOKEN is empty: running web CRM without the bot")

    yield

    if polling:
        await dp.stop_polling()
        await asyncio.wait_for(polling, timeout=10)
        await bot.session.close()


app = FastAPI(title="Мини-CRM агентства", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.public_url.startswith("https://"),
    max_age=60 * 60 * 24 * 14,
)
app.include_router(router)


@app.exception_handler(LoginRequired)
async def _to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)
