#!/usr/bin/env python3
"""Bounded Firecrawl v2 Map preflight and explicitly authorized site archive.

The default invocation only calls Map and writes a signed, short-lived
preflight.  Crawl is unreachable unless ``--execute`` is paired with that
preflight and every scope parameter and referenced artifact still matches.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

try:
    import idna as _idna_candidate
except ImportError:  # pragma: no cover - exercised by patching IDNA_UTS46.
    IDNA_UTS46 = None
else:
    try:
        _idna_major = int(_idna_candidate.__version__.split(".", 1)[0])
    except (AttributeError, TypeError, ValueError):
        _idna_major = 0
    IDNA_UTS46 = _idna_candidate if _idna_major == 3 else None


API_BASE = "https://api.firecrawl.dev/v2"
API_HOST = "api.firecrawl.dev"
API_KEY_ENV = "FIRECRAWL_API_KEY"
API_KEY_FILE = Path.home() / ".config" / "agent-secrets" / "firecrawl-api-key"
PREFLIGHT_VERSION = "yichen-firecrawl-site-preflight/v1"
PREFLIGHT_TTL_SECONDS = 2 * 60 * 60
MAX_LIMIT = 100
MAX_DEPTH = 3
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PREFLIGHT_BYTES = 2 * 1024 * 1024
MAX_MARKDOWN_BYTES = 5 * 1024 * 1024
MAX_PATH_DECODE_ROUNDS = 12
DEFAULT_OUTPUT_ROOT = Path.home() / "Documents" / "content-archive" / "firecrawl-sites"
SIGNING_CONTEXT = b"yichen-content-archive/firecrawl-preflight/v1"
SPECIAL_USE_DNS_SUFFIXES = (
    "localhost",
    "local",
    "localdomain",
    "internal",
    "test",
    "invalid",
    "example",
    "home.arpa",
    "onion",
    "alt",
)


class SiteError(RuntimeError):
    """A safe error whose message contains no credential or response body."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class Scope:
    site_url: str
    origin: str
    path_prefix: str
    limit: int
    max_depth: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SiteError("invalid_preflight", f"{label} is missing.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise SiteError("invalid_preflight", f"{label} is invalid.") from None
    if parsed.tzinfo is None:
        raise SiteError("invalid_preflight", f"{label} needs a timezone.")
    return parsed.astimezone(timezone.utc)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exclusive_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise SiteError("invalid_preflight", "A required preflight file could not be read.") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SiteError("invalid_preflight", "A required preflight path is not a regular file.")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise SiteError("invalid_preflight", "A required preflight file is too large.")
        return data
    finally:
        os.close(descriptor)


def _load_api_key(environ: dict[str, str] | None = None) -> bytes:
    environment = os.environ if environ is None else environ
    inline = environment.get(API_KEY_ENV)
    if inline is not None:
        raw = inline.strip().encode("utf-8")
    else:
        path = API_KEY_FILE
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path.expanduser(), flags)
        except OSError:
            raise SiteError(
                "missing_api_key",
                "Firecrawl API key is unavailable in the environment or private key file.",
            ) from None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise SiteError(
                    "unsafe_api_key_file",
                    "Firecrawl API key file must be a private regular file.",
                )
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise SiteError(
                    "unsafe_api_key_file",
                    "Firecrawl API key file must be owned by the current user.",
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(4097).strip()
        finally:
            os.close(descriptor)
    if not raw or len(raw) > 4096 or any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise SiteError("invalid_api_key", "Firecrawl API key is empty or invalid.")
    return raw


def _signing_key(api_key: bytes) -> bytes:
    return hmac.new(api_key, SIGNING_CONTEXT, hashlib.sha256).digest()


def _whatwg_ipv4_number(value: str) -> int | None:
    """Parse one WHATWG-style IPv4 number without doing DNS resolution."""

    raw = value.lower()
    radix = 10
    digits = raw
    if raw.startswith("0x"):
        radix = 16
        digits = raw[2:]
        if not digits or not re.fullmatch(r"[0-9a-f]+", digits):
            return None
    elif len(raw) >= 2 and raw.startswith("0"):
        radix = 8
        digits = raw[1:] or "0"
        if not re.fullmatch(r"[0-7]+", digits):
            return None
    elif not re.fullmatch(r"[0-9]+", digits):
        return None
    try:
        return int(digits, radix)
    except ValueError:
        return None


def _whatwg_ipv4(host: str) -> tuple[bool, ipaddress.IPv4Address | None]:
    """Return whether a host is numeric-looking and its legacy IPv4 value.

    Browsers accept shortened, octal, hexadecimal, and mixed-radix IPv4 forms.
    Those representations must not bypass the public-address gate merely because
    ``ipaddress.ip_address`` only accepts canonical text.
    """

    parts = host.split(".")
    if parts and parts[-1] == "":
        parts.pop()
    if not parts:
        return False, None
    last = parts[-1].lower()
    numeric_ending = bool(
        re.fullmatch(r"[0-9]+", last)
        or re.fullmatch(r"0x[0-9a-f]*", last)
    )
    if not numeric_ending:
        return False, None
    if len(parts) > 4:
        return True, None
    numbers = [_whatwg_ipv4_number(part) for part in parts]
    if any(number is None for number in numbers):
        return True, None
    parsed_numbers = [int(number) for number in numbers if number is not None]
    if any(number > 255 for number in parsed_numbers[:-1]):
        return True, None
    last_limit = 256 ** (5 - len(parsed_numbers))
    if parsed_numbers[-1] >= last_limit:
        return True, None
    numeric_value = parsed_numbers[-1]
    for index, number in enumerate(parsed_numbers[:-1]):
        numeric_value += number * (256 ** (3 - index))
    try:
        return True, ipaddress.IPv4Address(numeric_value)
    except ipaddress.AddressValueError:
        return True, None


def _public_host(hostname: str) -> str:
    raw_host = hostname.rstrip(".")
    if (
        not raw_host
        or "%" in raw_host
        or "\\" in raw_host
        or "/" in raw_host
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in raw_host)
    ):
        raise SiteError("invalid_scope", "Site hostname is invalid.")

    # Parse literal IPv4/IPv6 before applying domain-name mappings.  This also
    # keeps scoped IPv6 literals and other percent-bearing forms out.
    try:
        literal_address = ipaddress.ip_address(raw_host)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        if not literal_address.is_global:
            raise SiteError("invalid_scope", "Site must use a public HTTPS host.")
        return literal_address.compressed.lower()

    if IDNA_UTS46 is None:
        if not raw_host.isascii():
            raise SiteError(
                "invalid_scope",
                "Internationalized hostnames require IDNA 3.x UTS46 support.",
            )
        host = raw_host.lower()
    else:
        try:
            host = IDNA_UTS46.encode(
                raw_host,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").lower()
        except (IDNA_UTS46.IDNAError, UnicodeError):
            raise SiteError("invalid_scope", "Site hostname is invalid.") from None
    if len(host) > 253:
        raise SiteError("invalid_scope", "Site hostname is invalid.")

    # UTS46 may map Unicode digits and separators to an IP-looking ASCII host.
    # Re-run the literal gate so e.g. fullwidth loopback cannot become public.
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise SiteError("invalid_scope", "Site must use a public HTTPS host.")
        return address.compressed.lower()

    numeric_ending, legacy_address = _whatwg_ipv4(host)
    if numeric_ending:
        if legacy_address is not None and not legacy_address.is_global:
            raise SiteError("invalid_scope", "Site must use a public HTTPS host.")
        raise SiteError("invalid_scope", "Site hostname uses an ambiguous IPv4 form.")

    labels = host.split(".")
    if len(labels) < 2 or any(
        len(label) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise SiteError("invalid_scope", "Site hostname is not a public DNS name.")
    if any(host == suffix or host.endswith("." + suffix) for suffix in SPECIAL_USE_DNS_SUFFIXES):
        raise SiteError("invalid_scope", "Site must use a public HTTPS host.")
    return host


def _decode_policy_path(value: str, label: str) -> str:
    decoded = value
    for _ in range(MAX_PATH_DECODE_ROUNDS):
        if re.search(r"%(?![0-9A-Fa-f]{2})", decoded):
            raise SiteError("invalid_scope", f"{label} contains malformed percent encoding.")
        if re.search(r"%(?:2f|5c)", decoded, re.IGNORECASE):
            raise SiteError("invalid_scope", f"{label} contains an encoded path separator.")
        try:
            expanded = unquote(decoded, encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            raise SiteError("invalid_scope", f"{label} contains invalid encoding.") from None
        if expanded == decoded:
            break
        decoded = expanded
    else:
        raise SiteError("invalid_scope", f"{label} is encoded too deeply.")
    if re.search(r"%(?:2f|5c)", decoded, re.IGNORECASE):
        raise SiteError("invalid_scope", f"{label} contains an encoded path separator.")
    if "%" in decoded or "\\" in decoded or "\x00" in decoded:
        raise SiteError("invalid_scope", f"{label} contains an unsafe path.")
    return decoded


def _policy_path(raw: str, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SiteError("invalid_scope", f"{label} must not be empty.")
    value = raw
    if not value.startswith("/") or "?" in value or "#" in value:
        raise SiteError("invalid_scope", f"{label} must be an absolute URL path.")
    decoded = _decode_policy_path(value, label)
    segments = decoded.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise SiteError("invalid_scope", f"{label} contains dot segments.")
    normalized = "/" + "/".join(segment for segment in segments if segment)
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def _origin_parts(parsed: Any) -> tuple[str, str]:
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise SiteError("invalid_scope", "Site must use public HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise SiteError("invalid_scope", "Site URL must not contain user information.")
    try:
        port = parsed.port
    except ValueError:
        raise SiteError("invalid_scope", "Site URL port is invalid.") from None
    if port is not None and not 1 <= port <= 65535:
        raise SiteError("invalid_scope", "Site URL port is invalid.")
    host = _public_host(parsed.hostname)
    if ":" in host:
        display_host = f"[{host}]"
    else:
        display_host = host
    netloc = display_host if port in {None, 443} else f"{display_host}:{port}"
    return host, f"https://{netloc}"


def make_scope(site_url: str, path_prefix: str, limit: int, max_depth: int) -> Scope:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise SiteError("invalid_scope", "limit must be between 1 and 100.")
    if isinstance(max_depth, bool) or not 0 <= max_depth <= MAX_DEPTH:
        raise SiteError("invalid_scope", "max-depth must be between 0 and 3.")
    try:
        parsed = urlsplit(site_url.strip())
    except (AttributeError, ValueError):
        raise SiteError("invalid_scope", "site-url is invalid.") from None
    if parsed.query or parsed.fragment:
        raise SiteError("invalid_scope", "site-url must not contain a query or fragment.")
    _, origin = _origin_parts(parsed)
    prefix = _policy_path(path_prefix, "path-prefix")
    if prefix == "/" and path_prefix != "/":
        raise SiteError(
            "invalid_scope",
            "Only an explicit '/' path-prefix may authorize the whole site.",
        )
    seed_path = _policy_path(parsed.path or "/", "site-url path")
    if not _path_allowed(seed_path, prefix):
        raise SiteError("invalid_scope", "site-url path must be inside path-prefix.")
    encoded_path = quote(seed_path, safe="/~:@!$&'()*+,;=-._")
    return Scope(
        site_url=f"{origin}{encoded_path}",
        origin=origin,
        path_prefix=prefix,
        limit=limit,
        max_depth=max_depth,
    )


def _path_allowed(path: str, prefix: str) -> bool:
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


def normalize_scoped_url(value: Any, scope: Scope) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SiteError("outside_scope", "Returned URL is missing.")
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        raise SiteError("outside_scope", "Returned URL is invalid.") from None
    try:
        _, origin = _origin_parts(parsed)
    except SiteError:
        raise SiteError("outside_scope", "Returned URL is outside the approved origin.") from None
    if origin != scope.origin:
        raise SiteError("outside_scope", "Returned URL is outside the approved origin.")
    try:
        path = _policy_path(parsed.path or "/", "returned URL path")
    except SiteError:
        raise SiteError("outside_scope", "Returned URL is outside path-prefix.") from None
    if not _path_allowed(path, scope.path_prefix):
        raise SiteError("outside_scope", "Returned URL is outside path-prefix.")
    encoded_path = quote(path, safe="/~:@!$&'()*+,;=-._")
    return f"{origin}{encoded_path}"


def _fixed_policy(scope: Scope) -> dict[str, Any]:
    prefix_pattern = (
        r"^/.*$"
        if scope.path_prefix == "/"
        else "^" + re.escape(scope.path_prefix) + r"(?:/.*)?$"
    )
    return {
        "api_base": API_BASE,
        "map": {
            "includeSubdomains": False,
            "ignoreQueryParameters": True,
        },
        "crawl": {
            "allowSubdomains": False,
            "allowExternalLinks": False,
            "ignoreQueryParameters": True,
            "ignoreRobotsTxt": False,
            "crawlEntireDomain": False,
            "includePaths": [prefix_pattern],
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True,
                "skipTlsVerification": False,
                "proxy": "basic",
                "storeInCache": False,
            },
        },
    }


def _scope_request(scope: Scope) -> dict[str, Any]:
    return {
        "site_url": scope.site_url,
        "path_prefix": scope.path_prefix,
        "limit": scope.limit,
        "max_depth": scope.max_depth,
    }


def _quota_exposure(scope: Scope) -> dict[str, Any]:
    return {
        "map_requests": 1,
        "crawl_page_cap": scope.limit,
        "pricing_must_be_rechecked": True,
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the bearer credential never crosses an origin."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _validate_api_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise SiteError("unsafe_pagination", "Firecrawl request left the fixed v2 API.") from None
    try:
        decoded_path = _decode_policy_path(parsed.path or "/", "Firecrawl API path")
    except SiteError:
        raise SiteError("unsafe_pagination", "Firecrawl request left the fixed v2 API.") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != API_HOST
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith("/v2/")
        or "\\" in parsed.path
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise SiteError("unsafe_pagination", "Firecrawl request left the fixed v2 API.")


class FirecrawlClient:
    def __init__(self, api_key: bytes, timeout: int = 30, opener: Any | None = None):
        self._api_key = api_key.decode("ascii")
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _validate_api_url(url)
        data = None if payload is None else _canonical_json(payload)
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.geturl() != url:
                    raise SiteError(
                        "firecrawl_redirect_refused",
                        "Firecrawl API attempted to redirect the authenticated request.",
                    )
                raw = response.read(MAX_JSON_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise SiteError(
                    "firecrawl_redirect_refused",
                    "Firecrawl API attempted to redirect the authenticated request.",
                ) from None
            raise SiteError("firecrawl_http_error", f"Firecrawl API returned HTTP {exc.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SiteError("firecrawl_unavailable", "Firecrawl API could not be reached.") from None
        if len(raw) > MAX_JSON_BYTES:
            raise SiteError("firecrawl_response_too_large", "Firecrawl response exceeded the safe size limit.")
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SiteError("firecrawl_invalid_response", "Firecrawl returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise SiteError("firecrawl_invalid_response", "Firecrawl returned an invalid object.")
        if result.get("success") is False:
            raise SiteError("firecrawl_rejected", "Firecrawl rejected the request.")
        return result

    def map_site(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", API_BASE + "/map", payload)

    def start_crawl(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", API_BASE + "/crawl", payload)

    def crawl_status(self, job_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", job_id):
            raise SiteError("firecrawl_invalid_response", "Firecrawl returned an invalid crawl job ID.")
        return self._request("GET", API_BASE + "/crawl/" + job_id)

    def next_page(self, url: str) -> dict[str, Any]:
        _validate_api_url(url)
        parsed = urlsplit(url)
        if (
            not parsed.path.startswith("/v2/crawl/")
        ):
            raise SiteError("unsafe_pagination", "Firecrawl pagination URL left the fixed v2 crawl API.")
        return self._request("GET", url)


def _new_run_dir(output_root: Path, mode: str, now: datetime) -> Path:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir() or root.is_symlink():
        raise SiteError("unsafe_output", "Output root must be a real directory.")
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(100):
        path = root / f"firecrawl-{mode}-{stamp}-{secrets.token_hex(4)}"
        try:
            path.mkdir(mode=0o700)
            return path
        except FileExistsError:
            continue
    raise SiteError("output_conflict", "Could not allocate a new output directory.")


def _map_payload(scope: Scope) -> dict[str, Any]:
    return {
        "url": scope.site_url,
        "limit": scope.limit,
        "includeSubdomains": False,
        "ignoreQueryParameters": True,
    }


def _crawl_payload(scope: Scope) -> dict[str, Any]:
    policy = _fixed_policy(scope)["crawl"]
    return {
        "url": scope.site_url,
        "limit": scope.limit,
        "maxDiscoveryDepth": scope.max_depth,
        "allowSubdomains": policy["allowSubdomains"],
        "allowExternalLinks": policy["allowExternalLinks"],
        "ignoreQueryParameters": policy["ignoreQueryParameters"],
        "ignoreRobotsTxt": policy["ignoreRobotsTxt"],
        "crawlEntireDomain": policy["crawlEntireDomain"],
        "includePaths": policy["includePaths"],
        "scrapeOptions": policy["scrapeOptions"],
    }


def _extract_map_links(response: dict[str, Any]) -> list[Any]:
    links = response.get("links")
    if links is None and isinstance(response.get("data"), dict):
        links = response["data"].get("links")
    if not isinstance(links, list):
        raise SiteError("firecrawl_invalid_response", "Firecrawl Map response did not contain a links list.")
    return links


def _filter_map(response: dict[str, Any], scope: Scope) -> tuple[list[str], list[dict[str, Any]], int]:
    raw_links = _extract_map_links(response)
    accepted: list[str] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_links, start=1):
        value = item.get("url") if isinstance(item, dict) else item
        try:
            normalized = normalize_scoped_url(value, scope)
        except SiteError as exc:
            rejected.append({"item_ref": f"map:{index}", "reason": exc.category})
            continue
        if normalized in seen:
            rejected.append({"item_ref": f"map:{index}", "reason": "duplicate"})
            continue
        seen.add(normalized)
        if len(accepted) < scope.limit:
            accepted.append(normalized)
        else:
            rejected.append({"item_ref": f"map:{index}", "reason": "over_limit"})
    return accepted, rejected, len(raw_links)


def _map_audit(
    scope: Scope,
    *,
    returned_count: int,
    accepted_count: int,
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe Map coverage without claiming exhaustive enumeration."""

    filtered_count = sum(row.get("reason") != "over_limit" for row in rejected)
    return {
        "returned_count": returned_count,
        "accepted_count": accepted_count,
        "filtered_count": filtered_count,
        "rejected_count": len(rejected),
        "cap_reached": returned_count >= scope.limit,
        "completeness": "unknown",
    }


def _preflight_signature(payload: dict[str, Any], signing_key: bytes) -> str:
    digest = hmac.new(signing_key, _canonical_json(payload), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _write_map_failure(
    *,
    run_dir: Path,
    scope: Scope,
    error: SiteError,
    status: str = "failed",
    map_path: Path | None = None,
    map_bytes: bytes | None = None,
    list_path: Path | None = None,
    list_bytes: bytes | None = None,
    returned_count: int = 0,
    accepted_count: int = 0,
    filtered_count: int = 0,
    rejected_count: int = 0,
    cap_reached: bool = False,
) -> dict[str, Any]:
    if status not in {"failed", "empty"}:
        raise SiteError("internal_error", "Map terminal status is invalid.")
    artifact_values = (map_path, map_bytes, list_path, list_bytes)
    if any(value is None for value in artifact_values) and any(
        value is not None for value in artifact_values
    ):
        raise SiteError("internal_error", "Map terminal artifacts are incomplete.")
    artifacts: dict[str, Any] = {}
    if map_path is not None and map_bytes is not None and list_path is not None and list_bytes is not None:
        _exclusive_write(map_path, map_bytes)
        _exclusive_write(list_path, list_bytes)
        artifacts.update(
            {
                "site_map": {"path": str(map_path), "sha256": _sha256(map_bytes)},
                "enumerated_url_list": {
                    "path": str(list_path),
                    "sha256": _sha256(list_bytes),
                },
            }
        )
    failures = [{"item_ref": "bounded-site", "stage": "map", "reason": error.category}]
    failures_bytes = _canonical_json(failures) + b"\n"
    failures_path = run_dir / "failures.json"
    _exclusive_write(failures_path, failures_bytes)
    summary = {
        "schema_version": "yichen-firecrawl-site-map-run/v1",
        "status": status,
        "mode": "map_preflight",
        "backend": "firecrawl-v2-map",
        "request": _scope_request(scope),
        "counts": {
            "map_requests": 1,
            "returned": returned_count,
            "accepted": accepted_count,
            "enumerated": accepted_count,
            "filtered": filtered_count,
            "rejected": rejected_count,
            "failed": 1,
        },
        "cap_reached": cap_reached,
        "completeness": "unknown",
        "failure": {"category": error.category},
        "failures": failures,
        "policy": _fixed_policy(scope),
        "quota_exposure": _quota_exposure(scope),
        "artifacts": artifacts,
    }
    summary["artifacts"]["failures"] = {
        "path": str(failures_path),
        "sha256": _sha256(failures_bytes),
    }
    summary_bytes = _canonical_json(summary) + b"\n"
    summary_path = run_dir / "run-summary.json"
    _exclusive_write(summary_path, summary_bytes)
    result = {
        "status": status,
        "mode": "map_preflight",
        "run_dir": str(run_dir),
        "run_summary": str(summary_path),
        "failures": str(failures_path),
        "quota_exposure": _quota_exposure(scope),
        "error": {"category": error.category, "message": error.message},
    }
    if map_path is not None and list_path is not None:
        result["site_map"] = str(map_path)
        result["enumerated_urls"] = str(list_path)
    return result


def run_preflight(
    scope: Scope,
    *,
    client: Any,
    api_key: bytes,
    output_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc_now() if now is None else now.astimezone(timezone.utc)
    run_dir = _new_run_dir(output_root, "map", current)
    try:
        response = client.map_site(_map_payload(scope))
        urls, rejected, returned_count = _filter_map(response, scope)
    except SiteError as exc:
        return _write_map_failure(run_dir=run_dir, scope=scope, error=exc)

    map_audit = _map_audit(
        scope,
        returned_count=returned_count,
        accepted_count=len(urls),
        rejected=rejected,
    )
    site_map = {
        "schema_version": "yichen-firecrawl-site-map/v1",
        "backend": "firecrawl-v2-map",
        "site_url": scope.site_url,
        "path_prefix": scope.path_prefix,
        **map_audit,
        "links": urls,
        "rejections": rejected,
    }
    map_bytes = _canonical_json(site_map) + b"\n"
    list_bytes = (("\n".join(urls) + "\n") if urls else "").encode("utf-8")
    map_path = run_dir / "site-map.json"
    list_path = run_dir / "enumerated-urls.txt"
    if len(map_bytes) > MAX_PREFLIGHT_BYTES or len(list_bytes) > MAX_PREFLIGHT_BYTES:
        return _write_map_failure(
            run_dir=run_dir,
            scope=scope,
            error=SiteError(
                "preflight_artifact_too_large",
                "Map artifacts exceeded the signed preflight size limit.",
            ),
            returned_count=map_audit["returned_count"],
            accepted_count=map_audit["accepted_count"],
            filtered_count=map_audit["filtered_count"],
            rejected_count=map_audit["rejected_count"],
            cap_reached=map_audit["cap_reached"],
        )
    if not urls:
        return _write_map_failure(
            run_dir=run_dir,
            scope=scope,
            error=SiteError(
                "empty_map",
                "Map returned no in-scope URLs; no executable preflight was created.",
            ),
            status="empty",
            map_path=map_path,
            map_bytes=map_bytes,
            list_path=list_path,
            list_bytes=list_bytes,
            returned_count=map_audit["returned_count"],
            accepted_count=map_audit["accepted_count"],
            filtered_count=map_audit["filtered_count"],
            rejected_count=map_audit["rejected_count"],
            cap_reached=map_audit["cap_reached"],
        )

    payload = {
        "schema_version": PREFLIGHT_VERSION,
        "run_id": secrets.token_hex(16),
        "created_at": _timestamp(current),
        "expires_at": _timestamp(current + timedelta(seconds=PREFLIGHT_TTL_SECONDS)),
        "backend": "firecrawl-v2",
        "mode": "map_preflight",
        "request": _scope_request(scope),
        "policy": _fixed_policy(scope),
        "quota_exposure": _quota_exposure(scope),
        "map_summary": {
            **map_audit,
            "enumerated_count": len(urls),
        },
        "artifacts": {
            "run_dir": str(run_dir),
            "site_map": {"path": str(map_path), "sha256": _sha256(map_bytes)},
            "enumerated_urls": {"path": str(list_path), "sha256": _sha256(list_bytes)},
        },
        "limitations": [
            "Map is a bounded preflight, not proof that the site was exhaustively enumerated.",
            "storeInCache=false is required for Crawl but is not a claim of absolute zero data retention.",
        ],
    }
    preflight = {
        **payload,
        "receipt": {
            "algorithm": "HMAC-SHA256",
            "key_derivation": "firecrawl-api-key-context-v1",
            "signature": _preflight_signature(payload, _signing_key(api_key)),
        },
    }
    preflight_path = run_dir / "preflight.json"
    preflight_bytes = _canonical_json(preflight) + b"\n"
    if len(preflight_bytes) > MAX_PREFLIGHT_BYTES:
        return _write_map_failure(
            run_dir=run_dir,
            scope=scope,
            error=SiteError(
                "preflight_artifact_too_large",
                "Preflight exceeded the executable size limit.",
            ),
            returned_count=map_audit["returned_count"],
            accepted_count=map_audit["accepted_count"],
            filtered_count=map_audit["filtered_count"],
            rejected_count=map_audit["rejected_count"],
            cap_reached=map_audit["cap_reached"],
        )
    _exclusive_write(map_path, map_bytes)
    _exclusive_write(list_path, list_bytes)
    _exclusive_write(preflight_path, preflight_bytes)
    failures: list[dict[str, Any]] = []
    failures_bytes = _canonical_json(failures) + b"\n"
    failures_path = run_dir / "failures.json"
    _exclusive_write(failures_path, failures_bytes)
    summary = {
        "schema_version": "yichen-firecrawl-site-map-run/v1",
        "status": "preflight_ready",
        "mode": "map_preflight",
        "backend": "firecrawl-v2-map",
        "request": _scope_request(scope),
        "counts": {
            "map_requests": 1,
            "returned": map_audit["returned_count"],
            "accepted": map_audit["accepted_count"],
            "enumerated": len(urls),
            "filtered": map_audit["filtered_count"],
            "rejected": map_audit["rejected_count"],
            "failed": 0,
        },
        "cap_reached": map_audit["cap_reached"],
        "completeness": map_audit["completeness"],
        "policy": _fixed_policy(scope),
        "quota_exposure": _quota_exposure(scope),
        "artifacts": {
            "preflight": {"path": str(preflight_path), "sha256": _sha256(preflight_bytes)},
            "site_map": {"path": str(map_path), "sha256": _sha256(map_bytes)},
            "enumerated_url_list": {"path": str(list_path), "sha256": _sha256(list_bytes)},
            "failures": {"path": str(failures_path), "sha256": _sha256(failures_bytes)},
        },
    }
    summary_bytes = _canonical_json(summary) + b"\n"
    summary_path = run_dir / "run-summary.json"
    _exclusive_write(summary_path, summary_bytes)
    return {
        "status": "preflight_ready",
        "mode": "map_preflight",
        "run_dir": str(run_dir),
        "preflight": str(preflight_path),
        "site_map": str(map_path),
        "enumerated_urls": str(list_path),
        "run_summary": str(summary_path),
        "failures": str(failures_path),
        "enumerated_count": len(urls),
        "expires_at": preflight["expires_at"],
        "quota_exposure": _quota_exposure(scope),
    }


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _load_verified_preflight(
    path: Path,
    *,
    scope: Scope,
    api_key: bytes,
    now: datetime,
) -> tuple[dict[str, Any], bytes, bytes, bytes, list[str]]:
    preflight_bytes = _read_regular(path.expanduser(), MAX_PREFLIGHT_BYTES)
    try:
        preflight = json.loads(preflight_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SiteError("invalid_preflight", "Preflight is not valid JSON.") from None
    if not isinstance(preflight, dict) or preflight.get("schema_version") != PREFLIGHT_VERSION:
        raise SiteError("invalid_preflight", "Preflight schema is unsupported.")
    receipt = preflight.get("receipt")
    if not isinstance(receipt, dict) or set(receipt) != {
        "algorithm", "key_derivation", "signature"
    }:
        raise SiteError("invalid_preflight", "Preflight receipt is missing or invalid.")
    if receipt.get("algorithm") != "HMAC-SHA256" or receipt.get("key_derivation") != "firecrawl-api-key-context-v1":
        raise SiteError("invalid_preflight", "Preflight receipt policy is invalid.")
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", signature):
        raise SiteError("invalid_preflight", "Preflight signature is invalid.")
    payload = dict(preflight)
    payload.pop("receipt", None)
    expected = _preflight_signature(payload, _signing_key(api_key))
    if not hmac.compare_digest(signature, expected):
        raise SiteError("invalid_preflight", "Preflight signature does not match its content.")
    created = _parse_timestamp(preflight.get("created_at"), "Preflight creation time")
    expires = _parse_timestamp(preflight.get("expires_at"), "Preflight expiration")
    if expires <= created or expires > created + timedelta(seconds=PREFLIGHT_TTL_SECONDS):
        raise SiteError("invalid_preflight", "Preflight lifetime is invalid.")
    if now.astimezone(timezone.utc) >= expires:
        raise SiteError("expired_preflight", "Preflight has expired; run Map again.")
    if (
        preflight.get("request") != _scope_request(scope)
        or preflight.get("policy") != _fixed_policy(scope)
        or preflight.get("quota_exposure") != _quota_exposure(scope)
    ):
        raise SiteError("scope_mismatch", "Execute parameters do not match the signed preflight.")

    artifacts = preflight.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SiteError("invalid_preflight", "Preflight artifacts are missing.")
    try:
        source_run = Path(artifacts["run_dir"]).resolve(strict=True)
        map_path = Path(artifacts["site_map"]["path"]).resolve(strict=True)
        list_path = Path(artifacts["enumerated_urls"]["path"]).resolve(strict=True)
        map_hash = artifacts["site_map"]["sha256"]
        list_hash = artifacts["enumerated_urls"]["sha256"]
    except (KeyError, TypeError, OSError):
        raise SiteError("invalid_preflight", "Preflight artifact references are invalid.") from None
    if not _inside(map_path, source_run) or not _inside(list_path, source_run):
        raise SiteError("invalid_preflight", "Preflight artifacts escaped their source run.")
    map_bytes = _read_regular(map_path, MAX_PREFLIGHT_BYTES)
    list_bytes = _read_regular(list_path, MAX_PREFLIGHT_BYTES)
    if not hmac.compare_digest(_sha256(map_bytes), str(map_hash)) or not hmac.compare_digest(_sha256(list_bytes), str(list_hash)):
        raise SiteError("invalid_preflight", "Preflight artifact content has changed.")
    try:
        site_map = json.loads(map_bytes)
        urls = [line.strip() for line in list_bytes.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SiteError("invalid_preflight", "Preflight artifacts are malformed.") from None
    if not isinstance(site_map, dict) or site_map.get("links") != urls or len(urls) != len(set(urls)):
        raise SiteError("invalid_preflight", "Preflight URL artifacts disagree.")
    if preflight.get("map_summary", {}).get("enumerated_count") != len(urls):
        raise SiteError("invalid_preflight", "Preflight URL count has changed.")
    for url in urls:
        if normalize_scoped_url(url, scope) != url:
            raise SiteError("invalid_preflight", "Preflight contains an out-of-scope URL.")
    if not urls:
        raise SiteError("empty_preflight", "Preflight contains no approved URLs to archive.")
    return preflight, preflight_bytes, map_bytes, list_bytes, urls


def _collect_crawl(
    client: Any,
    payload: dict[str, Any],
    *,
    timeout: int,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, list[Any]]:
    started = client.start_crawl(payload)
    job_id = started.get("id") if isinstance(started, dict) else None
    if not isinstance(job_id, str) or not job_id:
        raise SiteError("firecrawl_invalid_response", "Firecrawl did not return a crawl job ID.")
    deadline = time.monotonic() + timeout
    while True:
        status = client.crawl_status(job_id)
        state = str(status.get("status", "")).lower()
        if state == "completed":
            documents = status.get("data", [])
            if not isinstance(documents, list):
                raise SiteError("firecrawl_invalid_response", "Completed Crawl data is not a list.")
            maximum_documents = int(payload["limit"])
            if len(documents) > maximum_documents:
                raise SiteError("firecrawl_invalid_response", "Crawl returned more documents than the signed limit.")
            next_url = status.get("next")
            visited: set[str] = set()
            while (
                len(documents) < maximum_documents
                and isinstance(next_url, str)
                and next_url
                and next_url not in visited
            ):
                visited.add(next_url)
                page = client.next_page(next_url)
                extra = page.get("data", [])
                if not isinstance(extra, list):
                    raise SiteError("firecrawl_invalid_response", "Crawl pagination data is invalid.")
                documents.extend(extra)
                if len(documents) > maximum_documents:
                    raise SiteError("firecrawl_invalid_response", "Crawl pagination exceeded the signed limit.")
                next_url = page.get("next")
                if len(visited) >= 20:
                    raise SiteError("firecrawl_invalid_response", "Crawl pagination exceeded the safe bound.")
            return job_id, documents
        if state in {"failed", "cancelled"}:
            raise SiteError("firecrawl_crawl_failed", "Firecrawl Crawl did not complete.")
        if time.monotonic() >= deadline:
            raise SiteError("firecrawl_timeout", "Firecrawl Crawl did not finish before the timeout.")
        sleep(poll_seconds)


def _document_url(item: Any) -> Any:
    if not isinstance(item, dict):
        return None
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in ("sourceURL", "sourceUrl", "url"):
            if metadata.get(key):
                return metadata[key]
    return item.get("url")


def _safe_metadata(item: dict[str, Any], url: str) -> dict[str, Any]:
    source = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    result: dict[str, Any] = {"source_url": url}
    for key in ("title", "description", "language", "statusCode"):
        value = source.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            result[key] = value
    return result


def _write_execute_result(
    *,
    run_dir: Path,
    scope: Scope,
    urls: list[str],
    documents: list[Any],
    job_id: str | None,
    crawl_error: SiteError | None,
    now: datetime,
    preflight_audit: dict[str, Any],
) -> dict[str, Any]:
    web_root = run_dir / "web"
    web_root.mkdir(mode=0o700)
    approved = set(urls)
    accepted: dict[str, list[str]] = {}
    rejected_by_url: dict[str, str] = {}
    rejected_documents: list[dict[str, Any]] = []
    for index, item in enumerate(documents, start=1):
        try:
            url = normalize_scoped_url(_document_url(item), scope)
        except SiteError as exc:
            rejected_documents.append({"item_ref": f"crawl:{index}", "reason": exc.category})
            continue
        if url not in approved:
            rejected_documents.append({"item_ref": f"crawl:{index}", "reason": "not_in_signed_preflight"})
            continue
        if url in accepted:
            rejected_documents.append({"item_ref": f"crawl:{index}", "reason": "duplicate"})
            continue
        markdown = item.get("markdown") if isinstance(item, dict) else None
        if not isinstance(markdown, str) or not markdown.strip():
            rejected_documents.append({"item_ref": f"crawl:{index}", "reason": "missing_markdown"})
            rejected_by_url.setdefault(url, "missing_markdown")
            continue
        content_bytes = markdown.encode("utf-8")
        if len(content_bytes) > MAX_MARKDOWN_BYTES:
            rejected_documents.append({"item_ref": f"crawl:{index}", "reason": "page_too_large"})
            rejected_by_url.setdefault(url, "page_too_large")
            continue
        item_dir = web_root / f"{len(accepted) + 1:04d}-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
        item_dir.mkdir(mode=0o700)
        content_path = item_dir / "content.md"
        metadata_path = item_dir / "metadata.json"
        _exclusive_write(content_path, content_bytes)
        _exclusive_write(metadata_path, _canonical_json(_safe_metadata(item, url)) + b"\n")
        accepted[url] = [str(content_path), str(metadata_path)]

    manifest_lines: list[bytes] = []
    failures: list[dict[str, Any]] = []
    fetched_at = _timestamp(now)
    for position, url in enumerate(urls, start=1):
        success = url in accepted and crawl_error is None
        reason = (
            None
            if success
            else (
                crawl_error.category
                if crawl_error
                else rejected_by_url.get(url, "not_returned_by_crawl")
            )
        )
        row = {
            "item_ref": f"site-map:{position}",
            "platform": "web",
            "source_url_ref": f"enumerated-urls.txt:{position}",
            "container_ref": scope.site_url,
            "container_position": position,
            "enumeration_status": "signed_preflight",
            "requested_actions": ["archive"],
            "status": "success" if success else "failed",
            "artifact_paths": accepted.get(url, []),
            "route_backend": "firecrawl-v2-bounded-site",
            "fetched_at": fetched_at,
            "reason": reason,
            "error_category": crawl_error.category if crawl_error else None,
        }
        manifest_lines.append(_canonical_json(row) + b"\n")
        if not success:
            failure = {"item_ref": row["item_ref"], "stage": "crawl", "reason": reason}
            if crawl_error:
                failure["category"] = crawl_error.category
            failures.append(failure)
    manifest_path = run_dir / "archive-manifest.jsonl"
    failures_path = run_dir / "failures.json"
    manifest_bytes = b"".join(manifest_lines)
    failures_bytes = _canonical_json(failures) + b"\n"
    _exclusive_write(manifest_path, manifest_bytes)
    _exclusive_write(failures_path, failures_bytes)

    counts = {
        "input": len(urls),
        "success": len(accepted) if crawl_error is None else 0,
        "failed": len(failures),
        "skipped": 0,
        "unsupported": 0,
    }
    status = "completed" if not failures else ("partial" if counts["success"] else "failed")
    summary = {
        "schema_version": "yichen-firecrawl-site-run/v1",
        "status": status,
        "backend": "firecrawl-v2-bounded-site",
        "request": _scope_request(scope),
        "crawl_job_ref": job_id,
        "counts": counts,
        "crawl_failure": (
            None
            if crawl_error is None
            else {
                "stage": "crawl",
                "reason": crawl_error.category,
                "category": crawl_error.category,
            }
        ),
        "failures": failures,
        "rejected_crawl_documents": rejected_documents,
        "policy": _fixed_policy(scope),
        "quota_exposure": _quota_exposure(scope),
        "preflight_audit": preflight_audit,
        "limitations": [
            "Only URLs in the signed Map preflight were archived.",
            "storeInCache=false reduces Firecrawl cache persistence but is not absolute zero data retention.",
        ],
    }
    summary_path = run_dir / "run-summary.json"
    summary_bytes = _canonical_json(summary) + b"\n"
    _exclusive_write(summary_path, summary_bytes)
    copied = preflight_audit["copied_artifacts"]
    handoff = {
        "handoff_version": "yichen-content-handoff/v1",
        "producer_skill": "yichen-content-archive",
        "operation": "content_archive",
        "scope": {
            "platforms": ["web"],
            "input_kind": "known_collection",
            "container_kind": "bounded_site",
            "discovery_performed": True,
            "site_url": scope.site_url,
            "path_prefix": scope.path_prefix,
            "limit": scope.limit,
            "max_depth": scope.max_depth,
        },
        "authorization": {
            "private_read_authorized_this_turn": False,
            "download_authorized_this_turn": True,
            "authorization_not_transferable": True,
        },
        "artifacts": [
            {
                "kind": "preflight",
                "path": copied["preflight"]["path"],
                "count": 1,
                "sha256": copied["preflight"]["sha256"],
            },
            {
                "kind": "site_map",
                "path": copied["site_map"]["path"],
                "count": len(urls),
                "sha256": copied["site_map"]["sha256"],
            },
            {
                "kind": "enumerated_url_list",
                "path": copied["enumerated_url_list"]["path"],
                "count": len(urls),
                "sha256": copied["enumerated_url_list"]["sha256"],
            },
            {
                "kind": "archive_manifest",
                "path": str(manifest_path),
                "count": len(urls),
                "sha256": _sha256(manifest_bytes),
            },
            {
                "kind": "run_summary",
                "path": str(summary_path),
                "count": 1,
                "sha256": _sha256(summary_bytes),
            },
            {
                "kind": "failures",
                "path": str(failures_path),
                "count": len(failures),
                "sha256": _sha256(failures_bytes),
            },
            {"kind": "web_content", "path": str(web_root), "count": counts["success"]},
        ],
        "counts": counts,
        "quota_exposure": _quota_exposure(scope),
        "failures": failures,
        "next_step": {"action": "none", "requires_explicit_user_request": True},
    }
    handoff_path = run_dir / "handoff.json"
    _exclusive_write(handoff_path, _canonical_json(handoff) + b"\n")
    return {
        "status": status,
        "mode": "crawl_execute",
        "run_dir": str(run_dir),
        "archive_manifest": str(manifest_path),
        "run_summary": str(summary_path),
        "failures": str(failures_path),
        "handoff": str(handoff_path),
        "web": str(web_root),
        "preflight": copied["preflight"]["path"],
        "site_map": copied["site_map"]["path"],
        "enumerated_urls": copied["enumerated_url_list"]["path"],
        "counts": counts,
        "quota_exposure": _quota_exposure(scope),
    }


def run_execute(
    scope: Scope,
    *,
    preflight_path: Path,
    client: Any,
    api_key: bytes,
    output_root: Path,
    crawl_timeout: int,
    poll_seconds: float,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    current = _utc_now() if now is None else now.astimezone(timezone.utc)
    verified_preflight, preflight_bytes, map_bytes, list_bytes, urls = _load_verified_preflight(
        preflight_path, scope=scope, api_key=api_key, now=current
    )
    run_dir = _new_run_dir(output_root, "crawl", current)
    copied_preflight_path = run_dir / "preflight.json"
    copied_map_path = run_dir / "site-map.json"
    copied_list_path = run_dir / "enumerated-urls.txt"
    _exclusive_write(copied_preflight_path, preflight_bytes)
    _exclusive_write(copied_map_path, map_bytes)
    _exclusive_write(copied_list_path, list_bytes)
    source_preflight_path = Path(os.path.abspath(preflight_path.expanduser()))
    preflight_audit = {
        "source_preflight": {
            "path": str(source_preflight_path),
            "sha256": _sha256(preflight_bytes),
        },
        "verified_receipt": {
            "algorithm": verified_preflight["receipt"]["algorithm"],
            "key_derivation": verified_preflight["receipt"]["key_derivation"],
            "signature": verified_preflight["receipt"]["signature"],
        },
        "signed_artifact_hashes": {
            "site_map": verified_preflight["artifacts"]["site_map"]["sha256"],
            "enumerated_url_list": verified_preflight["artifacts"]["enumerated_urls"]["sha256"],
        },
        "copied_artifacts": {
            "preflight": {
                "path": str(copied_preflight_path),
                "sha256": _sha256(preflight_bytes),
            },
            "site_map": {"path": str(copied_map_path), "sha256": _sha256(map_bytes)},
            "enumerated_url_list": {
                "path": str(copied_list_path),
                "sha256": _sha256(list_bytes),
            },
        },
        "signed_source_paths_preserved_in_preflight_copy": True,
    }
    job_id: str | None = None
    documents: list[Any] = []
    crawl_error: SiteError | None = None
    try:
        job_id, documents = _collect_crawl(
            client,
            _crawl_payload(scope),
            timeout=crawl_timeout,
            poll_seconds=poll_seconds,
            sleep=sleep,
        )
    except SiteError as exc:
        crawl_error = exc
    return _write_execute_result(
        run_dir=run_dir,
        scope=scope,
        urls=urls,
        documents=documents,
        job_id=job_id,
        crawl_error=crawl_error,
        now=current,
        preflight_audit=preflight_audit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded Firecrawl Map preflight; Crawl requires a matching signed preflight."
    )
    parser.add_argument("--site-url", required=True)
    parser.add_argument("--path-prefix", required=True)
    parser.add_argument("--limit", required=True, type=int)
    parser.add_argument("--max-depth", required=True, type=int)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--preflight")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--request-timeout", type=int, default=30)
    parser.add_argument("--crawl-timeout", type=int, default=300)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.execute and not args.preflight:
        parser.error("--execute requires --preflight <file>")
    if args.preflight and not args.execute:
        parser.error("--preflight is accepted only with --execute")
    if not 1 <= args.request_timeout <= 60:
        parser.error("--request-timeout must be between 1 and 60")
    if not 30 <= args.crawl_timeout <= 600:
        parser.error("--crawl-timeout must be between 30 and 600")
    if not 0.25 <= args.poll_seconds <= 10:
        parser.error("--poll-seconds must be between 0.25 and 10")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        scope = make_scope(args.site_url, args.path_prefix, args.limit, args.max_depth)
        api_key = _load_api_key()
        client = FirecrawlClient(api_key, timeout=args.request_timeout)
        if args.execute:
            result = run_execute(
                scope,
                preflight_path=Path(args.preflight),
                client=client,
                api_key=api_key,
                output_root=Path(args.output_root),
                crawl_timeout=args.crawl_timeout,
                poll_seconds=args.poll_seconds,
            )
        else:
            result = run_preflight(
                scope,
                client=client,
                api_key=api_key,
                output_root=Path(args.output_root),
            )
    except SiteError as exc:
        print(
            json.dumps(
                {"status": "failed", "error": {"category": exc.category, "message": exc.message}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"preflight_ready", "completed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
