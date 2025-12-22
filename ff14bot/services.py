from datetime import datetime, timedelta
import hashlib
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import or_, select, update
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
    now = _utcnow()
    seen_source_ids: List[str] = []
    for scraped in scraped_events:
        sid = _source_id(scraped)
        seen_source_ids.append(sid)
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
            event.is_active = True
            event.last_seen_at = now
            event.removed_at = None
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
                is_active=True,
                last_seen_at=now,
                removed_at=None,
            )
            session.add(event)
            created.append(event)

    # Anything no longer present on the source page is marked inactive.
    if seen_source_ids:
        session.execute(
            update(Event)
            .where(Event.is_active.is_(True), Event.source_id.not_in(seen_source_ids))
            .values(is_active=False, removed_at=now)
        )
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
        .where(Event.is_active.is_(True))
        .where(or_(Event.end_at.is_(None), Event.end_at >= now))
        .order_by(Event.start_at.is_(None), Event.start_at, Event.created_at.desc())
    )
    return list(session.execute(stmt).scalars())


def pending_reminders(
    session: Session,
    within_days: int = 3,
    exclude_source_ids: Optional[Sequence[str]] = None,
) -> List[EventDelivery]:
    now = _utcnow()
    deadline = now + timedelta(days=within_days)
    stmt = (
        select(EventDelivery)
        .join(Event)
        .where(
            Event.is_active.is_(True),
            Event.end_at.is_not(None),
            Event.end_at <= deadline,
            Event.end_at >= now,
            EventDelivery.confirmed_at.is_(None),
            EventDelivery.reminder_sent_at.is_(None),
        )
    )
    if exclude_source_ids:
        stmt = stmt.where(Event.source_id.not_in(list(exclude_source_ids)))
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
