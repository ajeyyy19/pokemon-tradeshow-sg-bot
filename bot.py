"""
Telegram bot that notifies a group about Singapore TCG tradeshows.
- Every Monday at 9am SGT: posts tradeshows happening that week (Mon–Sun)
- /thisweek  — shows current week's events
- /upcoming  — shows next 4 weeks of events
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from scraper import run_scraper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

SGT = ZoneInfo("Asia/Singapore")
EVENTS_FILE = Path(__file__).parent / "events.json"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_ID = 7609501467


def admin_only(func):
    """Decorator that silently ignores commands from non-admin users."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            logger.warning("Unauthorised command attempt from user %s", update.effective_user.id)
            return
        return await func(update, context)
    return wrapper


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def load_events() -> list[dict]:
    """Load events from events.json."""
    if not EVENTS_FILE.exists():
        logger.warning("events.json not found — returning empty list")
        return []
    with open(EVENTS_FILE) as f:
        return json.load(f)


def events_in_range(start: date, end: date) -> list[dict]:
    """Return events whose date range overlaps [start, end]."""
    all_events = load_events()
    result = []
    for ev in all_events:
        ev_start = date.fromisoformat(ev["start_date"])
        ev_end = date.fromisoformat(ev["end_date"])
        # Overlaps if ev_start <= end AND ev_end >= start
        if ev_start <= end and ev_end >= start:
            result.append(ev)
    return sorted(result, key=lambda e: e["start_date"])


def week_bounds(ref: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the week containing ref."""
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def format_date_range(start_str: str, end_str: str) -> str:
    """Format '2026-03-28' + '2026-03-29' → 'Sat 28 – Sun 29 Mar 2026'."""
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    day_abbr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if start == end:
        return f"{day_abbr[start.weekday()]} {start.day} {start.strftime('%b %Y')}"
    if start.month == end.month:
        return (
            f"{day_abbr[start.weekday()]} {start.day} – "
            f"{day_abbr[end.weekday()]} {end.day} {start.strftime('%b %Y')}"
        )
    return (
        f"{day_abbr[start.weekday()]} {start.strftime('%-d %b')} – "
        f"{day_abbr[end.weekday()]} {end.strftime('%-d %b %Y')}"
    )


def format_event(ev: dict) -> str:
    """Format a single event as a Telegram HTML block."""
    date_range = format_date_range(ev["start_date"], ev["end_date"])
    lines = [
        f"🃏 <b>{ev['name']}</b>",
        f"📅 {date_range}",
        f"📍 {ev['venue']}",
    ]
    if ev.get("address"):
        lines.append(f"🏠 {ev['address']}")
    if ev.get("hours") and ev["hours"] != "TBC":
        lines.append(f"🕐 {ev['hours']}")
    elif ev.get("hours") == "TBC":
        lines.append("🕐 Hours TBC")
    return "\n".join(lines)


def format_weekly_message(events: list[dict], week_start: date, week_end: date) -> str:
    """Format the full weekly digest message."""
    header_date = f"{week_start.strftime('%-d %b')} – {week_end.strftime('%-d %b %Y')}"
    if not events:
        return (
            f"🗓 <b>TCG Tradeshows This Week</b> ({header_date})\n\n"
            "No tradeshows this week. Stay tuned for upcoming events! 👀"
        )

    parts = [f"🗓 <b>TCG Tradeshows This Week</b> ({header_date})\n"]
    for ev in events:
        parts.append(format_event(ev))
    return "\n\n".join(parts)


def format_upcoming_message(weeks: int = 4) -> str:
    """Format upcoming events across the next N weeks."""
    today = datetime.now(SGT).date()
    start = today
    end = today + timedelta(weeks=weeks)
    events = events_in_range(start, end)

    if not events:
        return (
            f"📅 <b>Upcoming TCG Tradeshows</b> (next {weeks} weeks)\n\n"
            "No upcoming events found. Check back soon!"
        )

    parts = [f"📅 <b>Upcoming TCG Tradeshows</b> (next {weeks} weeks)\n"]
    for ev in events:
        parts.append(format_event(ev))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Scheduled job
# ---------------------------------------------------------------------------

async def send_weekly_update(app: Application) -> None:
    """Send the weekly tradeshow digest to the configured group."""
    today = datetime.now(SGT).date()
    monday, sunday = week_bounds(today)
    events = events_in_range(monday, sunday)
    message = format_weekly_message(events, monday, sunday)

    try:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
        )
        logger.info("Weekly update sent to chat %s (%d events)", CHAT_ID, len(events))
    except Exception as e:
        logger.error("Failed to send weekly update: %s", e)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@admin_only
async def cmd_thisweek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/thisweek — show tradeshows happening this week."""
    today = datetime.now(SGT).date()
    monday, sunday = week_bounds(today)
    events = events_in_range(monday, sunday)
    message = format_weekly_message(events, monday, sunday)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)


@admin_only
async def cmd_upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/upcoming — show tradeshows in the next 4 weeks."""
    message = format_upcoming_message(weeks=4)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)


@admin_only
async def cmd_push(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/push — manually send this week's digest to the group chat."""
    today = datetime.now(SGT).date()
    monday, sunday = week_bounds(today)
    events = events_in_range(monday, sunday)
    message = format_weekly_message(events, monday, sunday)

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        parse_mode=ParseMode.HTML,
    )
    # Confirm to the person who triggered it (if they're not in the group chat)
    if str(update.effective_chat.id) != str(CHAT_ID):
        await update.message.reply_text("✅ Pushed to the group!")


@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — welcome message."""
    text = (
        "👋 <b>SG TCG Tradeshow Bot</b>\n\n"
        "I post weekly updates about trading card tradeshows in Singapore every "
        "<b>Monday at 9am SGT</b>.\n\n"
        "<b>Commands:</b>\n"
        "/thisweek — tradeshows happening this week\n"
        "/upcoming — next 4 weeks of events\n"
        "/push — manually push this week's events to the group\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

def build_app() -> Application:
    """Build and configure the Telegram application."""
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")
    if not CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID is not set in .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("thisweek", cmd_thisweek))
    app.add_handler(CommandHandler("upcoming", cmd_upcoming))
    app.add_handler(CommandHandler("push", cmd_push))
    return app


def setup_scheduler(app: Application) -> AsyncIOScheduler:
    """Set up APScheduler for Monday 9am SGT weekly digest."""
    scheduler = AsyncIOScheduler(timezone=SGT)

    # Weekly digest: every Monday at 09:00 SGT
    scheduler.add_job(
        send_weekly_update,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=SGT),
        args=[app],
        id="weekly_digest",
        name="Weekly TCG tradeshow digest",
        replace_existing=True,
    )

    # Refresh events.json every Sunday at 23:00 SGT (async job)
    async def refresh_events():
        events = await run_scraper()
        logger.info("Scheduled scrape complete — %d events loaded", len(events))

    scheduler.add_job(
        refresh_events,
        CronTrigger(day_of_week="sun", hour=23, minute=0, timezone=SGT),
        id="weekly_scrape",
        name="Weekly event data refresh",
        replace_existing=True,
    )

    return scheduler
