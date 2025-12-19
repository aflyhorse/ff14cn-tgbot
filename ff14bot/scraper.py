from dataclasses import dataclass
from datetime import datetime
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from dateutil import parser


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


def _parse_time_range(time_text: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    normalized = time_text.replace("～", "~").replace("—", "-")
    pattern = re.compile(r"20\d{2}[年-]\d{1,2}[月-]\d{1,2}[日\s]*\d{0,2}:?\d{0,2}")
    matches: List[datetime] = []
    for raw in pattern.findall(normalized):
        try:
            matches.append(parser.parse(raw, fuzzy=True))
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
    items: List[dict] = []
    # Category codes used by the page:
    # 7139/7140/7141 (latest/ongoing/seasonal).
    # We only treat items with an explicit "活动时间" in Summary as time-bounded activities.
    for category in (7139, 7140, 7141):
        items.extend(_fetch_category(category))

    events: List[ScrapedEvent] = []
    seen = set()
    for item in items:
        title = _clean_text(str(item.get("Title") or ""))
        if not title:
            continue
        time_text_raw = _clean_text(str(item.get("Summary") or ""))
        if "活动时间" not in time_text_raw:
            continue
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
