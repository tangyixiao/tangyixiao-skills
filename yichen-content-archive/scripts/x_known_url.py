#!/usr/bin/env python3
"""Read one known public X URL without using an account login state."""

from __future__ import annotations

import argparse
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


FX_API = "https://api.fxtwitter.com/2"
JINA_READER = "https://r.jina.ai/http://x.com"
USER_AGENT = "yichen-content-archive/1.0 (+known public X URL reader)"
MAX_JSON_BYTES = 12 * 1024 * 1024
MAX_MARKDOWN_BYTES = 6 * 1024 * 1024
ALLOWED_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}


class KnownUrlError(RuntimeError):
    """A safe public error that never contains credentials."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_known_url(value: str) -> dict[str, str | None]:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError as exc:
        raise KnownUrlError("invalid_url", "The supplied X URL is invalid.") from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise KnownUrlError(
            "unsupported_url",
            "Only explicit x.com or twitter.com status and Article URLs are accepted.",
        )

    status_match = re.fullmatch(
        r"/(?P<handle>[^/]+)/status/(?P<id>\d+)(?:/.*)?",
        parsed.path.rstrip("/"),
    )
    if status_match:
        return {
            "input_kind": "x_status_url",
            "id": status_match.group("id"),
            "handle": status_match.group("handle"),
            "canonical_url": (
                f"https://x.com/{status_match.group('handle')}/status/"
                f"{status_match.group('id')}"
            ),
        }

    web_status_match = re.fullmatch(
        r"/i/(?:web/)?status/(?P<id>\d+)(?:/.*)?",
        parsed.path.rstrip("/"),
    )
    if web_status_match:
        return {
            "input_kind": "x_status_url",
            "id": web_status_match.group("id"),
            "handle": None,
            "canonical_url": f"https://x.com/i/status/{web_status_match.group('id')}",
        }

    article_match = re.fullmatch(
        r"/i/article/(?P<id>\d+)(?:/.*)?",
        parsed.path.rstrip("/"),
    )
    if article_match:
        return {
            "input_kind": "x_article_url",
            "id": article_match.group("id"),
            "handle": None,
            "canonical_url": f"https://x.com/i/article/{article_match.group('id')}",
        }

    raise KnownUrlError(
        "unsupported_url",
        "The URL is not a supported X status or Article URL.",
    )


def read_limited(response: Any, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise KnownUrlError("response_too_large", "The public response was too large.")
    return body


def fetch_json(path: str, *, query: dict[str, str | int] | None, timeout: int) -> dict:
    url = f"{FX_API}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = read_limited(response, MAX_JSON_BYTES)
    except urllib.error.HTTPError as exc:
        category = {
            400: "invalid_request",
            404: "not_found",
            429: "rate_limited",
        }.get(exc.code, "upstream_http_error")
        raise KnownUrlError(
            category,
            f"FxTwitter returned HTTP {exc.code}.",
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise KnownUrlError(
            "network_error",
            "FxTwitter could not be reached.",
        ) from exc
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnownUrlError("invalid_response", "FxTwitter returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise KnownUrlError("invalid_response", "FxTwitter returned an unexpected response.")
    if payload.get("code") != 200:
        raise KnownUrlError(
            "upstream_api_error",
            f"FxTwitter returned API code {payload.get('code')!r}.",
        )
    return payload


def status_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if not isinstance(status, dict) or status.get("type") == "tombstone":
        raise KnownUrlError("not_found", "The public status is unavailable.")
    return status


def find_article_parent(
    results: Any,
    article_id: str,
) -> dict[str, Any] | None:
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict):
            continue
        article = result.get("article")
        if isinstance(article, dict) and str(article.get("id")) == article_id:
            return result
        quote = result.get("quote")
        if isinstance(quote, dict):
            quote_article = quote.get("article")
            if (
                isinstance(quote_article, dict)
                and str(quote_article.get("id")) == article_id
            ):
                return quote
    return None


def canonical_status_url(status: dict[str, Any]) -> str | None:
    status_id = text_or_none(status.get("id"))
    if not status_id:
        return None
    author = status.get("author")
    handle = (
        text_or_none(author.get("screen_name"))
        if isinstance(author, dict)
        else None
    )
    if handle:
        return f"https://x.com/{handle}/status/{status_id}"
    return f"https://x.com/i/status/{status_id}"


def author_projection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": text_or_none(value.get("id")),
        "name": text_or_none(value.get("name")),
        "screen_name": text_or_none(value.get("screen_name")),
        "followers": number_or_none(value.get("followers")),
        "verified": (
            value.get("verification", {}).get("verified")
            if isinstance(value.get("verification"), dict)
            else None
        ),
    }


def media_url(media_info: Any) -> str | None:
    if not isinstance(media_info, dict):
        return None
    return text_or_none(
        media_info.get("original_img_url")
        or media_info.get("media_url_https")
        or media_info.get("media_url")
        or media_info.get("url")
        or media_info.get("thumbnail_url")
    )


def media_url_source(media_info: Any) -> str | None:
    if not isinstance(media_info, dict):
        return None
    for key in (
        "original_img_url",
        "media_url_https",
        "media_url",
        "url",
        "thumbnail_url",
    ):
        if text_or_none(media_info.get(key)):
            return key
    return None


def _media_type_values(entity: dict[str, Any], media_info: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for record in (entity, media_info):
        for key in (
            "__typename",
            "type",
            "kind",
            "media_type",
            "content_type",
            "mime_type",
        ):
            value = text_or_none(record.get(key))
            if value:
                values.append(value)
    return values


def _nonempty_media_value(value: Any) -> bool:
    return value not in (None, False, "", [], {})


def article_media_kind(
    entity: dict[str, Any], media_info: dict[str, Any], url: str
) -> str:
    """Classify only from explicit evidence; thumbnail-only media is unknown."""

    type_values = [
        value.lower().replace("-", "_")
        for value in _media_type_values(entity, media_info)
    ]
    if any("video" in value or value == "animated_gif" for value in type_values):
        return "video"
    for record in (entity, media_info):
        if any(
            _nonempty_media_value(record.get(key))
            for key in (
                "video_info",
                "videoInfo",
                "variants",
                "video_variants",
                "playback_url",
                "video_url",
                "mp4_url",
                "duration_ms",
                "duration_millis",
                "is_video",
            )
        ):
            return "video"
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "unknown"
    host = (parsed.hostname or "").lower()
    if host == "video.twimg.com" or parsed.path.lower().endswith(
        (".mp4", ".m3u8", ".mov", ".webm")
    ):
        return "video"
    if any("image" in value or "photo" in value for value in type_values):
        return "photo"
    source = media_url_source(media_info)
    if source in {"original_img_url", "media_url_https", "media_url"}:
        return "photo"
    return "unknown"


def _safe_variant_url(value: Any) -> str | None:
    url = text_or_none(value)
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    # Variant query strings may be signed.  Preserve the public CDN path while
    # never projecting credentials or query parameters into ordinary output.
    return urllib.parse.urlunsplit(("https", parsed.hostname, parsed.path, "", ""))


def article_video_info(
    entity: dict[str, Any], media_info: dict[str, Any]
) -> dict[str, Any] | None:
    candidates = [
        media_info.get("video_info"),
        media_info.get("videoInfo"),
        entity.get("video_info"),
        entity.get("videoInfo"),
        media_info,
        entity,
    ]
    records = [value for value in candidates if isinstance(value, dict)]
    variants: list[Any] = []
    for record in records:
        for key in ("variants", "video_variants"):
            value = record.get(key)
            if isinstance(value, list):
                variants = value
                break
        if variants:
            break
    projected_variants: list[dict[str, Any]] = []
    for value in variants:
        if not isinstance(value, dict):
            continue
        variant_url = _safe_variant_url(
            value.get("url") or value.get("src") or value.get("source")
        )
        projected_variants.append(
            {
                "content_type": text_or_none(
                    value.get("content_type")
                    or value.get("type")
                    or value.get("mime_type")
                ),
                "bitrate": number_or_none(value.get("bitrate")),
                "url": variant_url,
            }
        )
    duration = None
    for record in records:
        duration = number_or_none(
            record.get("duration_millis") or record.get("duration_ms")
        )
        if duration is not None:
            break
    if not projected_variants and duration is None:
        return None
    return {
        "duration_millis": duration,
        "variant_count": len(projected_variants),
        "variants": projected_variants,
    }


def article_media(article: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    media_entities = article.get("media_entities", [])
    if not isinstance(media_entities, list):
        return [
            {
                "id": None,
                "url": None,
                "kind": "unknown",
                "source_media_type": None,
                "url_source": None,
                "projection_error": "media_entities_not_a_list",
            }
        ]
    for media_index, entity in enumerate(media_entities, start=1):
        if not isinstance(entity, dict):
            output.append(
                {
                    "id": None,
                    "url": None,
                    "kind": "unknown",
                    "source_media_type": None,
                    "url_source": None,
                    "projection_error": f"media_entity_{media_index}_not_an_object",
                }
            )
            continue
        media_id = (
            text_or_none(entity.get("media_id"))
            or text_or_none(entity.get("media_key"))
            or text_or_none(entity.get("id"))
        )
        media_info = entity.get("media_info")
        if not isinstance(media_info, dict):
            output.append(
                {
                    "id": media_id,
                    "url": None,
                    "kind": "unknown",
                    "source_media_type": None,
                    "url_source": None,
                    "projection_error": "media_info_not_an_object",
                }
            )
            continue
        url = media_url(media_info)
        if not url:
            output.append(
                {
                    "id": media_id,
                    "url": None,
                    "kind": "unknown",
                    "source_media_type": next(
                        iter(_media_type_values(entity, media_info)), None
                    ),
                    "url_source": None,
                    "projection_error": "media_url_missing",
                }
            )
            continue
        kind = article_media_kind(entity, media_info, url)
        record = {
            "id": media_id,
            "url": url,
            "kind": kind,
            "source_media_type": next(
                iter(_media_type_values(entity, media_info)), None
            ),
            "url_source": media_url_source(media_info),
        }
        if kind == "video":
            record["video_info"] = article_video_info(entity, media_info)
        output.append(record)
    return output


def entity_map_by_key(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = content.get("entityMap")
    if isinstance(raw, dict):
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(value, dict)
        }
    if isinstance(raw, list):
        output = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key is not None and isinstance(value, dict):
                output[str(key)] = value
        return output
    return {}


def entity_map_by_key_audited(
    content: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    raw = content.get("entityMap")
    output: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    if raw is None:
        return output, errors
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                output[str(key)] = value
            else:
                errors.append(
                    {
                        "category": "entity_map_value_not_object",
                        "entity_key": str(key),
                    }
                )
        return output, errors
    if not isinstance(raw, list):
        return output, [{"category": "entity_map_not_object_or_list"}]
    for entity_index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(
                {
                    "category": "entity_map_entry_not_object",
                    "entity_index": entity_index,
                }
            )
            continue
        key = item.get("key")
        value = item.get("value")
        if key is None or not isinstance(value, dict):
            errors.append(
                {
                    "category": "entity_map_entry_invalid",
                    "entity_index": entity_index,
                }
            )
            continue
        output[str(key)] = value
    return output, errors


def utf16_to_python_index(text: str, code_units: int) -> int:
    consumed = 0
    for index, character in enumerate(text):
        if consumed >= code_units:
            return index
        consumed += 2 if ord(character) > 0xFFFF else 1
    return len(text)


def apply_link_entities(
    text: str,
    ranges: Any,
    entities: dict[str, dict[str, Any]],
) -> str:
    if not isinstance(ranges, list):
        return text
    replacements = []
    for value in ranges:
        if not isinstance(value, dict):
            continue
        entity = entities.get(str(value.get("key")))
        if not isinstance(entity, dict) or entity.get("type") != "LINK":
            continue
        data = entity.get("data")
        url = text_or_none(data.get("url")) if isinstance(data, dict) else None
        offset = value.get("offset")
        length = value.get("length")
        if not url or not isinstance(offset, int) or not isinstance(length, int):
            continue
        start = utf16_to_python_index(text, offset)
        end = utf16_to_python_index(text, offset + length)
        if end > start:
            replacements.append((start, end, url))
    rendered = text
    for start, end, url in sorted(replacements, reverse=True):
        label = rendered[start:end]
        rendered = f"{rendered[:start]}[{label}]({url}){rendered[end:]}"
    return rendered


def _utf16_boundaries(text: str) -> dict[int, int]:
    boundaries = {0: 0}
    consumed = 0
    for index, character in enumerate(text, start=1):
        consumed += 2 if ord(character) > 0xFFFF else 1
        boundaries[consumed] = index
    return boundaries


def apply_link_entities_audited(
    text: str,
    ranges: Any,
    entities: dict[str, dict[str, Any]],
    *,
    block_index: int,
) -> tuple[str, list[dict[str, Any]]]:
    if ranges is None:
        return text, []
    if not isinstance(ranges, list):
        return text, [
            {
                "category": "link_entity_ranges_not_list",
                "block_index": block_index,
            }
        ]
    replacements: list[tuple[int, int, str, int]] = []
    errors: list[dict[str, Any]] = []
    boundaries = _utf16_boundaries(text)
    for range_index, value in enumerate(ranges, start=1):
        location = {"block_index": block_index, "range_index": range_index}
        if not isinstance(value, dict):
            errors.append({"category": "link_range_not_object", **location})
            continue
        key = value.get("key")
        entity = entities.get(str(key)) if key is not None else None
        if not isinstance(entity, dict):
            errors.append({"category": "link_entity_missing", **location})
            continue
        if entity.get("type") != "LINK":
            errors.append({"category": "inline_entity_unsupported", **location})
            continue
        data = entity.get("data")
        url = text_or_none(data.get("url")) if isinstance(data, dict) else None
        if not url:
            errors.append({"category": "link_url_missing", **location})
            continue
        offset = value.get("offset")
        length = value.get("length")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or isinstance(length, bool)
            or not isinstance(length, int)
            or offset < 0
            or length <= 0
            or offset not in boundaries
            or offset + length not in boundaries
        ):
            errors.append({"category": "link_range_invalid", **location})
            continue
        replacements.append(
            (boundaries[offset], boundaries[offset + length], url, range_index)
        )

    accepted: list[tuple[int, int, str, int]] = []
    previous_end = -1
    for start, end, url, range_index in sorted(replacements):
        if start < previous_end:
            errors.append(
                {
                    "category": "link_ranges_overlap",
                    "block_index": block_index,
                    "range_index": range_index,
                }
            )
            continue
        accepted.append((start, end, url, range_index))
        previous_end = end
    rendered = text
    for start, end, url, _range_index in sorted(accepted, reverse=True):
        label = rendered[start:end]
        rendered = f"{rendered[:start]}[{label}]({url}){rendered[end:]}"
    return rendered, errors


def media_lookup(article: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in article_media(article):
        if item["kind"] == "photo" and item["id"]:
            output[str(item["id"])] = item["url"]
            match = re.search(r"(\d{8,})$", str(item["id"]))
            if match:
                output[match.group(1)] = item["url"]
    return output


def render_atomic(
    block: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    media_by_id: dict[str, str],
) -> str:
    ranges = block.get("entityRanges")
    if not isinstance(ranges, list) or not ranges:
        return ""
    entity = entities.get(str(ranges[0].get("key")))
    if not isinstance(entity, dict) or entity.get("type") != "MEDIA":
        return ""
    data = entity.get("data")
    if not isinstance(data, dict):
        return ""
    caption = text_or_none(data.get("caption")) or "X Article media"
    media_items = data.get("mediaItems")
    if isinstance(media_items, list):
        for media_item in media_items:
            if not isinstance(media_item, dict):
                continue
            media_id = text_or_none(media_item.get("mediaId"))
            url = media_by_id.get(media_id or "")
            if url:
                return f"![{caption}]({url})"
    return ""


def render_atomic_audited(
    block: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    media_by_id: dict[str, str],
    *,
    block_index: int,
) -> tuple[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    ranges = block.get("entityRanges")
    if not isinstance(ranges, list) or not ranges:
        return "", [
            {
                "category": "atomic_entity_range_missing",
                "block_index": block_index,
            }
        ]
    if len(ranges) != 1:
        errors.append(
            {
                "category": "atomic_entity_range_count_invalid",
                "block_index": block_index,
            }
        )
    entity_range = ranges[0]
    if not isinstance(entity_range, dict):
        errors.append(
            {
                "category": "atomic_entity_range_not_object",
                "block_index": block_index,
            }
        )
        return "", errors
    offset = entity_range.get("offset")
    length = entity_range.get("length")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or isinstance(length, bool)
        or not isinstance(length, int)
        or offset < 0
        or length <= 0
    ):
        errors.append(
            {
                "category": "atomic_entity_range_invalid",
                "block_index": block_index,
            }
        )
    key = entity_range.get("key")
    entity = entities.get(str(key)) if key is not None else None
    if not isinstance(entity, dict):
        errors.append(
            {"category": "atomic_entity_missing", "block_index": block_index}
        )
        return "", errors
    if entity.get("type") != "MEDIA":
        errors.append(
            {"category": "atomic_entity_not_media", "block_index": block_index}
        )
        return "", errors
    data = entity.get("data")
    if not isinstance(data, dict):
        errors.append(
            {"category": "atomic_data_invalid", "block_index": block_index}
        )
        return "", errors
    caption = text_or_none(data.get("caption")) or "X Article media"
    media_items = data.get("mediaItems")
    if not isinstance(media_items, list) or not media_items:
        errors.append(
            {
                "category": "atomic_media_items_invalid",
                "block_index": block_index,
            }
        )
        return "", errors
    rendered_items: list[str] = []
    for media_index, media_item in enumerate(media_items, start=1):
        location = {"block_index": block_index, "media_index": media_index}
        if not isinstance(media_item, dict):
            errors.append(
                {"category": "atomic_media_item_not_object", **location}
            )
            continue
        media_id = text_or_none(media_item.get("mediaId"))
        if not media_id:
            errors.append({"category": "atomic_media_id_missing", **location})
            continue
        url = media_by_id.get(media_id)
        if not url:
            errors.append({"category": "atomic_media_unrenderable", **location})
            continue
        rendered_items.append(f"![{caption}]({url})")
    return "\n\n".join(rendered_items), errors


def render_article_markdown_audited(
    article: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    content = article.get("content")
    if not isinstance(content, dict):
        errors.append({"category": "article_content_not_object"})
        return None, {
            "status": "incomplete",
            "complete": False,
            "declared_block_count": None,
            "rendered_block_count": 0,
            "empty_block_count": 0,
            "errors": errors,
        }
    blocks = content.get("blocks")
    if not isinstance(blocks, list):
        errors.append({"category": "article_blocks_not_list"})
        return None, {
            "status": "incomplete",
            "complete": False,
            "declared_block_count": None,
            "rendered_block_count": 0,
            "empty_block_count": 0,
            "errors": errors,
        }
    entities, entity_errors = entity_map_by_key_audited(content)
    errors.extend(entity_errors)
    media_by_id = media_lookup(article)
    lines: list[str] = []
    empty_block_count = 0
    ordered_index = 0
    previous_type = None
    supported_types = {
        "unstyled",
        "header-one",
        "header-two",
        "header-three",
        "blockquote",
        "unordered-list-item",
        "ordered-list-item",
        "code-block",
        "atomic",
    }
    for block_index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            errors.append(
                {"category": "block_not_object", "block_index": block_index}
            )
            continue
        raw_block_type = block.get("type", "unstyled")
        if not isinstance(raw_block_type, str) or not raw_block_type.strip():
            errors.append(
                {"category": "block_type_invalid", "block_index": block_index}
            )
            block_type = "unstyled"
        else:
            block_type = raw_block_type.strip()
        raw_text = block.get("text", "")
        if not isinstance(raw_text, str):
            errors.append(
                {"category": "block_text_not_string", "block_index": block_index}
            )
            text = ""
        else:
            text = raw_text
        if block_type == "atomic":
            rendered, block_errors = render_atomic_audited(
                block, entities, media_by_id, block_index=block_index
            )
        else:
            text, block_errors = apply_link_entities_audited(
                text,
                block.get("entityRanges"),
                entities,
                block_index=block_index,
            )
            if block_type not in supported_types:
                block_errors.append(
                    {
                        "category": "block_type_unsupported",
                        "block_index": block_index,
                    }
                )
            if block_type == "header-one":
                rendered = f"# {text}"
            elif block_type == "header-two":
                rendered = f"## {text}"
            elif block_type == "header-three":
                rendered = f"### {text}"
            elif block_type == "blockquote":
                rendered = "\n".join(f"> {line}" for line in text.splitlines())
            elif block_type == "unordered-list-item":
                rendered = f"- {text}"
            elif block_type == "ordered-list-item":
                ordered_index = (
                    ordered_index + 1 if previous_type == block_type else 1
                )
                rendered = f"{ordered_index}. {text}"
            elif block_type == "code-block":
                rendered = f"```\n{text}\n```"
            else:
                rendered = text
        errors.extend(block_errors)
        previous_type = block_type
        if rendered:
            lines.append(rendered)
        else:
            empty_block_count += 1
    markdown = "\n\n".join(lines).strip() or None
    complete = not errors
    return markdown, {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "declared_block_count": len(blocks),
        "rendered_block_count": len(lines),
        "empty_block_count": empty_block_count,
        "errors": errors,
    }


def render_article_markdown(article: dict[str, Any]) -> str | None:
    markdown, _audit = render_article_markdown_audited(article)
    return markdown


def article_projection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    article_id = text_or_none(value.get("id"))
    title = text_or_none(value.get("title"))
    preview = text_or_none(value.get("preview_text"))
    if not any((article_id, title, preview)):
        return None
    cover = None
    cover_media = value.get("cover_media")
    if isinstance(cover_media, dict):
        cover = media_url(cover_media.get("media_info"))
    markdown, render_audit = render_article_markdown_audited(value)
    projected_media = article_media(value)
    render_errors = list(render_audit["errors"])
    for media_index, media in enumerate(projected_media, start=1):
        projection_error = media.get("projection_error")
        if projection_error:
            render_errors.append(
                {
                    "category": "article_media_projection_incomplete",
                    "media_index": media_index,
                    "reason": projection_error,
                }
            )
    render_complete = not render_errors
    render_audit = {
        **render_audit,
        "status": "complete" if render_complete else "incomplete",
        "complete": render_complete,
        "errors": render_errors,
    }
    return {
        "id": article_id,
        "title": title,
        "preview_text": preview,
        "cover_url": cover,
        "body_markdown": markdown,
        "render_complete": render_complete,
        "render_errors": render_errors,
        "render_audit": render_audit,
        "block_count": (
            len(value.get("content", {}).get("blocks", []))
            if isinstance(value.get("content"), dict)
            and isinstance(value.get("content", {}).get("blocks"), list)
            else 0
        ),
        "media": projected_media,
    }


def quote_projection(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") == "tombstone":
        return {
            "availability": text_or_none(value.get("reason")) or "unavailable",
            "id": text_or_none(value.get("id")),
            "url": text_or_none(value.get("url")),
        }
    return {
        "availability": "public",
        "id": text_or_none(value.get("id")),
        "url": canonical_status_url(value),
        "text": text_or_none(value.get("text")),
        "author": author_projection(value.get("author")),
        "article": article_projection(value.get("article")),
    }


def normalize_status(status: dict[str, Any]) -> dict[str, Any]:
    article = article_projection(status.get("article"))
    quote = quote_projection(status.get("quote"))
    content_type = "x_article" if article else "x_quote_post" if quote else "x_post"
    return {
        "content_type": content_type,
        "id": text_or_none(status.get("id")),
        "url": canonical_status_url(status),
        "text": text_or_none(status.get("text")),
        "created_at": text_or_none(status.get("created_at")),
        "lang": text_or_none(status.get("lang")),
        "author": author_projection(status.get("author")),
        "metrics": {
            "likes": number_or_none(status.get("likes")),
            "reposts": number_or_none(status.get("reposts")),
            "quotes": number_or_none(status.get("quotes")),
            "replies": number_or_none(status.get("replies")),
            "bookmarks": number_or_none(status.get("bookmarks")),
            "views": number_or_none(status.get("views")),
        },
        "media": status.get("media") if isinstance(status.get("media"), dict) else None,
        "quote": quote,
        "article": article,
    }


def projected_article_body_complete(normalized: Any) -> bool:
    if not isinstance(normalized, dict):
        return False
    article = normalized.get("article")
    return bool(
        isinstance(article, dict)
        and text_or_none(article.get("body_markdown"))
        and article.get("render_complete") is True
        and isinstance(article.get("render_errors"), list)
        and not article["render_errors"]
    )


def fetch_status(status_id: str, *, timeout: int) -> dict[str, Any]:
    return status_from_payload(fetch_json(f"/status/{status_id}", query=None, timeout=timeout))


def require_status_identity(
    status: dict[str, Any],
    *,
    expected_status_id: str,
    expected_article_id: str | None = None,
) -> None:
    if text_or_none(status.get("id")) != expected_status_id:
        raise KnownUrlError(
            "source_identity_mismatch",
            "The public reader returned a different parent status than requested.",
        )
    if expected_article_id is not None:
        article = status.get("article")
        if (
            not isinstance(article, dict)
            or text_or_none(article.get("id")) != expected_article_id
        ):
            raise KnownUrlError(
                "source_identity_mismatch",
                "The fetched parent status did not contain the requested Article ID.",
            )


def resolve_article(article_id: str, *, timeout: int) -> dict[str, Any]:
    search = fetch_json(
        "/search",
        query={"q": article_id, "feed": "latest", "count": 10},
        timeout=timeout,
    )
    parent = find_article_parent(search.get("results"), article_id)
    if parent is None:
        raise KnownUrlError(
            "article_parent_not_found",
            "The public index did not return an exact parent status for this Article ID.",
        )
    status_id = text_or_none(parent.get("id"))
    if status_id is None:
        raise KnownUrlError(
            "invalid_response",
            "The exact Article match did not contain a parent status ID.",
        )
    resolved = fetch_status(status_id, timeout=timeout)
    require_status_identity(
        resolved,
        expected_status_id=status_id,
        expected_article_id=article_id,
    )
    return resolved


def jina_target_url(status_url: str) -> str:
    parsed = urllib.parse.urlsplit(status_url)
    return f"{JINA_READER}{parsed.path}"


def fetch_jina(status_url: str, *, timeout: int) -> str:
    request = urllib.request.Request(
        jina_target_url(status_url),
        headers={"Accept": "text/markdown", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = read_limited(response, MAX_MARKDOWN_BYTES)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise KnownUrlError("jina_unavailable", "Jina Reader could not read the status.") from exc
    try:
        markdown = body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise KnownUrlError("invalid_response", "Jina Reader returned invalid text.") from exc
    lowered = markdown.lower()
    if not markdown or "log in to x" in lowered or "sign in to x" in lowered:
        raise KnownUrlError("login_wall", "Jina Reader reached an X login page.")
    return markdown


def authenticated_fallbacks(
    parsed: dict[str, str | None],
    status_url: str | None,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    target = status_url or parsed["canonical_url"]
    if (
        parsed["input_kind"] == "x_article_url"
        or content_type == "x_article"
    ):
        opencli_argv = ["opencli", "twitter", "article", target, "-f", "md"]
    else:
        opencli_argv = [
            "opencli",
            "twitter",
            "thread",
            target,
            "--limit",
            "1",
            "-f",
            "json",
        ]
    fallbacks = [
        {
            "backend": "opencli-twitter",
            "argv": opencli_argv,
            "login_state_used": True,
            "requires_current_turn_authorization": True,
        }
    ]
    if status_url or parsed["input_kind"] == "x_status_url":
        fallbacks.append(
            {
                "backend": "xreach",
                "argv": [
                    "xreach",
                    "--cookie-source",
                    "chrome",
                    "--json",
                    "tweet",
                    target,
                ],
                "login_state_used": True,
                "requires_current_turn_authorization": True,
            }
        )
    return fallbacks


def read_known_url(
    value: str,
    *,
    timeout: int,
    allow_jina_fallback: bool,
) -> dict[str, Any]:
    parsed = parse_known_url(value)
    errors: list[dict[str, str]] = []
    status = None
    normalized = None
    backend = None
    jina_markdown = None

    try:
        if parsed["input_kind"] == "x_article_url":
            status = resolve_article(str(parsed["id"]), timeout=timeout)
        else:
            status = fetch_status(str(parsed["id"]), timeout=timeout)
            require_status_identity(
                status, expected_status_id=str(parsed["id"])
            )
        normalized = normalize_status(status)
        backend = "fxtwitter-public"
        is_article = (
            parsed["input_kind"] == "x_article_url"
            or normalized.get("content_type") == "x_article"
        )
        if (
            is_article
            and not projected_article_body_complete(normalized)
        ):
            errors.append(
                {
                    "backend": backend,
                    "category": "article_body_incomplete",
                    "message": "FxTwitter returned the Article parent without a full body.",
                }
            )
    except KnownUrlError as exc:
        errors.append(
            {
                "backend": "fxtwitter-public",
                "category": exc.category,
                "message": exc.message,
            }
        )

    status_url = normalized.get("url") if isinstance(normalized, dict) else None
    content_type = (
        normalized.get("content_type")
        if isinstance(normalized, dict)
        else None
    )
    is_article = (
        parsed["input_kind"] == "x_article_url"
        or content_type == "x_article"
    )
    needs_public_fallback = normalized is None or (
        is_article
        and not projected_article_body_complete(normalized)
    )
    if allow_jina_fallback and needs_public_fallback and status_url:
        try:
            jina_markdown = fetch_jina(status_url, timeout=timeout)
            backend = "jina-reader"
        except KnownUrlError as exc:
            errors.append(
                {
                    "backend": "jina-reader",
                    "category": exc.category,
                    "message": exc.message,
                }
            )
    elif (
        allow_jina_fallback
        and needs_public_fallback
        and parsed["input_kind"] == "x_status_url"
    ):
        try:
            jina_markdown = fetch_jina(str(parsed["canonical_url"]), timeout=timeout)
            backend = "jina-reader"
        except KnownUrlError as exc:
            errors.append(
                {
                    "backend": "jina-reader",
                    "category": exc.category,
                    "message": exc.message,
                }
            )

    success = normalized is not None or jina_markdown is not None
    complete = bool(
        normalized
        and (
            not is_article
            or projected_article_body_complete(normalized)
        )
    ) or bool(jina_markdown)
    return {
        "schema_version": "1.0",
        "status": "success" if complete else "partial" if success else "failed",
        "input": parsed,
        "route": {
            "backend_used": backend,
            "login_state_used": False,
            "discovery_performed": False,
            "retrieved_at": utc_now_iso(),
        },
        "content": normalized,
        "jina_markdown": jina_markdown,
        "authenticated_fallbacks": (
            []
            if complete
            else authenticated_fallbacks(parsed, status_url, content_type)
        ),
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read one known public X status or Article URL anonymously."
    )
    parser.add_argument("url")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-jina-fallback", action="store_true")
    args = parser.parse_args()
    if not 5 <= args.timeout <= 60:
        parser.error("--timeout must be between 5 and 60 seconds")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = read_known_url(
            args.url,
            timeout=args.timeout,
            allow_jina_fallback=not args.no_jina_fallback,
        )
    except KnownUrlError as exc:
        result = {
            "schema_version": "1.0",
            "status": "failed",
            "input": None,
            "route": {
                "backend_used": None,
                "login_state_used": False,
                "discovery_performed": False,
                "retrieved_at": utc_now_iso(),
            },
            "content": None,
            "jina_markdown": None,
            "authenticated_fallbacks": [],
            "errors": [
                {
                    "backend": None,
                    "category": exc.category,
                    "message": exc.message,
                }
            ],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
