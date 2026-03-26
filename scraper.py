"""
Scraper for https://www.tcgcards.sg/Singapore-card-trade-show
Uses Playwright (headless Chromium) to render the Google Sites page,
then parses event blocks into structured data saved to events.json.
"""

import asyncio
import json
import re
import logging
from datetime import date, datetime
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.tcgcards.sg/Singapore-card-trade-show"
EVENTS_FILE = Path(__file__).parent / "events.json"

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date_string(date_str: str) -> tuple[date, date]:
    """
    Parse date strings like:
      "28, 29th March 2026"    → (2026-03-28, 2026-03-29)
      "17-19th April 2026"     → (2026-04-17, 2026-04-19)
      "31st May 2026"          → (2026-05-31, 2026-05-31)
      "1-3rd May 2026"         → (2026-05-01, 2026-05-03)
    Returns (start_date, end_date).
    """
    date_str = date_str.strip()
    # Extract year and month
    year_match = re.search(r'\b(20\d{2})\b', date_str)
    month_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)', date_str, re.IGNORECASE)
    if not year_match or not month_match:
        raise ValueError(f"Cannot parse date: {date_str!r}")

    year = int(year_match.group(1))
    month = MONTH_MAP[month_match.group(1).lower()]

    # Extract day numbers — strip ordinal suffixes
    days_part = re.sub(r'(january|february|march|april|may|june|july|august|september|october|november|december)', '', date_str, flags=re.IGNORECASE)
    days_part = re.sub(r'\b(20\d{2})\b', '', days_part)
    days_part = re.sub(r'(st|nd|rd|th)', '', days_part)
    days_part = days_part.strip()

    # Find all numbers
    numbers = re.findall(r'\d+', days_part)
    if not numbers:
        raise ValueError(f"No day numbers found in: {date_str!r}")

    day_ints = [int(n) for n in numbers]
    start_day = day_ints[0]
    end_day = day_ints[-1]  # last number is end day

    return date(year, month, start_day), date(year, month, end_day)


async def scrape_events() -> list[dict]:
    """Scrape tcgcards.sg and return list of event dicts."""
    logger.info("Starting Playwright scrape of %s", EVENTS_URL)
    events = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(EVENTS_URL, wait_until="networkidle", timeout=60000)
            # Google Sites renders content in iframes or shadow DOM — wait for text
            await page.wait_for_timeout(3000)

            # Get all text content from the page
            content = await page.inner_text("body")
            events = parse_events_from_text(content)
            logger.info("Scraped %d events from website", len(events))

        except Exception as e:
            logger.error("Scrape failed: %s", e)
        finally:
            await browser.close()

    return events


def parse_events_from_text(text: str) -> list[dict]:
    """
    Parse the raw page text into event dicts.
    The page structure repeats:
      EVENT NAME (ALL CAPS heading)
      Date line (e.g. "28, 29th March 2026")
      Venue name
      Address
      Admission/hours line
    """
    events = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Date pattern to identify date lines
    date_pattern = re.compile(
        r'\b\d{1,2}(?:st|nd|rd|th)?(?:\s*[,\-–]\s*\d{1,2}(?:st|nd|rd|th)?)?\s+'
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+20\d{2}\b',
        re.IGNORECASE
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if next line (or this line) is a date — then previous line was event name
        if i + 1 < len(lines) and date_pattern.search(lines[i + 1]):
            event_name = line
            date_line = lines[i + 1]

            # Collect venue, address, hours from subsequent lines
            venue = lines[i + 2] if i + 2 < len(lines) else ""
            address = lines[i + 3] if i + 3 < len(lines) else ""
            hours_line = lines[i + 4] if i + 4 < len(lines) else ""

            # Clean up hours — remove "General Admission:" prefix
            hours = re.sub(r'^(General\s+Admission|Free\s+Admission|Admission)\s*:\s*', '', hours_line, flags=re.IGNORECASE).strip()
            if not hours:
                hours = "TBC"

            try:
                start_date, end_date = parse_date_string(date_line)
                events.append({
                    "name": event_name,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "venue": venue,
                    "address": address,
                    "hours": hours,
                })
                i += 5
                continue
            except ValueError as e:
                logger.warning("Date parse error for %r: %s", date_line, e)

        i += 1

    return events


def load_existing_events() -> list[dict]:
    """Load events from events.json if it exists."""
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE) as f:
            return json.load(f)
    return []


def save_events(events: list[dict]) -> None:
    """Save events list to events.json, sorted by start_date."""
    events_sorted = sorted(events, key=lambda e: e["start_date"])
    with open(EVENTS_FILE, "w") as f:
        json.dump(events_sorted, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d events to %s", len(events_sorted), EVENTS_FILE)


async def run_scraper() -> list[dict]:
    """
    Run scraper. If scrape yields results, save and return them.
    If scrape fails or returns nothing, fall back to existing events.json.
    """
    scraped = await scrape_events()

    if scraped:
        save_events(scraped)
        return scraped

    logger.warning("Scrape returned no events — using cached events.json")
    return load_existing_events()


if __name__ == "__main__":
    events = asyncio.run(run_scraper())
    print(f"Total events: {len(events)}")
    for e in events:
        print(f"  {e['start_date']} – {e['name']} @ {e['venue']}")
