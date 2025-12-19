import logging
from datetime import datetime
from typing import List

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from sqlalchemy import select

from .config import Settings
from .database import init_db, session_scope
from .models import EventDelivery, Subscriber
from .notifier import send_event_to_subscriber
from .services import (
    ensure_deliveries,
    ensure_subscriber,
    list_current_events,
    mark_confirmed,
)


logger = logging.getLogger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # python-telegram-bot awaits error handlers; this must be async.
    logger.exception("Unhandled error", exc_info=context.error)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    user = update.effective_user
    with session_scope() as session:
        subscriber = ensure_subscriber(
            session,
            chat_id=update.effective_chat.id,
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
        )
        events = list_current_events(session)
        for event in events:
            ensure_deliveries(session, event, [subscriber])
    await update.message.reply_text("已订阅活动推送，使用 /list 查看当前活动。")


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    user = update.effective_user
    with session_scope() as session:
        subscriber = ensure_subscriber(
            session,
            chat_id=update.effective_chat.id,
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
        )
        events = list_current_events(session)
        deliveries: List[EventDelivery] = []
        for event in events:
            deliveries.extend(ensure_deliveries(session, event, [subscriber]))

        if not deliveries:
            await update.message.reply_text("当前没有正在进行或即将到来的活动。")
            return

        # Persist subscription + delivery rows even if sending fails.
        session.commit()

        for delivery in deliveries:
            try:
                await send_event_to_subscriber(
                    context.bot,
                    delivery.subscriber,
                    delivery.event,
                    delivery,
                    tag="活动",
                )
            except Exception:
                logger.exception(
                    "Failed to send /list event_id=%s to chat_id=%s",
                    delivery.event_id,
                    subscriber.chat_id,
                )
                # Continue with next delivery
                continue


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(f"Bot is running. Current server time: {now}")


async def handle_incomplete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    user = update.effective_user
    with session_scope() as session:
        subscriber = ensure_subscriber(
            session,
            chat_id=update.effective_chat.id,
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            last_name=user.last_name if user else None,
        )
        events = list_current_events(session)
        deliveries: List[EventDelivery] = []
        for event in events:
            deliveries.extend(ensure_deliveries(session, event, [subscriber]))

        deliveries = [d for d in deliveries if not d.is_confirmed]
        if not deliveries:
            await update.message.reply_text("当前没有未完成的活动。")
            return

        session.commit()
        for delivery in deliveries:
            try:
                await send_event_to_subscriber(
                    context.bot,
                    delivery.subscriber,
                    delivery.event,
                    delivery,
                    tag="未完成",
                )
            except Exception:
                logger.exception(
                    "Failed to send /incomplete event_id=%s to chat_id=%s",
                    delivery.event_id,
                    subscriber.chat_id,
                )
                continue


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    await query.answer()
    data = query.data or ""
    if not data.startswith("confirm:"):
        return
    try:
        event_id = int(data.split(":", 1)[1])
    except ValueError:
        await query.edit_message_reply_markup(None)
        return

    with session_scope() as session:
        subscriber = session.execute(
            select(Subscriber).where(Subscriber.chat_id == update.effective_chat.id)
        ).scalar_one_or_none()
        if not subscriber:
            await query.edit_message_text("请先发送 /start 订阅活动推送。")
            return
        delivery = session.execute(
            select(EventDelivery).where(
                EventDelivery.subscriber_id == subscriber.id,
                EventDelivery.event_id == event_id,
            )
        ).scalar_one_or_none()
        if not delivery:
            await query.edit_message_text("未找到对应活动，请稍后再试。")
            return
        mark_confirmed(delivery)
    await query.edit_message_reply_markup(None)
    await query.answer("已确认")


def build_application(settings: Settings) -> Application:
    init_db()
    if settings.telegram_proxy:
        request = HTTPXRequest(proxy=settings.telegram_proxy)
        application = (
            ApplicationBuilder().token(settings.telegram_token).request(request).build()
        )
    else:
        application = ApplicationBuilder().token(settings.telegram_token).build()
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("list", handle_list))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(CommandHandler("incomplete", handle_incomplete))
    application.add_handler(CallbackQueryHandler(handle_confirm, pattern=r"^confirm:"))
    application.add_error_handler(handle_error)
    return application
