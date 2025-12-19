#!/usr/bin/env python3

import argparse
import asyncio
import logging

from telegram import Bot

from ff14bot.bot_app import build_application
from ff14bot.config import load_settings
from ff14bot.database import init_db, session_scope
from ff14bot.notifier import send_event_to_subscriber
from ff14bot.scraper import scrape_events
from ff14bot.services import (
    ensure_deliveries,
    list_subscribers,
    pending_reminders,
    sync_events,
)


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


async def run_scan() -> None:
    settings = load_settings()
    init_db()
    bot = Bot(settings.telegram_token)
    with session_scope() as session:
        scraped = scrape_events(settings.source_url)
        logger.info("Scraped %d events", len(scraped))
        created, updated = sync_events(session, scraped)
        if not created:
            logger.info("No new events found (updated=%d)", len(updated))
            return
        subscribers = list_subscribers(session)
        if not subscribers:
            logger.info("No subscribers yet, skipping notifications")
            return
        for event in created:
            deliveries = ensure_deliveries(session, event, subscribers)
            for delivery in deliveries:
                await send_event_to_subscriber(
                    bot, delivery.subscriber, delivery.event, delivery
                )
    logger.info("Scan completed and notifications sent")


async def run_countdown(within_days: int = 3) -> None:
    settings = load_settings()
    init_db()
    bot = Bot(settings.telegram_token)
    with session_scope() as session:
        deliveries = pending_reminders(session, within_days=within_days)
        if not deliveries:
            logger.info("No pending reminders")
            return
        for delivery in deliveries:
            await send_event_to_subscriber(
                bot, delivery.subscriber, delivery.event, delivery, is_reminder=True
            )
    logger.info("Countdown reminders sent")


def run_bot() -> None:
    settings = load_settings()
    application = build_application(settings)
    application.run_polling()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FF14 国服 活动推送机器人")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bot", help="启动 Telegram Bot")
    sub.add_parser("scan", help="从官网抓取活动并推送新活动")
    countdown = sub.add_parser("countdown", help="给三天内未确认的活动发送提醒")
    countdown.add_argument(
        "--within-days", type=int, default=3, help="提醒窗口天数，默认 3 天"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "bot":
        run_bot()
    elif args.command == "scan":
        asyncio.run(run_scan())
    elif args.command == "countdown":
        asyncio.run(run_countdown(within_days=args.within_days))


if __name__ == "__main__":
    main()
