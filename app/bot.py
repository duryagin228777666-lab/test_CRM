import html
import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BusinessConnection,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from . import leads
from .config import lead_card_url, settings

log = logging.getLogger("crm.bot")
router = Router()

# код кнопки -> (подпись, тег в CRM)
SERVICES = {
    "target": ("Таргетированная реклама", "таргет"),
    "context": ("Контекстная реклама (Директ)", "контекст"),
    "seo": ("SEO-продвижение", "seo"),
    "smm": ("SMM, ведение соцсетей", "smm"),
    "site": ("Сайт или лендинг", "сайт"),
    "other": ("Пока не знаю, нужна консультация", "консультация"),
}

PHONE_RE = re.compile(r"\d")
USERNAME_RE = re.compile(r"^@?[A-Za-z][A-Za-z0-9_]{4,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Form(StatesGroup):
    service = State()
    name = State()
    contact = State()
    request = State()
    confirm = State()


def _services_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"svc:{code}")]
        for code, (label, _) in SERVICES.items()
    ])


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отправить заявку", callback_data="form:send"),
        InlineKeyboardButton(text="Заполнить заново", callback_data="form:restart"),
    ]])


def _contact_kb(username: str | None) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Поделиться номером", request_contact=True)]]
    if username:
        rows.append([KeyboardButton(text=f"Пишите мне в Telegram: @{username}")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def _looks_like_contact(text: str) -> bool:
    digits = len(PHONE_RE.findall(text))
    return digits >= 10 or bool(USERNAME_RE.match(text)) or bool(EMAIL_RE.match(text))


def _lead_summary(lead_id: int, header: str) -> str:
    lead = leads.get_lead(lead_id)
    esc = html.escape
    text = (
        f"<b>{esc(header)}</b>\n"
        f"Имя: {esc(lead['name'] or '—')}\n"
        f"Контакт: {esc(lead['contact'] or '—')}\n"
        f"Запрос: {esc(lead['request'] or '—')}\n"
        f"Теги: {esc(', '.join(lead['tags']))}"
    )
    link = lead_card_url(lead_id)
    if link:
        text += f"\n{link}"
    return text


async def _notify_managers(bot: Bot, text: str) -> None:
    for chat_id in settings.manager_chat_ids:
        try:
            await bot.send_message(
                chat_id, text, link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception:
            log.exception("failed to notify manager %s", chat_id)


_active_bot: Bot | None = None


async def notify_new_lead(lead_id: int, header: str) -> None:
    """Для источников вне бота (юзербот): уведомление уходит, только если бот запущен."""
    if _active_bot is not None:
        await _notify_managers(_active_bot, _lead_summary(lead_id, header))


# --- Пункт 1: анкета в боте -------------------------------------------------

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.service)
    await message.answer(
        "Здравствуйте! Мы рекламное агентство: приводим клиентов бизнесу через рекламу, "
        "SEO и соцсети.\n\nОставьте заявку за минуту, менеджер свяжется с вами. "
        "Что вас интересует?",
        reply_markup=_services_kb(),
    )


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"chat id: <code>{message.chat.id}</code>")


@router.callback_query(Form.service, F.data.startswith("svc:"))
async def pick_service(callback: CallbackQuery, state: FSMContext):
    code = callback.data.removeprefix("svc:")
    if code not in SERVICES:
        await callback.answer()
        return
    await state.update_data(service=code)
    await state.set_state(Form.name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Вы выбрали: {SERVICES[code][0]}.")
    first_name = callback.from_user.first_name
    await callback.message.answer(
        "Как к вам обращаться?",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=first_name)]],
            resize_keyboard=True, one_time_keyboard=True,
        ) if first_name else ReplyKeyboardRemove(),
    )
    await callback.answer()


@router.message(Form.service)
async def service_hint(message: Message):
    await message.answer("Выберите вариант кнопкой выше или нажмите /start.")


@router.message(Form.name, F.text)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()[:100]
    if len(name) < 2:
        await message.answer("Напишите, пожалуйста, имя.")
        return
    await state.update_data(name=name)
    await state.set_state(Form.contact)
    await message.answer(
        "Как с вами связаться? Нажмите кнопку или напишите телефон, @username или email.",
        reply_markup=_contact_kb(message.from_user.username),
    )


@router.message(Form.contact, F.contact)
async def get_contact_shared(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await _save_contact(message, state, phone if phone.startswith("+") else f"+{phone}")


@router.message(Form.contact, F.text)
async def get_contact_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("Пишите мне в Telegram:") and message.from_user.username:
        text = f"@{message.from_user.username}"
    if not _looks_like_contact(text):
        await message.answer("Не похоже на контакт. Нужен телефон, @username или email.")
        return
    await _save_contact(message, state, text[:100])


async def _save_contact(message: Message, state: FSMContext, contact: str):
    await state.update_data(contact=contact)
    await state.set_state(Form.request)
    await message.answer(
        "Коротко опишите задачу: что за бизнес, чего хотите добиться, "
        "есть ли бюджет и сроки.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Form.request, F.text)
async def get_request(message: Message, state: FSMContext):
    text = message.text.strip()[:2000]
    if len(text) < 3:
        await message.answer("Напишите хотя бы пару слов о задаче.")
        return
    await state.update_data(request=text)
    await state.set_state(Form.confirm)
    data = await state.get_data()
    esc = html.escape
    await message.answer(
        "<b>Проверьте заявку</b>\n"
        f"Услуга: {esc(SERVICES[data['service']][0])}\n"
        f"Имя: {esc(data['name'])}\n"
        f"Контакт: {esc(data['contact'])}\n"
        f"Задача: {esc(data['request'])}",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(Form.confirm, F.data == "form:restart")
async def restart(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await start(callback.message, state)


@router.callback_query(Form.confirm, F.data == "form:send")
async def send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    user = callback.from_user
    lead_id = leads.create_lead(
        name=data["name"], contact=data["contact"], request=data["request"],
        source="bot", tags=[SERVICES[data["service"]][1]],
        tg_user_id=user.id, tg_username=user.username, tg_chat_id=callback.message.chat.id,
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Заявка №{lead_id} принята. Менеджер свяжется с вами в рабочее время.\n"
        "Если хотите что-то добавить, просто напишите сюда, мы передадим."
    )
    await callback.answer("Отправлено")
    await _notify_managers(bot, _lead_summary(lead_id, "Новый лид из бота"))


@router.message(StateFilter(Form.name, Form.contact, Form.request))
async def need_text(message: Message):
    await message.answer("Ответьте, пожалуйста, текстом.")


@router.message(StateFilter(None), F.chat.type == "private", F.text)
async def after_form(message: Message, bot: Bot):
    lead = leads.latest_lead_for_tg_user("bot", message.from_user.id)
    if lead is None or message.text.startswith("/"):
        await message.answer("Чтобы оставить заявку, нажмите /start.")
        return
    leads.add_message(lead["id"], "in", message.text[:4000])
    await message.answer("Передали менеджеру, спасибо!")
    extra = (
        f"<b>Дополнение к заявке №{lead['id']}</b>\n{html.escape(message.text[:1000])}"
    )
    link = lead_card_url(lead["id"])
    if link:
        extra += f"\n{link}"
    await _notify_managers(bot, extra)


# --- Пункт 2, вариант с Premium: личный Telegram через Telegram Business ---
# Вариант без Premium (юзербот на Telethon) лежит в personal_tg.py.

_connection_owner: dict[str, int] = {}


@router.business_connection()
async def on_business_connection(connection: BusinessConnection, bot: Bot):
    _connection_owner[connection.id] = connection.user.id
    state = "подключён" if connection.is_enabled else "отключён"
    log.info("business connection %s %s by %s", connection.id, state, connection.user.id)
    try:
        await bot.send_message(
            connection.user_chat_id,
            f"Личный Telegram {state}. Входящие от новых собеседников будут падать в CRM как лиды "
            "с тегом «личный tg»." if connection.is_enabled else f"Личный Telegram {state}.",
        )
    except Exception:
        log.exception("failed to confirm business connection")


async def _owner_id(bot: Bot, connection_id: str) -> int:
    if connection_id not in _connection_owner:
        connection = await bot.get_business_connection(connection_id)
        _connection_owner[connection_id] = connection.user.id
    return _connection_owner[connection_id]


@router.business_message()
async def on_business_message(message: Message, bot: Bot):
    text = message.text or message.caption
    if not text or message.from_user is None:
        return
    owner_id = await _owner_id(bot, message.business_connection_id)
    sender = message.from_user
    lead_id, created = leads.record_personal_message(
        chat_id=message.chat.id, text=text, outgoing=sender.id == owner_id,
        sender_id=sender.id, sender_name=sender.full_name, sender_username=sender.username,
    )
    if created:
        await _notify_managers(bot, _lead_summary(lead_id, "Новый лид из личного Telegram"))


def build_bot() -> tuple[Bot, Dispatcher]:
    global _active_bot
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    _active_bot = bot
    return bot, dp
