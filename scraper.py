"""
Scraper for https://www.tcgcards.sg/singapore-card-trade-show/
Uses Playwright (headless Chromium) to render the page, walks the
paginated listing, and parses event blocks into events.json.

Page format (as of Oct 2026):
    02 Oct 2026 - 03 Oct 2026
    NEXUS x Slab Acad Midnight Tradeshow
    Yishun Safra Level 2 (Outside Slab Acad). 60 Yishun Ave 4, Singapore 769027
    General Admission: 5pm - 2am
"""

import asyncio
import json
import re
import logging
from datetime import date
from pathlib import Path
from playwright.async_api import async_playwright

from alerts import check_scrape_result, check_upcoming

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.tcgcards.sg/singapore-card-trade-show/"
EVENTS_FILE = Path(__file__).parent / "events.json"
MAX_PAGES = 25

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Matches a single date like "02 Oct 2026" or "2 October 2026"
SINGLE_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)

ADMISSION = re.compile(
    r"^\s*(general\s+admission|free\s+admission|admission|entry)\s*:",
    re.IGNORECASE,
)


def is_date_line(line: str) -> bool:
    """A line that starts with a date — the first line of an event block."""
    return bool(SINGLE_DATE.match(line.strip()))


def parse_date_line(line: str) -> tuple[date, date]:
    """
    Parse '02 Oct 2026 - 03 Oct 2026' or '11 Oct 2026'.
    Returns (start_date, end_date).
    """
    matches = SINGLE_DATE.findall(line)
    if not matches:
        raise ValueError(f"Cannot parse date: {line!r}")

    def to_date(m) -> date:
        day, mon, year = m
        key = mon[:3].lower()
        if key not in MONTHS:
            raise ValueError(f"Unknown month {mon!r} in {line!r}")
        return date(int(year), MONTHS[key], int(day))

    start = to_date(matches[0])
    end = to_date(matches[-1])
    if end < start:
        end = start
    return start, end


def split_location(line: str) -> tuple[str, str]:
    """
    The site merges venue and address into one line, usually separated
    by '. ' — e.g. 'Junction 8. 9 Bishan Pl, Singapore 579837'.
    """
    line = line.strip()
    parts = line.split(". ", 1)
    if len(parts) == 2 and parts[1]:
        return parts[0].strip(), parts[1].strip()
    return line, ""


def parse_events_from_text(text: str) -> list[dict]:
    """
    Walk the page text. Each event starts with a date line; everything
    up to the next date line belongs to that event.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    date_idx = [i for i, l in enumerate(lines) if is_date_line(l)]
    events = []

    for n, start in enumerate(date_idx):
        stop = date_idx[n + 1] if n + 1 < len(date_idx) else len(lines)
        block = lines[start + 1:stop]
        if not block:
            continue

        try:
            start_date, end_date = parse_date_line(lines[start])
        except ValueError as e:
            logger.warning("Skipping block: %s", e)
            continue

        name = block[0]
        hours = "TBC"
        location_lines = []

        for line in block[1:]:
            if ADMISSION.match(line):
                hours = ADMISSION.sub("", line).strip() or "TBC"
                break
            location_lines.append(line)

        venue, address = ("", "")
        if location_lines:
            venue, address = split_location(location_lines[0])
            # Any further lines before the admission line are extra address detail
            if len(location_lines) > 1 and not address:
                address = " ".join(location_lines[1:]).strip()

        events.append({
            "name": name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "venue": venue,
            "address": address,
            "hours": hours,
        })

    return events


async def scrape_events() -> list[dict]:
    """Scrape every page of the listing and return deduplicated events."""
    logger.info("Starting Playwright scrape of %s", BASE_URL)
    all_events: list[dict] = []
    seen: set[tuple[str, str]] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = await browser.new_page()

        try:
            for page_num in range(1, MAX_PAGES + 1):
                url = BASE_URL if page_num == 1 else f"{BASE_URL}?epage={page_num}"
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(2000)

                text = await page.inner_text("body")
                found = parse_events_from_text(text)

                new = [e for e in found if (e["name"], e["start_date"]) not in seen]
                for e in new:
                    seen.add((e["name"], e["start_date"]))
                all_events.extend(new)

                logger.info("Page %d: %d events (%d new)", page_num, len(found), len(new))

                # Stop when a page yields nothing, or nothing we haven't seen
                if not found or not new:
                    break

            logger.info("Scraped %d events from website", len(all_events))

        except Exception as e:
            logger.error("Scrape failed: %s", e)
        finally:
            await browser.close()

    return all_events


def load_existing_events() -> list[dict]:
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE) as f:
            return json.load(f)
    return []


def save_events(events: list[dict]) -> None:
    events_sorted = sorted(events, key=lambda e: e["start_date"])
    with open(EVENTS_FILE, "w") as f:
        json.dump(events_sorted, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d events to %s", len(events_sorted), EVENTS_FILE)


async def run_scraper() -> list[dict]:
    cached = load_existing_events()
    scraped = await scrape_events()
    await check_scrape_result(scraped, cached)

    if scraped:
        save_events(scraped)
        events = scraped
    else:
        logger.warning("Scrape returned no events — using cached events.json")
        events = cached

    await check_upcoming(events)
    return events


if __name__ == "__main__":
    events = asyncio.run(run_scraper())
    print(f"Total events: {len(events)}")
    for e in events:
        print(f"  {e['start_date']} – {e['name']} @ {e['venue']}")
