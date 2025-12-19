from typing import List

from telegram import Update
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
    deliveries: List[EventDelivery] = []
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
            deliveries.extend(ensure_deliveries(session, event, [subscriber]))
    if not deliveries:
        await update.message.reply_text("当前没有正在进行或即将到来的活动。")
        return
    for delivery in deliveries:
        await send_event_to_subscriber(
            context.bot, delivery.subscriber, delivery.event, delivery
        )


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
    application = ApplicationBuilder().token(settings.telegram_token).build()
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("list", handle_list))
    application.add_handler(CallbackQueryHandler(handle_confirm, pattern=r"^confirm:"))
    return application
