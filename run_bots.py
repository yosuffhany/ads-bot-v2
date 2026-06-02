"""
Runs both Telegram bots in the same asyncio event loop.
Avoids subprocess issues; both bots run concurrently.
Also runs daily BigQuery export at 03:00 UTC.
"""
import asyncio
import logging
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def run_app(app, name):
    """Start one bot Application and run it until cancelled."""
    logger.info(f"[run_bots] starting {name}")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info(f"[run_bots] {name} is polling")
        # Keep alive until cancelled
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()
    logger.info(f"[run_bots] {name} stopped")


async def run_bq_export_daily():
    """Run bq_export.main() every 2 hours."""
    import bq_export
    while True:
        try:
            logger.info("[bq_export] starting export...")
            await asyncio.get_event_loop().run_in_executor(None, bq_export.main)
            logger.info("[bq_export] export done")
        except Exception as e:
            logger.error(f"[bq_export] error: {e}")
        await asyncio.sleep(7200)  # 2 hours


async def main():
    from telegram_bot import build_app as build_balance
    from campaigns_bot import build_app as build_campaigns

    balance_app   = build_balance()
    campaigns_app = build_campaigns()

    tasks = [
        asyncio.create_task(run_app(balance_app,   "balance_bot")),
        asyncio.create_task(run_app(campaigns_app, "campaigns_bot")),
        asyncio.create_task(run_bq_export_daily()),
    ]
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"[run_bots] fatal error: {e}")
        for t in tasks:
            t.cancel()
        raise


if __name__ == '__main__':
    asyncio.run(main())
