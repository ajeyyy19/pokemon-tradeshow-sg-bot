"""
Entry point for the SG TCG Tradeshow Telegram Bot.

Start sequence:
1. Run scraper to refresh events.json from tcgcards.sg
2. Start APScheduler (Monday 9am SGT digest + Sunday 11pm scrape refresh)
3. Start Telegram bot (polling)
"""

import asyncio
import logging

from bot import build_app, setup_scheduler
from scraper import run_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # 1. Initial scrape to ensure events.json is fresh
    logger.info("Running initial event scrape...")
    events = await run_scraper()
    logger.info("Loaded %d events", len(events))

    # 2. Build Telegram app
    app = build_app()

    # 3. Set up scheduler
    scheduler = setup_scheduler(app)
    scheduler.start()
    logger.info("Scheduler started — weekly digest every Monday at 09:00 SGT")

    # 4. Start bot (polling)
    logger.info("Starting Telegram bot...")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running. Press Ctrl+C to stop.")

        # Keep running until interrupted
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            logger.info("Shutting down...")
            scheduler.shutdown(wait=False)
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
