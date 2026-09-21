#!/usr/bin/env python3
"""Safely read or archive exact public YouTube URLs with yt-dlp.

This adapter never performs keyword search, channel discovery, recommendation
expansion, deletion, or silent overwrite. Browser cookies are opt-in only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
}
QUALITY_FORMATS = {
    "best": "bestvideo+bestaudio/best",
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
}


class ArchiveError(RuntimeError):
    """A safe, user-facing archive failure."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def normalized_host(value: str) -> str:
    host = value.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_url(raw: str) -> tuple[str, str, str | None]:
    """Return (kind, normalized URL, stable video/playlist ID)."""
    value = raw.strip()
    parsed = urlparse(value)
    host = normalized_host(parsed.hostname or "")
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise ArchiveError("invalid_url", "Expected a public HTTP(S) YouTube URL.")

    parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)
    if host == "youtu.be" and parts and VIDEO_ID_RE.fullmatch(parts[0]):
        video_id = parts[0]
        return "video", f"https://www.youtube.com/watch?v={video_id}", video_id

    if parsed.path == "/watch":
        video_id = (query.get("v") or [None])[0]
        if video_id and VIDEO_ID_RE.fullmatch(video_id):
            return "video", f"https://www.youtube.com/watch?v={video_id}", video_id

    if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
        video_id = parts[1]
        if VIDEO_ID_RE.fullmatch(video_id):
            return "video", f"https://www.youtube.com/watch?v={video_id}", video_id

    playlist_id = (query.get("list") or [None])[0]
    if parsed.path == "/playlist" and playlist_id:
        normalized = urlunparse(
            ("https", "www.youtube.com", "/playlist", "", urlencode({"list": playlist_id}), "")
        )
        return "playlist", normalized, playlist_id

    if parts and (
        parts[0].startswith("@")
        or parts[0] in {"channel", "c", "user"}
        or CHANNEL_ID_RE.fullmatch(parts[0])
    ):
        return "channel", value, None
    if parsed.path == "/results" or "search_query" in query:
        return "search", value, None
    raise ArchiveError("unsupported_url", "The URL is not a supported YouTube video or playlist.")


def require_video_url(raw: str) -> tuple[str, str]:
    kind, normalized, stable_id = classify_url(raw)
    if kind != "video" or stable_id is None:
        raise ArchiveError(
            "video_url_required",
            "This command accepts one exact YouTube video URL, not a channel, search page, or playlist.",
        )
    return normalized, stable_id


def require_playlist_url(raw: str) -> tuple[str, str]:
    value = raw.strip()
    parsed = urlparse(value)
    host = normalized_host(parsed.hostname or "")
    playlist_id = (parse_qs(parsed.query).get("list") or [None])[0]
    if (
        parsed.scheme not in {"http", "https"}
        or host not in YOUTUBE_HOSTS
        or not playlist_id
        or not re.fullmatch(r"[A-Za-z0-9_-]{10,}", playlist_id)
    ):
        raise ArchiveError(
            "playlist_url_required",
            "Playlist enumeration requires an exact YouTube URL containing a valid list= ID.",
        )
    normalized = urlunparse(
        ("https", "www.youtube.com", "/playlist", "", urlencode({"list": playlist_id}), "")
    )
    return normalized, playlist_id


def dependency() -> str:
    binary = shutil.which("yt-dlp")
    if not binary:
        raise ArchiveError("missing_dependency", "yt-dlp is not installed.")
    return binary


def allocate_output_dir(requested: str | None, *, label: str) -> Path:
    """Exclusively create a new output directory without touching prior runs."""
    if requested:
        base = Path(requested).expanduser().resolve()
    else:
        stamp = utc_now().strftime("%Y%m%d-%H%M%S")
        base = (Path.home() / "Downloads" / f"youtube-{label}-{stamp}").resolve()
    base.parent.mkdir(parents=True, exist_ok=True)
    candidate = base
    suffix = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = base.with_name(f"{base.name}-run-{suffix}")
        suffix += 1
    candidate.mkdir(mode=0o700)
    return candidate


def auth_args(allow_browser_cookies: bool, browser: str) -> list[str]:
    if not allow_browser_cookies:
        return []
    return ["--cookies-from-browser", browser]


def run(command: list[str], *, timeout: int, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=capture,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchiveError("timeout", "yt-dlp operation timed out.") from exc
    if result.returncode:
        raise ArchiveError(
            "yt_dlp_failed",
            f"yt-dlp failed with exit code {result.returncode}; no login fallback was attempted automatically.",
        )
    return result


def safe_metadata(payload: dict[str, Any], normalized_url: str, video_id: str) -> dict[str, Any]:
    published_at = None
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            published_at = iso_z(datetime.fromtimestamp(timestamp, timezone.utc))
        except (OSError, OverflowError, ValueError):
            pass
    upload_date = payload.get("upload_date")
    if published_at is None and isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00Z"
    return {
        "id": video_id,
        "title": payload.get("title"),
        "channel": payload.get("channel") or payload.get("uploader"),
        "channel_id": payload.get("channel_id") or payload.get("uploader_id"),
        "published_at": published_at,
        "duration_seconds": payload.get("duration"),
        "views": payload.get("view_count"),
        "likes": payload.get("like_count"),
        "description": payload.get("description"),
        "canonical_url": normalized_url,
    }


def info(args: argparse.Namespace) -> dict[str, Any]:
    normalized_url, video_id = require_video_url(args.url)
    command = [
        dependency(),
        "--ignore-config",
        "--no-plugin-dirs",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        *auth_args(args.allow_browser_cookies, args.browser),
        normalized_url,
    ]
    result = run(command, timeout=args.timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ArchiveError("invalid_response", "yt-dlp returned invalid metadata JSON.") from exc
    return {
        "status": "success",
        "action": "read",
        "platform": "youtube",
        "backend": "youtube-known-url",
        "login_state_used": args.allow_browser_cookies,
        "item": safe_metadata(payload, normalized_url, video_id),
        "fetched_at": iso_z(utc_now()),
    }


def download_command(
    *,
    binary: str,
    url: str,
    output_dir: Path,
    quality: str,
    audio_only: bool,
    allow_browser_cookies: bool,
    browser: str,
) -> list[str]:
    command = [
        binary,
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-overwrites",
        "--continue",
        "--no-playlist",
        "--no-write-info-json",
        *auth_args(allow_browser_cookies, browser),
    ]
    if audio_only:
        command.extend(["-x", "--audio-format", "mp3"])
    else:
        command.extend(
            ["-f", QUALITY_FORMATS[quality], "--merge-output-format", "mp4"]
        )
    command.extend(
        [
            "-o",
            str(output_dir / "%(title).180B [%(id)s].%(ext)s"),
            url,
        ]
    )
    return command


def list_artifacts(output_dir: Path) -> list[str]:
    return [
        str(path.resolve())
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    ]


def download(args: argparse.Namespace) -> dict[str, Any]:
    normalized_url, video_id = require_video_url(args.url)
    binary = dependency()
    output_dir = allocate_output_dir(args.output_dir, label=video_id)
    command = download_command(
        binary=binary,
        url=normalized_url,
        output_dir=output_dir,
        quality=args.quality,
        audio_only=args.audio_only,
        allow_browser_cookies=args.allow_browser_cookies,
        browser=args.browser,
    )
    try:
        run(command, timeout=args.timeout)
    except Exception:
        # The exclusive run directory is intentionally preserved for diagnostics.
        raise
    return {
        "status": "success",
        "action": "download_audio" if args.audio_only else "download_video",
        "platform": "youtube",
        "backend": "youtube-known-url",
        "login_state_used": args.allow_browser_cookies,
        "video_id": video_id,
        "output_dir": str(output_dir),
        "artifacts": list_artifacts(output_dir),
        "fetched_at": iso_z(utc_now()),
    }


def srt_to_timestamped_text(source: str) -> str:
    """Remove SRT sequence numbers while preserving timestamps and caption text."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"(?m)^\s*\d+\s*\n(?=\d{2}:\d{2}:\d{2},\d{3}\s+-->)", "", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return f"{normalized}\n" if normalized else ""


def convert_subtitles(output_dir: Path) -> list[Path]:
    written: list[Path] = []
    for srt_path in sorted(output_dir.glob("*.srt")):
        txt_path = srt_path.with_suffix(".txt")
        content = srt_to_timestamped_text(srt_path.read_text(encoding="utf-8-sig"))
        with txt_path.open("x", encoding="utf-8") as handle:
            handle.write(content)
        written.append(txt_path)
    return written


def subtitles(args: argparse.Namespace) -> dict[str, Any]:
    normalized_url, video_id = require_video_url(args.url)
    binary = dependency()
    output_dir = allocate_output_dir(args.output_dir, label=f"{video_id}-subtitles")
    command = [
        binary,
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-overwrites",
        "--no-playlist",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        args.langs,
        "--convert-subs",
        "srt",
        "--skip-download",
        "--no-write-info-json",
        *auth_args(args.allow_browser_cookies, args.browser),
        "-o",
        str(output_dir / "%(title).180B [%(id)s].%(ext)s"),
        normalized_url,
    ]
    run(command, timeout=args.timeout)
    converted = convert_subtitles(output_dir)
    srt_files = sorted(output_dir.glob("*.srt"))
    if not srt_files:
        raise ArchiveError(
            "subtitles_unavailable",
            "No requested public subtitles were available; the run directory was preserved.",
        )
    return {
        "status": "success",
        "action": "download_subtitles",
        "platform": "youtube",
        "backend": "youtube-known-url",
        "login_state_used": args.allow_browser_cookies,
        "video_id": video_id,
        "output_dir": str(output_dir),
        "srt_files": [str(path.resolve()) for path in srt_files],
        "txt_files": [str(path.resolve()) for path in converted],
        "artifacts": list_artifacts(output_dir),
        "fetched_at": iso_z(utc_now()),
    }


def playlist(args: argparse.Namespace) -> dict[str, Any]:
    normalized_url, playlist_id = require_playlist_url(args.url)
    binary = dependency()
    output_dir = allocate_output_dir(args.output_dir, label=f"playlist-{playlist_id}")
    command = [
        binary,
        "--ignore-config",
        "--no-plugin-dirs",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--yes-playlist",
        "--playlist-end",
        str(args.limit),
        *auth_args(args.allow_browser_cookies, args.browser),
        normalized_url,
    ]
    result = run(command, timeout=args.timeout)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ArchiveError("invalid_response", "yt-dlp returned invalid playlist JSON.") from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ArchiveError("invalid_response", "Playlist response is missing an entries list.")

    normalized_entries = []
    for position, entry in enumerate(entries[: args.limit], 1):
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "")
        if not VIDEO_ID_RE.fullmatch(video_id):
            continue
        normalized_entries.append(
            {
                "position": position,
                "id": video_id,
                "title": entry.get("title"),
                "channel": entry.get("channel") or entry.get("uploader"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    raw_total = payload.get("playlist_count")
    try:
        total = int(raw_total) if raw_total is not None else None
    except (TypeError, ValueError):
        total = None
    truncated = total is not None and total > args.limit
    manifest = {
        "schema_version": "1.0",
        "platform": "youtube",
        "backend": "youtube-known-url",
        "container_kind": "youtube_playlist_url",
        "container_id": playlist_id,
        "container_ref": normalized_url,
        "requested_limit": args.limit,
        "returned_count": len(normalized_entries),
        "known_total": total,
        "truncated": truncated if total is not None else None,
        "login_state_used": args.allow_browser_cookies,
        "entries": normalized_entries,
        "enumerated_at": iso_z(utc_now()),
    }
    manifest_path = output_dir / "playlist.json"
    urls_path = output_dir / "enumerated-urls.txt"
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with urls_path.open("x", encoding="utf-8") as handle:
        for entry in normalized_entries:
            handle.write(f"{entry['url']}\n")
    return {
        "status": "success",
        "action": "enumerate_playlist",
        "platform": "youtube",
        "backend": "youtube-known-url",
        "login_state_used": args.allow_browser_cookies,
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "url_list_path": str(urls_path),
        "returned_count": len(normalized_entries),
        "truncated": manifest["truncated"],
        "fetched_at": manifest["enumerated_at"],
    }


def add_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-browser-cookies",
        action="store_true",
        help="Use a browser login state only after current-turn authorization for this exact target.",
    )
    parser.add_argument(
        "--browser",
        choices=("chrome", "firefox", "safari"),
        default="chrome",
    )
    parser.add_argument("--timeout", type=int, default=300)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read or archive exact public YouTube URLs without search or overwrite."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="Read metadata for one exact video URL")
    info_parser.add_argument("url")
    add_auth_arguments(info_parser)

    download_parser = subparsers.add_parser("download", help="Download one exact video/audio URL")
    download_parser.add_argument("url")
    download_parser.add_argument("--output-dir")
    download_parser.add_argument("--quality", choices=tuple(QUALITY_FORMATS), default="best")
    download_parser.add_argument("--audio-only", action="store_true")
    add_auth_arguments(download_parser)

    subtitle_parser = subparsers.add_parser("subtitles", help="Download SRT and timestamped TXT")
    subtitle_parser.add_argument("url")
    subtitle_parser.add_argument("--output-dir")
    subtitle_parser.add_argument("--langs", default="en,zh-Hans")
    add_auth_arguments(subtitle_parser)

    playlist_parser = subparsers.add_parser("playlist", help="Enumerate one exact playlist")
    playlist_parser.add_argument("url")
    playlist_parser.add_argument("--output-dir")
    playlist_parser.add_argument("--limit", type=int, required=True)
    add_auth_arguments(playlist_parser)

    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 7200:
        parser.error("--timeout must be between 1 and 7200 seconds")
    if args.command == "playlist" and not 1 <= args.limit <= 5000:
        parser.error("--limit must be between 1 and 5000")
    if args.command == "subtitles":
        languages = [value.strip() for value in args.langs.split(",") if value.strip()]
        if not languages or any(not re.fullmatch(r"[A-Za-z0-9.*_-]+", value) for value in languages):
            parser.error("--langs must be a comma-separated list of subtitle language tags")
        args.langs = ",".join(languages)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    handlers = {
        "info": info,
        "download": download,
        "subtitles": subtitles,
        "playlist": playlist,
    }
    try:
        payload = handlers[args.command](args)
        code = 0
    except ArchiveError as exc:
        payload = {
            "status": "failed",
            "action": args.command,
            "platform": "youtube",
            "backend": "youtube-known-url",
            "error": {"category": exc.category, "message": exc.message},
        }
        code = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
