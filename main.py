#!/usr/bin/env python3

import argparse
import asyncio
import logging
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Bot
from telegram.request import HTTPXRequest

from ff14bot.bot_app import build_application
from ff14bot.config import load_settings
from ff14bot.database import init_db, session_scope
from ff14bot.notifier import send_event_to_subscriber
from ff14bot.scraper import scrape_events
from ff14bot.services import (
    ensure_deliveries,
    list_current_events,
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
    request = (
        HTTPXRequest(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    )
    bot = Bot(settings.telegram_token, request=request)
    suppressed_source_ids = set()
    with session_scope() as session:
        scraped = scrape_events(settings.source_url)
        logger.info("Scraped %d events", len(scraped))
        created, updated = sync_events(session, scraped)
        if not created:
            logger.info("No new events found (updated=%d)", len(updated))
            return

        # If a newly detected event is inherently short (e.g. total duration <= 3 days),
        # the scan-triggered countdown would immediately send a second "活动提醒".
        # We suppress ONLY the immediate countdown for those events; the normal
        # scheduled/manual countdown will still remind later if needed.
        for event in created:
            if event.start_at is None or event.end_at is None:
                continue
            if event.end_at <= event.start_at:
                continue
            if (event.end_at - event.start_at) <= timedelta(days=3):
                suppressed_source_ids.add(event.source_id)

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
    # After new event notifications, trigger countdown reminders
    await run_countdown(within_days=3, exclude_source_ids=sorted(suppressed_source_ids))
    logger.info("Scan completed and notifications sent")


async def run_countdown(within_days: int = 3, exclude_source_ids=None) -> None:
    settings = load_settings()
    init_db()
    request = (
        HTTPXRequest(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    )
    bot = Bot(settings.telegram_token, request=request)
    with session_scope() as session:
        deliveries = pending_reminders(
            session, within_days=within_days, exclude_source_ids=exclude_source_ids
        )
        if not deliveries:
            logger.info("No pending reminders")
            return
        for delivery in deliveries:
            await send_event_to_subscriber(
                bot, delivery.subscriber, delivery.event, delivery, is_reminder=True
            )
    logger.info("Countdown reminders sent")


def run_list() -> None:
    init_db()
    cst = ZoneInfo("Asia/Shanghai")
    with session_scope() as session:
        events = list_current_events(session)
        print("id\tend_at(CST)\tend_at(UTC)\ttitle")
        for event in events:
            if event.end_at is None:
                end_cst = "-"
                end_utc = "-"
            else:
                end_utc_dt = event.end_at.replace(tzinfo=timezone.utc)
                end_cst = end_utc_dt.astimezone(cst).strftime("%Y-%m-%d %H:%M")
                end_utc = end_utc_dt.strftime("%Y-%m-%d %H:%M")
            print(f"{event.id}\t{end_cst}\t{end_utc}\t{event.title}")


def run_bot() -> None:
    settings = load_settings()
    application = build_application(settings)
    application.run_polling()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FF14 国服 活动推送机器人")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bot", help="启动 Telegram Bot")
    sub.add_parser("scan", help="从官网抓取活动并推送新活动")
    sub.add_parser("list", help="列出数据库内当前活动及截止时间")
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
    elif args.command == "list":
        run_list()
    elif args.command == "countdown":
        asyncio.run(run_countdown(within_days=args.within_days))


if __name__ == "__main__":
    main()
