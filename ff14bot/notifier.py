from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Bot

from .models import Event, EventDelivery, Subscriber
from .services import mark_sent


def _build_keyboard(event_id: int, confirmed: bool) -> Optional[InlineKeyboardMarkup]:
    if confirmed:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="Done! ⭐", callback_data=f"confirm:{event_id}")]]
    )


def render_event_text(
    event: Event, is_reminder: bool = False, tag: Optional[str] = None
) -> str:
    if tag:
        prefix = f"【{tag}】"
    else:
        prefix = "【活动提醒】" if is_reminder else "【新活动】"
    lines = [f"{prefix}{event.title}"]
    if event.time_text:
        # Only label as 时间 if we actually parsed a time range.
        label = (
            "活动时间"
            if (event.start_at is not None or event.end_at is not None)
            else "活动信息"
        )
        lines.append(f"{label}：{event.time_text}")
    if event.detail_url:
        lines.append(f"详情：{event.detail_url}")
    return "\n".join(lines)


async def send_event_to_subscriber(
    bot: Bot,
    subscriber: Subscriber,
    event: Event,
    delivery: EventDelivery,
    is_reminder: bool = False,
    tag: Optional[str] = None,
) -> None:
    text = render_event_text(event, is_reminder=is_reminder, tag=tag)
    keyboard = _build_keyboard(event.id, delivery.is_confirmed)
    if event.image_url:
        await bot.send_photo(
            chat_id=subscriber.chat_id,
            photo=event.image_url,
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await bot.send_message(
            chat_id=subscriber.chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    mark_sent(delivery, reminder=is_reminder)
