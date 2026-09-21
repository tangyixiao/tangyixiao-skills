#!/usr/bin/env python3
"""Download media from one user-supplied public HTTPS URL without login state."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_MEDIA_BYTES = 4 * 1024 * 1024 * 1024
USER_AGENT = "yichen-content-archive/1.0 (+known public media downloader)"
X_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
X_MEDIA_HOSTS = {"video.twimg.com"}


class KnownMediaError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_x_reader() -> Any:
    path = Path(__file__).with_name("x_known_url.py")
    spec = importlib.util.spec_from_file_location("known_media_x_reader", path)
    if spec is None or spec.loader is None:
        raise KnownMediaError("backend_unavailable", "The public X reader is unavailable.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def safe_source_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    authority = host if port in {None, 443} else f"{host}:{port}"
    return urllib.parse.urlunsplit(("https", authority, parsed.path or "/", "", ""))


def _require_global_ip(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise KnownMediaError("invalid_host", "The media host resolved incorrectly.") from exc
    if not address.is_global:
        raise KnownMediaError("non_public_host", "Only public internet hosts are accepted.")


def validate_public_https_url(value: str, *, resolve_dns: bool = True) -> str:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise KnownMediaError("invalid_url", "The supplied media URL is invalid.") from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise KnownMediaError(
            "unsupported_url",
            "Only explicit public HTTPS URLs without embedded credentials are accepted.",
        )
    if port not in {None, 443}:
        raise KnownMediaError("unsupported_port", "Only the standard HTTPS port is accepted.")
    if host == "localhost" or host.endswith(".local"):
        raise KnownMediaError("non_public_host", "Local hosts are not accepted.")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise KnownMediaError("invalid_host", "The media host is invalid.") from exc
    try:
        _require_global_ip(ascii_host)
        is_ip = True
    except KnownMediaError as exc:
        if exc.category == "non_public_host":
            raise
        is_ip = False
    if resolve_dns and not is_ip:
        try:
            answers = socket.getaddrinfo(ascii_host, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise KnownMediaError("dns_failed", "The public media host could not be resolved.") from exc
        addresses = {answer[4][0] for answer in answers if answer[4]}
        if not addresses:
            raise KnownMediaError("dns_failed", "The public media host returned no addresses.")
        for address in addresses:
            _require_global_ip(address)
    return value.strip()


def validate_x_media_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in X_MEDIA_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise KnownMediaError(
            "unsafe_media_url",
            "The public X response did not contain an approved video CDN URL.",
        )
    return value


def choose_unique_output_dir(requested: Path) -> Path:
    candidate = requested.expanduser()
    counter = 2
    while candidate.exists():
        candidate = requested.with_name(f"{requested.name}-run-{counter}").expanduser()
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_x_videos(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, dict):
        return []
    media = content.get("media")
    videos = media.get("videos") if isinstance(media, dict) else None
    if not isinstance(videos, list):
        return []
    selected: list[dict[str, Any]] = []
    for index, video in enumerate(videos, start=1):
        if not isinstance(video, dict):
            continue
        candidates: list[tuple[int, str]] = []
        formats = video.get("formats")
        if isinstance(formats, list):
            for item in formats:
                if not isinstance(item, dict) or item.get("container") != "mp4":
                    continue
                url = item.get("url")
                bitrate = item.get("bitrate")
                if isinstance(url, str):
                    candidates.append((bitrate if isinstance(bitrate, int) else 0, url))
        fallback = video.get("url")
        if isinstance(fallback, str):
            candidates.append((0, fallback))
        if not candidates:
            continue
        bitrate, media_url = max(candidates, key=lambda item: item[0])
        selected.append(
            {
                "index": index,
                "id": str(video.get("id") or index),
                "url": validate_x_media_url(media_url),
                "bitrate": bitrate or None,
                "width": video.get("width"),
                "height": video.get("height"),
                "duration_seconds": video.get("duration"),
            }
        )
    return selected


class XMediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        validate_x_media_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_x_file(url: str, destination: Path, *, timeout: int) -> None:
    validate_x_media_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": "video/mp4", "User-Agent": USER_AGENT},
        method="GET",
    )
    opener = urllib.request.build_opener(XMediaRedirectHandler())
    partial = destination.with_suffix(f"{destination.suffix}.partial")
    try:
        with opener.open(request, timeout=timeout) as response:
            validate_x_media_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"video/mp4", "application/octet-stream"}:
                raise KnownMediaError("unexpected_media_type", "X returned a non-video response.")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_MEDIA_BYTES:
                raise KnownMediaError("media_too_large", "The video exceeds the 4 GiB safety limit.")
            written = 0
            with partial.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_MEDIA_BYTES:
                        raise KnownMediaError("media_too_large", "The video exceeds the 4 GiB safety limit.")
                    handle.write(chunk)
        if destination.exists():
            raise KnownMediaError("output_conflict", "The destination appeared during download.")
        partial.rename(destination)
    except KnownMediaError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise KnownMediaError("download_failed", "The public X video download failed.") from exc


def find_yt_dlp() -> str:
    preferred = Path.home() / ".local" / "bin" / "yt-dlp"
    if preferred.is_file() and os.access(preferred, os.X_OK):
        return str(preferred)
    binary = shutil.which("yt-dlp")
    if not binary:
        raise KnownMediaError("backend_unavailable", "yt-dlp is not installed.")
    return binary


def yt_dlp_common(timeout: int) -> list[str]:
    return [
        find_yt_dlp(),
        "--ignore-config",
        "--no-playlist",
        "--no-cookies-from-browser",
        "--socket-timeout",
        str(timeout),
        "--max-filesize",
        "4G",
    ]


def preflight_generic(url: str, *, timeout: int) -> dict[str, Any]:
    command = [*yt_dlp_common(timeout), "--skip-download", "--dump-single-json", "--", url]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise KnownMediaError("extractor_failed", "The anonymous single-URL extractor could not read this link.")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise KnownMediaError("invalid_response", "yt-dlp returned invalid metadata.") from exc
    if not isinstance(payload, dict) or payload.get("_type") in {"playlist", "multi_video"}:
        raise KnownMediaError("container_rejected", "Only one explicit media item is accepted per request.")
    if not payload.get("id"):
        raise KnownMediaError("invalid_response", "yt-dlp did not return a media identifier.")
    return payload


def download_generic(url: str, output_dir: Path, *, timeout: int) -> list[Path]:
    command = [
        *yt_dlp_common(timeout),
        "--no-overwrites",
        "--no-write-info-json",
        "--no-write-playlist-metafiles",
        "--no-write-comments",
        "--restrict-filenames",
        "--format",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--paths",
        f"home:{output_dir}",
        "--output",
        "%(extractor)s-%(id)s.%(ext)s",
        "--print",
        "after_move:filepath",
        "--no-simulate",
        "--",
        url,
    ]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise KnownMediaError("download_failed", "The anonymous single-URL media download failed.")
    root = output_dir.resolve()
    paths: list[Path] = []
    for line in process.stdout.splitlines():
        candidate = Path(line.strip()).expanduser()
        if not line.strip() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if root not in resolved.parents:
            raise KnownMediaError("output_escape", "The extractor returned a path outside the output directory.")
        paths.append(resolved)
    if len(paths) != 1:
        raise KnownMediaError("unexpected_output", "The extractor did not produce exactly one media file.")
    return paths


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def run(url: str, *, output_dir: str | None, timeout: int) -> dict[str, Any]:
    validated = validate_public_https_url(url)
    parsed = urllib.parse.urlsplit(validated)
    host = (parsed.hostname or "").lower()
    x_reader = None
    x_result = None
    source_id = None
    if host in X_HOSTS:
        x_reader = load_x_reader()
        x_result = x_reader.read_known_url(
            validated,
            timeout=timeout,
            allow_jina_fallback=False,
        )
        content = x_result.get("content") if isinstance(x_result, dict) else None
        videos = select_x_videos(content)
        if not videos:
            raise KnownMediaError("no_public_video", "The supplied X post has no anonymously downloadable MP4 video.")
        source_id = str(content.get("id") or x_result.get("input", {}).get("id"))
        requested = Path(output_dir).expanduser() if output_dir else Path.home() / "Downloads" / f"x-{source_id}"
        selected_dir = choose_unique_output_dir(requested)
        artifacts = []
        for video in videos:
            destination = selected_dir / f"x-{source_id}-video-{video['index']}.mp4"
            download_x_file(video["url"], destination, timeout=timeout)
            artifacts.append(
                {
                    "path": str(destination),
                    "size": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                    "bitrate": video["bitrate"],
                    "width": video["width"],
                    "height": video["height"],
                    "duration_seconds": video["duration_seconds"],
                }
            )
        backend = "fxtwitter-public+x-video-cdn"
        title = content.get("text") if isinstance(content, dict) else None
    else:
        preflight = preflight_generic(validated, timeout=timeout)
        source_id = str(preflight.get("id"))
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{host}-{source_id}").strip("-")[:120]
        requested = Path(output_dir).expanduser() if output_dir else Path.home() / "Downloads" / f"media-{slug}"
        selected_dir = choose_unique_output_dir(requested)
        paths = download_generic(validated, selected_dir, timeout=timeout)
        artifacts = [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in paths
        ]
        backend = "yt-dlp-anonymous-single-url"
        title = preflight.get("title")

    metadata = {
        "schema_version": "known-public-media/v1",
        "status": "success",
        "source_url": safe_source_url(validated),
        "source_id": source_id,
        "title": title,
        "backend": backend,
        "login_state_used": False,
        "discovery_performed": False,
        "downloaded_at": utc_now_iso(),
        "artifacts": artifacts,
    }
    metadata_path = selected_dir / "metadata.json"
    write_json_exclusive(metadata_path, metadata)
    return {**metadata, "output_dir": str(selected_dir), "metadata_path": str(metadata_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download media from one user-supplied public HTTPS URL anonymously."
    )
    parser.add_argument("url")
    parser.add_argument("--output-dir")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 5 <= args.timeout <= 120:
        parser.error("--timeout must be between 5 and 120 seconds")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = run(args.url, output_dir=args.output_dir, timeout=args.timeout)
    except KnownMediaError as exc:
        result = {
            "schema_version": "known-public-media/v1",
            "status": "failed",
            "error": {"category": exc.category, "message": exc.message},
            "login_state_used": False,
            "discovery_performed": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
