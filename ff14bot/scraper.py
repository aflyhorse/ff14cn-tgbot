from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from dateutil import parser


EVENT_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass
class ScrapedEvent:
    title: str
    time_text: str
    detail_url: Optional[str]
    image_url: Optional[str]
    start_at: Optional[datetime]
    end_at: Optional[datetime]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_TIME_TOKEN_RE = re.compile(
    r"(?:(?P<year>20\d{2})[年/-])?"
    r"(?P<month>\d{1,2})[月/-](?P<day>\d{1,2})日?\s*"
    r"(?:(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?)?"
)


def _build_local_datetime(
    match: re.Match[str], previous_local: Optional[datetime]
) -> Optional[datetime]:
    year_text = match.group("year")
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)

    if year_text:
        year = int(year_text)
    elif previous_local is not None:
        year = previous_local.year
    else:
        year = datetime.now(EVENT_TIMEZONE).year

    try:
        local_dt = datetime(year, month, day, hour, minute, tzinfo=EVENT_TIMEZONE)
    except ValueError:
        return None

    if year_text is None and previous_local is not None and local_dt < previous_local:
        try:
            local_dt = local_dt.replace(year=local_dt.year + 1)
        except ValueError:
            return None

    return local_dt


def _parse_time_range(time_text: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    normalized = time_text.replace("～", "~").replace("—", "-")
    matches: List[datetime] = []
    previous_local: Optional[datetime] = None
    for token in _TIME_TOKEN_RE.finditer(normalized):
        try:
            parsed = _build_local_datetime(token, previous_local)
            if parsed is None:
                raw = token.group(0)
                parsed = parser.parse(raw, fuzzy=True)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=EVENT_TIMEZONE)
            previous_local = parsed
            parsed_utc = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            matches.append(parsed_utc)
        except Exception:
            continue
    start_at = matches[0] if matches else None
    end_at = matches[1] if len(matches) > 1 else None
    return start_at, end_at


def _fetch_category(category_code: int, page_size: int = 20) -> List[dict]:
    # The ffactive page builds its UI by fetching JSON from cqnews.web.sdo.com.
    url = "https://cqnews.web.sdo.com/api/news/newsList"
    params = {
        "gameCode": "ff",
        "CategoryCode": str(category_code),
        "pageIndex": "0",
        "pageSize": str(page_size),
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if str(payload.get("Code")) != "0":
        return []
    return payload.get("Data") or []


def scrape_events(page_url: str) -> List[ScrapedEvent]:
    # NOTE: page_url is kept for compatibility, but the actual activity items
    # are fetched from a JSON API (see the ffactive page source).
    # The page splits activities into three sections via category codes:
    # - 7139: 萌新成长
    # - 7140: 商城补给
    # - 7141: 活动节庆
    # User requirement: only fetch 活动节庆.
    items: List[dict] = _fetch_category(7141)

    events: List[ScrapedEvent] = []
    seen = set()
    for item in items:
        title = _clean_text(str(item.get("Title") or ""))
        if not title:
            continue
        time_text_raw = _clean_text(str(item.get("Summary") or ""))
        # Return all entries in 活动节庆.
        # If the entry doesn't contain an explicit time range, we still keep it;
        # countdown will only apply when we can parse end_at.
        time_text = (
            _clean_text(re.sub(r"^活动时间[:：]\s*", "", time_text_raw))
            or time_text_raw
        )
        detail_url = item.get("OutLink")
        if detail_url:
            detail_url = urljoin(page_url, str(detail_url))
        image_url = item.get("HomeImagePath")
        if image_url:
            image_url = urljoin(page_url, str(image_url))
        start_at, end_at = _parse_time_range(time_text)

        key = (title, time_text, detail_url)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            ScrapedEvent(
                title=title,
                time_text=time_text,
                detail_url=detail_url,
                image_url=image_url,
                start_at=start_at,
                end_at=end_at,
            )
        )
    return events
