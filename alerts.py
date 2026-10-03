"""
Operational alerts for the scraper, sent privately to an admin chat.

Never raises: alerting must not break a scrape. Never logs request URLs,
since the Telegram API URL contains the bot token.
"""

import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent
load_dotenv(REPO_ROOT / ".env")

# httpx logs full request URLs (including the token) at INFO
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

SGT = ZoneInfo("Asia/Singapore")
EVENTS_FILE = REPO_ROOT / "events.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

STALE_CACHE_DAYS = 5
MIN_UPCOMING = 3


async def notify_admin(text: str) -> None:
    """Send text to ADMIN_CHAT_ID. Logs only status codes or exception class names."""
    if not ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID not set — alert not sent: %s", text)
        return
    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — alert not sent: %s", text)
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": ADMIN_CHAT_ID, "text": text},
            )
        if resp.status_code == 200:
            logger.info("Admin alert sent")
        else:
            logger.warning("Admin alert failed with status %d", resp.status_code)
    except Exception as e:
        logger.warning("Admin alert failed: %s", type(e).__name__)


def events_file_age_days() -> float | None:
    """Days since events.json was last modified, or None if it doesn't exist."""
    try:
        return (time.time() - EVENTS_FILE.stat().st_mtime) / 86400
    except OSError:
        return None


async def check_scrape_result(scraped: list[dict], cached: list[dict]) -> None:
    """Alert when the scrape came back empty and the bot is falling back to cache."""
    if scraped:
        return
    age = events_file_age_days()
    age_text = "missing" if age is None else f"{age:.1f} days old"
    msg = (
        "⚠️ Scrape returned no events — falling back to cached events.json "
        f"({len(cached)} events, {age_text})."
    )
    if age is None or age >= STALE_CACHE_DAYS:
        msg += (
            f"\n🚨 Cache is {STALE_CACHE_DAYS}+ days old or missing — "
            "the site layout may have changed. Check the scraper."
        )
    await notify_admin(msg)


async def check_upcoming(events: list[dict]) -> None:
    """Alert if no events remain from today on, or fewer than MIN_UPCOMING."""
    today = datetime.now(SGT).date()
    upcoming = 0
    for ev in events:
        try:
            if date.fromisoformat(ev["end_date"]) >= today:
                upcoming += 1
        except (KeyError, TypeError, ValueError):
            continue

    if upcoming == 0:
        await notify_admin("🚨 No upcoming events in the event list — nothing to announce.")
    elif upcoming < MIN_UPCOMING:
        await notify_admin(f"⚠️ Only {upcoming} upcoming event(s) left in the event list.")
