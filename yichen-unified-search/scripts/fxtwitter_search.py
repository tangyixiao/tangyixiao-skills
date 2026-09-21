#!/usr/bin/env python3
"""Search public X posts through FxTwitter without using an X login state."""

from __future__ import annotations

import argparse
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


API_URL = "https://api.fxtwitter.com/2/search"
BACKEND = "fxtwitter-public"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
USER_AGENT = "yichen-unified-search/1.0 (+local read-only public search)"


class SearchError(RuntimeError):
    """A safe, user-facing public-search error."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


def text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def parse_published_at(status: dict[str, Any]) -> str | None:
    timestamp = number_or_none(status.get("created_timestamp"))
    if timestamp is not None:
        try:
            return isoformat_utc(datetime.fromtimestamp(timestamp, timezone.utc))
        except (OverflowError, OSError, ValueError):
            pass

    raw = text_or_none(status.get("created_at"))
    if raw is None:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return isoformat_utc(parsed)


def canonical_status_url(status: dict[str, Any]) -> str | None:
    status_id = text_or_none(status.get("id"))
    if status_id is None:
        return None
    author = status.get("author")
    screen_name = (
        text_or_none(author.get("screen_name"))
        if isinstance(author, dict)
        else None
    )
    if screen_name:
        return f"https://x.com/{screen_name}/status/{status_id}"
    return f"https://x.com/i/status/{status_id}"


def article_projection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    article_id = text_or_none(value.get("id"))
    title = text_or_none(value.get("title"))
    preview_text = text_or_none(value.get("preview_text"))
    if not any((article_id, title, preview_text)):
        return None

    cover_url = None
    cover_media = value.get("cover_media")
    if isinstance(cover_media, dict):
        media_info = cover_media.get("media_info")
        if isinstance(media_info, dict):
            cover_url = text_or_none(
                media_info.get("original_img_url")
                or media_info.get("media_url_https")
                or media_info.get("media_url")
            )

    return {
        "id": article_id,
        "title": title,
        "preview_text": preview_text,
        "cover_url": cover_url,
    }


def quote_projection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") == "tombstone":
        return {
            "availability": text_or_none(value.get("reason")) or "unavailable",
            "id": text_or_none(value.get("id")),
            "url": text_or_none(value.get("url")),
            "author": None,
            "text": None,
            "published_at": None,
            "article": None,
        }
    if value.get("type") not in {None, "status"}:
        return None

    author = value.get("author")
    author_projection = None
    if isinstance(author, dict):
        author_projection = {
            "name": text_or_none(author.get("name")),
            "screen_name": text_or_none(author.get("screen_name")),
        }
    return {
        "availability": "public",
        "id": text_or_none(value.get("id")),
        "url": canonical_status_url(value),
        "author": author_projection,
        "text": text_or_none(value.get("text")),
        "published_at": parse_published_at(value),
        "article": article_projection(value.get("article")),
    }


def normalize_status(
    status: dict[str, Any],
    *,
    query: str,
    rank: int,
    retrieved_at: str,
) -> dict[str, Any] | None:
    status_id = text_or_none(status.get("id"))
    url = canonical_status_url(status)
    if status_id is None or url is None:
        return None

    author = status.get("author")
    author_name = None
    screen_name = None
    if isinstance(author, dict):
        author_name = text_or_none(author.get("name"))
        screen_name = text_or_none(author.get("screen_name"))

    article = article_projection(status.get("article"))
    quote = quote_projection(status.get("quote"))
    text = text_or_none(status.get("text"))
    if article is not None:
        content_type = "x_article"
        title = article.get("title") or (
            f"@{screen_name} 的 X Article" if screen_name else "X Article"
        )
        snippet = article.get("preview_text") or text
    elif quote is not None:
        content_type = "x_quote_post"
        title = f"@{screen_name} 的引用推文" if screen_name else "X 引用推文"
        snippet = text
    else:
        content_type = "x_post"
        title = f"@{screen_name} 的推文" if screen_name else "X 推文"
        snippet = text

    if snippet is not None:
        snippet = " ".join(snippet.split())
        if len(snippet) > 500:
            snippet = f"{snippet[:497]}..."

    limitations = [
        "FxTwitter is a third-party public index; this candidate is not proof of complete X coverage.",
        "The original X page was not opened during search.",
    ]
    if article is not None:
        limitations.append(
            "Search returns Article metadata and preview only; full-body reading belongs to yichen-content-archive."
        )
    if quote is not None and quote.get("availability") != "public":
        limitations.append("The quoted post is unavailable from the public result.")

    return {
        "candidate_id": f"x:{status_id}",
        "query": query,
        "platform": "x",
        "backend": BACKEND,
        "rank": rank,
        "title": title,
        "url": url,
        "canonical_url": url,
        "snippet": snippet,
        "author": author_name or (f"@{screen_name}" if screen_name else None),
        "published_at": parse_published_at(status),
        "content_type": content_type,
        "language": text_or_none(status.get("lang")),
        "metrics": {
            "likes": number_or_none(status.get("likes")),
            "comments": number_or_none(status.get("replies")),
            "collects": number_or_none(status.get("bookmarks")),
            "shares": number_or_none(status.get("reposts")),
            "views": number_or_none(status.get("views")),
            "quotes": number_or_none(status.get("quotes")),
        },
        "access": {
            "visibility": "public",
            "login_state_used": False,
        },
        "verification": {
            "status": "candidate",
            "opened_original": False,
            "checked_at": None,
        },
        "provenance": {
            "source_id": status_id,
            "retrieved_at": retrieved_at,
            "route_reason": "anonymous_public_x_search",
        },
        "platform_fields": {
            "screen_name": screen_name,
            "article": article,
            "quoted_post": quote,
        },
        "limitations": limitations,
    }


def filter_by_days(
    statuses: list[dict[str, Any]],
    days: int | None,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    if days in {None, 0}:
        return statuses
    cutoff = now.timestamp() - days * 86400
    filtered = []
    for status in statuses:
        timestamp = number_or_none(status.get("created_timestamp"))
        if timestamp is not None and timestamp >= cutoff:
            filtered.append(status)
    return filtered


def fetch_search(
    query: str,
    *,
    limit: int,
    feed: str,
    lang: str | None,
    timeout: int,
) -> dict[str, Any]:
    params: dict[str, str | int] = {
        "q": query,
        "feed": feed,
        "count": limit,
    }
    if lang:
        params["lang"] = lang
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"code": 404, "results": [], "cursor": {"top": None, "bottom": None}}
        category = {
            400: "invalid_query",
            429: "rate_limited",
        }.get(exc.code, "upstream_http_error")
        raise SearchError(
            category,
            f"FxTwitter returned HTTP {exc.code}; continue to the configured X fallback chain.",
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        category = "timeout" if isinstance(exc, TimeoutError) else "network_error"
        raise SearchError(
            category,
            "FxTwitter could not be reached; continue to the configured X fallback chain.",
        ) from exc

    if len(body) > MAX_RESPONSE_BYTES:
        raise SearchError(
            "response_too_large",
            "FxTwitter response exceeded the local safety limit.",
        )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchError(
            "invalid_response",
            "FxTwitter returned invalid JSON; continue to the configured X fallback chain.",
        ) from exc
    if not isinstance(payload, dict):
        raise SearchError("invalid_response", "FxTwitter returned an unexpected response.")
    code = payload.get("code")
    if code not in {200, 404}:
        raise SearchError(
            "upstream_api_error",
            f"FxTwitter returned API code {code!r}; continue to the configured X fallback chain.",
        )
    return payload


def make_envelope(
    *,
    query: str,
    limit: int,
    days: int | None,
    feed: str,
    payload: dict[str, Any] | None,
    error: SearchError | None,
    now: datetime,
) -> dict[str, Any]:
    retrieved_at = isoformat_utc(now)
    raw_results = payload.get("results", []) if payload else []
    if not isinstance(raw_results, list):
        raw_results = []
        if error is None:
            error = SearchError("invalid_response", "FxTwitter results were not a list.")
    statuses = [
        item
        for item in raw_results
        if isinstance(item, dict) and item.get("type") in {None, "status"}
    ]
    statuses = filter_by_days(statuses, days, now=now)

    candidates = []
    for status in statuses:
        candidate = normalize_status(
            status,
            query=query,
            rank=len(candidates) + 1,
            retrieved_at=retrieved_at,
        )
        if candidate is not None:
            candidates.append(candidate)
        if len(candidates) >= limit:
            break

    cursor = payload.get("cursor") if isinstance(payload, dict) else None
    has_more = bool(isinstance(cursor, dict) and cursor.get("bottom"))
    time_filter = (
        "none" if days in {None, 0} else f"local created_timestamp cutoff: last {days} day(s)"
    )
    route_limitations = [
        "One anonymous FxTwitter page was requested; no automatic pagination or retry was used.",
        "FxTwitter is a third-party public index and is not an official or exhaustive X search.",
    ]
    if days not in {None, 0}:
        route_limitations.append(
            "The time window was enforced locally on records with created_timestamp."
        )
    route_status = "failed" if error else "completed"
    errors = (
        [{"backend": BACKEND, "category": error.category, "message": error.message}]
        if error
        else []
    )
    return {
        "schema_version": "1.0",
        "request": {
            "queries": [query],
            "platforms": ["x"],
            "time_range": None if days in {None, 0} else {"days": days},
            "requested_limit": limit,
        },
        "routes": [
            {
                "platform": "x",
                "backend": BACKEND,
                "mode": "search",
                "login_state_used": False,
                "status": route_status,
                "limitations": route_limitations,
            }
        ],
        "candidates": candidates,
        "coverage": [
            {
                "platform": "x",
                "backend": BACKEND,
                "query_count": 1,
                "raw_result_count": len(raw_results),
                "returned_count": len(candidates),
                "feed": feed,
                "truncated": has_more or len(raw_results) >= limit,
                "time_filter": time_filter,
                "login_state_used": False,
                "limitations": route_limitations,
            }
        ],
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Anonymous, read-only public X search through FxTwitter."
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--days", type=int)
    parser.add_argument("--feed", choices=("latest", "top", "media"), default="latest")
    parser.add_argument("--lang")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    args.query = args.query.strip()
    if not args.query or len(args.query) > 500:
        parser.error("--query must contain 1 to 500 characters")
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if args.days is not None and not 0 <= args.days <= 180:
        parser.error("--days must be between 0 and 180")
    if not 5 <= args.timeout <= 60:
        parser.error("--timeout must be between 5 and 60 seconds")
    if args.lang and len(args.lang) > 16:
        parser.error("--lang is too long")
    return args


def main() -> int:
    args = parse_args()
    now = utc_now()
    payload = None
    error = None
    try:
        payload = fetch_search(
            args.query,
            limit=args.limit,
            feed=args.feed,
            lang=args.lang,
            timeout=args.timeout,
        )
    except SearchError as exc:
        error = exc
    envelope = make_envelope(
        query=args.query,
        limit=args.limit,
        days=args.days,
        feed=args.feed,
        payload=payload,
        error=error,
        now=now,
    )
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 2 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
