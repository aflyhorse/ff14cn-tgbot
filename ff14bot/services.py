from datetime import datetime, timedelta
import hashlib
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Event, EventDelivery, Subscriber
from .scraper import ScrapedEvent


def _utcnow() -> datetime:
    return datetime.utcnow()


def _source_id(scraped: ScrapedEvent) -> str:
    basis = f"{scraped.title}|{scraped.time_text}|{scraped.detail_url or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def ensure_subscriber(
    session: Session,
    chat_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> Subscriber:
    subscriber = session.execute(
        select(Subscriber).where(Subscriber.chat_id == chat_id)
    ).scalar_one_or_none()
    if subscriber:
        subscriber.username = username
        subscriber.first_name = first_name
        subscriber.last_name = last_name
        return subscriber
    subscriber = Subscriber(
        chat_id=chat_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )
    session.add(subscriber)
    return subscriber


def list_subscribers(session: Session) -> List[Subscriber]:
    return list(session.execute(select(Subscriber)).scalars())


def sync_events(
    session: Session, scraped_events: Iterable[ScrapedEvent]
) -> Tuple[List[Event], List[Event]]:
    created: List[Event] = []
    updated: List[Event] = []
    for scraped in scraped_events:
        sid = _source_id(scraped)
        event = session.execute(
            select(Event).where(Event.source_id == sid)
        ).scalar_one_or_none()
        if event:
            event.title = scraped.title
            event.time_text = scraped.time_text
            event.detail_url = scraped.detail_url
            event.image_url = scraped.image_url
            event.start_at = scraped.start_at
            event.end_at = scraped.end_at
            updated.append(event)
        else:
            event = Event(
                source_id=sid,
                title=scraped.title,
                time_text=scraped.time_text,
                detail_url=scraped.detail_url,
                image_url=scraped.image_url,
                start_at=scraped.start_at,
                end_at=scraped.end_at,
            )
            session.add(event)
            created.append(event)
    return created, updated


def ensure_deliveries(
    session: Session, event: Event, subscribers: Iterable[Subscriber]
) -> List[EventDelivery]:
    deliveries: List[EventDelivery] = []
    for sub in subscribers:
        delivery = session.execute(
            select(EventDelivery).where(
                EventDelivery.event_id == event.id,
                EventDelivery.subscriber_id == sub.id,
            )
        ).scalar_one_or_none()
        if not delivery:
            delivery = EventDelivery(event=event, subscriber=sub)
            session.add(delivery)
        deliveries.append(delivery)
    return deliveries


def list_current_events(session: Session) -> List[Event]:
    now = _utcnow()
    stmt = (
        select(Event)
        .where(or_(Event.end_at.is_(None), Event.end_at >= now))
        .order_by(Event.start_at.is_(None), Event.start_at, Event.created_at.desc())
    )
    return list(session.execute(stmt).scalars())


def pending_reminders(session: Session, within_days: int = 3) -> List[EventDelivery]:
    now = _utcnow()
    deadline = now + timedelta(days=within_days)
    stmt = (
        select(EventDelivery)
        .join(Event)
        .where(
            Event.end_at.is_not(None),
            Event.end_at <= deadline,
            Event.end_at >= now,
            EventDelivery.confirmed_at.is_(None),
            EventDelivery.reminder_sent_at.is_(None),
        )
    )
    return list(session.execute(stmt).scalars())


def mark_sent(
    delivery: EventDelivery, when: Optional[datetime] = None, reminder: bool = False
) -> None:
    when = when or _utcnow()
    if delivery.first_sent_at is None:
        delivery.first_sent_at = when
    delivery.last_sent_at = when
    if reminder:
        delivery.reminder_sent_at = when


def mark_confirmed(delivery: EventDelivery, when: Optional[datetime] = None) -> None:
    when = when or _utcnow()
    delivery.confirmed_at = when
