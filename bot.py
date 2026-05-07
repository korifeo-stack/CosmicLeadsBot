import asyncio
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiohttp import web
from dotenv import load_dotenv
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, URLInputFile, FSInputFile
from aiogram.client.default import DefaultBotProperties


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class UserSession:
    source: str = "organic"
    waiting_for: Optional[str] = None  # dashboard_request_text | demo_request_text


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@aicosmicnews")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
PDF_PATH = os.getenv("PDF_PATH")
PDF_URL = os.getenv("PDF_URL")

# ── Site → bot HTTP integration ──
SITE_LEAD_HOST  = os.getenv("SITE_LEAD_HOST", "127.0.0.1")
SITE_LEAD_PORT  = int(os.getenv("SITE_LEAD_PORT", "8001"))
SITE_LEAD_TOKEN = os.getenv("SITE_LEAD_TOKEN", "").strip()  # обязательно для прода

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not (ADMIN_CHAT_ID or ADMIN_PASSWORD):
    raise RuntimeError("Set ADMIN_CHAT_ID or ADMIN_PASSWORD")
if not (PDF_PATH or PDF_URL):
    raise RuntimeError("Set PDF_PATH or PDF_URL")

if PDF_PATH and not Path(PDF_PATH).exists():
    raise RuntimeError(f"PDF_PATH does not exist: {PDF_PATH}")


dp = Dispatcher()
sessions: Dict[int, UserSession] = {}
resolved_admin_chat_id: Optional[int] = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None


START_TEXT = (
    "Привет! 👋\n"
    "Я бот CosmicMind: помогаем держать высокий сервис через обратную связь гостей "
    "(голосом) → категории → задачи → дашборд владельца.\n\n"
    "🎁 Выдам PDF «Контроль сервиса за 10 минут в день» "
    "(ритуал смены + 5 метрик + шаблон отчёта).\n\n"
    "Чтобы получить PDF:\n\n"
    "• подпишись на канал\n"
    "• нажми «Проверить подписку»"
)

NOT_SUB_TEXT = (
    "Пока не вижу подписку 🙏\n"
    "Подпишись на канал и нажми «Проверить подписку» ещё раз."
)

SCRIPTS_TEXT = (
    "5 фраз, которые дают честную обратную связь 👇\n\n"
    "• Что было супер — а что можно улучшить?\n\n"
    "• Где было неудобно по времени?\n\n"
    "• Если улучшить одну вещь — что бы это было?\n\n"
    "• В какой момент хотелось внимания/помощи?\n\n"
    "• Оценка 1–10. Что нужно, чтобы стало на 10?"
)


def sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подписаться на канал", url="https://t.me/aicosmicnews")],
            [InlineKeyboardButton(text="🔁 Проверить подписку", callback_data="check_sub")],
        ]
    )


def after_pdf_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Хочу пример дашборда", callback_data="want_dashboard")],
            [InlineKeyboardButton(text="🎙 Скрипты фидбека", callback_data="get_scripts")],
            [InlineKeyboardButton(text="🤝 Хочу демо", callback_data="want_demo")],
        ]
    )


def scripts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Хочу пример дашборда", callback_data="want_dashboard")],
            [InlineKeyboardButton(text="🤝 Хочу демо", callback_data="want_demo")],
        ]
    )


def get_session(user_id: int) -> UserSession:
    if user_id not in sessions:
        sessions[user_id] = UserSession()
    return sessions[user_id]



def is_admin_password_message(message: Message) -> bool:
    return bool(ADMIN_PASSWORD and message.text and message.text.strip() == ADMIN_PASSWORD)


async def try_bind_admin(message: Message, bot: Bot) -> bool:
    global resolved_admin_chat_id
    if not is_admin_password_message(message):
        return False

    resolved_admin_chat_id = message.from_user.id
    await message.answer(
        f"✅ Админ-пароль принят. Теперь уведомления будут отправляться сюда (chat_id={resolved_admin_chat_id})."
    )
    return True


def format_user_display(message: Message) -> str:
    user = message.from_user
    if not user:
        return "unknown"
    first = user.first_name or ""
    last = user.last_name or ""
    username = f"(@{user.username})" if user.username else ""
    return f"{first} {last} {username}".strip()


async def notify_admin(bot: Bot, message: Message, event_name: str, source: str, payload: str) -> None:
    user = message.from_user
    if not user:
        return

    admin_text = (
        f"🟢 CosmicLead event: {event_name}\n"
        f"👤 user: {format_user_display(message)}\n"
        f"🆔 id: {user.id}\n"
        f"🔗 link: tg://user?id={user.id}\n"
        f"🧩 source: {source or 'organic'}\n"
        f"🕒 time: {datetime.now(timezone.utc).isoformat()}\n"
        f"📝 payload: {payload}"
    )
    if resolved_admin_chat_id is None:
        logger.warning("Admin chat is not configured yet; skip event %s", event_name)
        return
    await bot.send_message(chat_id=resolved_admin_chat_id, text=admin_text)


async def notify_error(bot: Bot, message: Message, error_text: str) -> None:
    try:
        await notify_admin(bot, message, "error", get_session(message.from_user.id).source, error_text[:800])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unable to send error to admin: %s", exc)


# ──────────────────────────────────────────────────────────────
# Site → bot integration: HTTP endpoint POST /api/site-lead
# ──────────────────────────────────────────────────────────────
def format_site_lead(payload: dict) -> str:
    """HTML message for admin chat (used with parse_mode=HTML)."""
    def f(v: object) -> str:
        return html_escape(str(v if v not in (None, "") else "—"))

    lines = [
        "🛎  <b>Заявка с лендинга · CosmicMind</b>",
        "",
        f"<b>Имя:</b>      {f(payload.get('name'))}",
        f"<b>Телефон:</b>  {f(payload.get('phone'))}",
        f"<b>Сеть:</b>     {f(payload.get('company'))}",
        f"<b>Размер:</b>   {f(payload.get('size'))} точек",
    ]
    src = payload.get("source")
    if src:    lines.append(f"<b>CTA:</b>      {f(src)}")
    page = payload.get("page")
    if page:   lines.append(f"<b>Страница:</b> {f(page)}")
    ts = payload.get("ts") or datetime.now(timezone.utc).isoformat()
    lines.append(f"<b>Время:</b>    {f(ts)}")
    utm = payload.get("utm")
    if utm:    lines.append(f"<b>UTM:</b>      {f(utm)}")
    return "\n".join(lines)


async def site_lead_handler(request: web.Request) -> web.Response:
    """Принимает заявки с лендинга (server.js → этот endpoint).

    Авторизация — header `X-Site-Token` должен совпадать с SITE_LEAD_TOKEN.
    """
    bot: Bot = request.app["bot"]

    # Auth
    if SITE_LEAD_TOKEN:
        sent = request.headers.get("X-Site-Token", "")
        if not hmac.compare_digest(sent, SITE_LEAD_TOKEN):
            logger.warning("site-lead unauthorized: client=%s", request.remote)
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    # Body
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    name  = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if not name or not phone:
        return web.json_response({"ok": False, "error": "name and phone are required"}, status=400)

    if resolved_admin_chat_id is None:
        logger.warning("site-lead got data but ADMIN_CHAT_ID not set yet; payload=%s", payload)
        return web.json_response({"ok": False, "error": "admin chat not configured"}, status=503)

    text = format_site_lead(payload)
    try:
        await bot.send_message(chat_id=resolved_admin_chat_id, text=text)
        logger.info("site-lead delivered: name=%s phone=%s source=%s", name, phone, payload.get("source"))
    except Exception as exc:
        logger.exception("site-lead delivery failed: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=502)

    return web.json_response({"ok": True})


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({
        "ok": True,
        "admin_configured": resolved_admin_chat_id is not None,
        "site_token_set": bool(SITE_LEAD_TOKEN),
    })


async def send_pdf(bot: Bot, chat_id: int) -> None:
    if PDF_URL:
        await bot.send_document(chat_id=chat_id, document=URLInputFile(PDF_URL))
        return

    await bot.send_document(chat_id=chat_id, document=FSInputFile(PDF_PATH))


@dp.message(CommandStart())
async def on_start(message: Message, bot: Bot) -> None:
    param = "organic"
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            param = parts[1].strip()

    session = get_session(message.from_user.id)
    session.source = param
    session.waiting_for = None

    if await try_bind_admin(message, bot):
        return

    await message.answer(START_TEXT, reply_markup=sub_keyboard())
    await notify_admin(bot, message, "start", session.source, "command=/start")


@dp.callback_query(F.data == "check_sub")
async def on_check_subscription(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.message:
        return

    message = callback.message
    user = callback.from_user
    session = get_session(user.id)

    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user.id)
        is_subscribed = member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }
    except Exception as exc:  # noqa: BLE001
        is_subscribed = False
        await notify_error(bot, message, f"check_sub failed: {exc}")

    if not is_subscribed:
        await callback.message.answer(NOT_SUB_TEXT, reply_markup=sub_keyboard())
        await notify_admin(bot, message, "not_subscribed_check", session.source, "button=check_sub")
        await callback.answer()
        return

    await callback.message.answer("Готово ✅ Спасибо!\nВот PDF «Контроль сервиса за 10 минут в день» 📎")
    await send_pdf(bot=bot, chat_id=user.id)
    await callback.message.answer("Что дальше?", reply_markup=after_pdf_keyboard())
    await notify_admin(bot, message, "subscribed_and_delivered", session.source, "button=check_sub")
    await callback.answer()


@dp.callback_query(F.data == "get_scripts")
async def on_get_scripts(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.message:
        return
    session = get_session(callback.from_user.id)
    session.waiting_for = None
    await callback.message.answer(SCRIPTS_TEXT, reply_markup=scripts_keyboard())
    await notify_admin(bot, callback.message, "clicked_scripts", session.source, "button=get_scripts")
    await callback.answer()


@dp.callback_query(F.data == "want_dashboard")
async def on_want_dashboard(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.message:
        return
    session = get_session(callback.from_user.id)
    session.waiting_for = "dashboard_request_text"

    await callback.message.answer(
        "Ок ✅ Напиши одним сообщением:\n\n"
        "• город и формат (кофейня/casual/fine и т.д.)\n"
        "• сколько точек"
    )
    await notify_admin(bot, callback.message, "clicked_dashboard", session.source, "button=want_dashboard")
    await callback.answer()


@dp.callback_query(F.data == "want_demo")
async def on_want_demo(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.message:
        return
    session = get_session(callback.from_user.id)
    session.waiting_for = "demo_request_text"

    await callback.message.answer(
        "Ок ✅ Напиши одним сообщением:\n"
        "• телефон или @username для связи\n"
        "• название ресторана/сети\n"
        "• сколько точек"
    )
    await notify_admin(bot, callback.message, "clicked_demo", session.source, "button=want_demo")
    await callback.answer()


@dp.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    if await try_bind_admin(message, bot):
        return

    session = get_session(message.from_user.id)
    if session.waiting_for == "dashboard_request_text":
        await notify_admin(bot, message, "dashboard_request_text", session.source, message.text)
        session.waiting_for = None
        await message.answer("Спасибо! ✅ Передал, пришлю пример в ответ.")
    elif session.waiting_for == "demo_request_text":
        await notify_admin(bot, message, "demo_request_text", session.source, message.text)
        session.waiting_for = None
        await message.answer("Спасибо! ✅ Передал запрос, свяжемся.")


# ──────────────────────────────────────────────────────────────
# Run polling + aiohttp web server side-by-side.
# ──────────────────────────────────────────────────────────────
async def start_web_server(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/api/site-lead", site_lead_handler)
    app.router.add_get("/api/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, SITE_LEAD_HOST, SITE_LEAD_PORT)
    await site.start()
    logger.info("Site-lead HTTP listener on %s:%s (token_required=%s)",
                SITE_LEAD_HOST, SITE_LEAD_PORT, bool(SITE_LEAD_TOKEN))
    return runner


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    runner = await start_web_server(bot)
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
