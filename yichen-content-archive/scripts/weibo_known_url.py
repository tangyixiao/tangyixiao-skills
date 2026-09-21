#!/usr/bin/env python3
"""Read or download one known public Weibo post without user login state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse


ROUTE_BACKEND = "weibo-known-url"
HANDOFF_VERSION = "yichen-content-handoff/v1"
URL_RE = re.compile(r"(?:(?:https?):)?//[^\s\"']+", re.IGNORECASE)
HEADER_SECRET_RE = re.compile(
    r"(?i)\b(cookie|set-cookie|authorization)\s*[:=][^\r\n]*"
)
SECRET_RE = re.compile(
    r"(?i)(cookie|authorization|access[_-]?token|refresh[_-]?token)\s*[:=]\s*[^\s,;]+"
)
SAFE_FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

YTDLP_SAFETY_FLAGS = (
    "--ignore-config",
    "--no-config-locations",
    "--no-cookies",
    "--no-cookies-from-browser",
    "--no-cache-dir",
    "--no-playlist",
    "--playlist-items",
    "1",
    "--no-overwrites",
    "--no-post-overwrites",
    "--no-warnings",
)


class ArchiveError(RuntimeError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class KnownWeiboTarget:
    canonical_url: str
    post_hint: str
    expected_numeric_id: Optional[str]
    user_id: Optional[str]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_known_url(url: str) -> KnownWeiboTarget:
    """Normalize only an exact, user-provided Weibo post URL."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ArchiveError("invalid_url", "只接受公开 HTTPS 微博单条链接")
    if host not in {"weibo.com", "www.weibo.com", "m.weibo.cn"}:
        raise ArchiveError("invalid_url", "只接受 weibo.com 或 m.weibo.cn 的已知单条链接")
    if parsed.fragment:
        raise ArchiveError("invalid_url", "微博单条链接不得包含 fragment")

    path = re.sub(r"/+", "/", parsed.path or "/")
    query = parse_qs(parsed.query, keep_blank_values=True)

    overlay = re.fullmatch(r"/u/(?P<uid>\d{4,30})/?", path)
    if host in {"weibo.com", "www.weibo.com"} and overlay:
        layerids = query.get("layerid", [])
        if len(layerids) != 1 or not re.fullmatch(r"\d{5,30}", layerids[0]):
            raise ArchiveError(
                "invalid_url",
                "微博账号 overlay 链接必须且只能包含一个十进制 layerid",
            )
        post_id = layerids[0]
        return KnownWeiboTarget(
            canonical_url=f"https://m.weibo.cn/detail/{post_id}",
            post_hint=post_id,
            expected_numeric_id=post_id,
            user_id=overlay.group("uid"),
        )

    mobile = re.fullmatch(r"/(?:detail|status)/(?P<post>\d{5,30})/?", path)
    if host == "m.weibo.cn" and mobile:
        post_id = mobile.group("post")
        return KnownWeiboTarget(
            canonical_url=f"https://m.weibo.cn/detail/{post_id}",
            post_hint=post_id,
            expected_numeric_id=post_id,
            user_id=None,
        )

    desktop = re.fullmatch(
        r"/(?P<uid>\d{4,30})/(?P<post>[A-Za-z0-9]{5,30})/?", path
    )
    if host in {"weibo.com", "www.weibo.com"} and desktop:
        post_token = desktop.group("post")
        expected = post_token if post_token.isdigit() else None
        return KnownWeiboTarget(
            canonical_url=(
                f"https://weibo.com/{desktop.group('uid')}/{post_token}"
            ),
            post_hint=post_token,
            expected_numeric_id=expected,
            user_id=desktop.group("uid"),
        )

    raise ArchiveError(
        "unsupported_url_shape",
        "只支持微博单条 status/detail 或带唯一 layerid 的 overlay 链接；不支持账号页、搜索、热榜、评论或推荐页",
    )


def sanitized_error(value: str) -> str:
    text = HEADER_SECRET_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", value or ""
    )
    text = URL_RE.sub("[URL]", text)
    text = SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = " ".join(text.split())
    return text[:500] or "backend_failed"


def ytdlp_binary() -> str:
    binary = shutil.which("yt-dlp")
    if not binary:
        raise ArchiveError("backend_missing", "未找到 yt-dlp")
    return binary


def ytdlp_base_command(binary: str, timeout: int) -> List[str]:
    return [
        binary,
        *YTDLP_SAFETY_FLAGS,
        "--socket-timeout",
        str(timeout),
    ]


def run_process(command: Sequence[str], *, max_runtime: int, reason: str) -> str:
    try:
        process = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max_runtime,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchiveError(reason, "匿名微博后端超时") from exc
    if process.returncode != 0:
        # Backend stderr can contain temporary CDN URLs or response headers.
        # Keep it in memory only and persist a fixed classification.
        raise ArchiveError(reason, f"匿名微博后端失败（{reason}）")
    return process.stdout


def fetch_info(target: KnownWeiboTarget, timeout: int) -> Dict[str, Any]:
    command = [
        *ytdlp_base_command(ytdlp_binary(), timeout),
        "--skip-download",
        "--dump-single-json",
        target.canonical_url,
    ]
    raw = run_process(
        command,
        max_runtime=max(90, timeout * 4),
        reason="metadata_fetch_failed",
    )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArchiveError("metadata_parse_failed", "微博元数据不是有效 JSON") from exc

    if info.get("_type") in {"playlist", "multi_video", "url_transparent"}:
        raise ArchiveError("unexpected_collection", "目标被解析为多项容器，已停止")
    extractor = str(info.get("extractor") or info.get("extractor_key") or "")
    if extractor.lower() != "weibo":
        raise ArchiveError("unexpected_extractor", "目标未被解析为微博单条内容")
    resolved_id = str(info.get("id") or "")
    if not re.fullmatch(r"\d{5,30}", resolved_id):
        raise ArchiveError("invalid_resolved_id", "微博后端未返回有效单条 ID")
    if target.expected_numeric_id and resolved_id != target.expected_numeric_id:
        raise ArchiveError("target_mismatch", "解析结果与用户给出的 layerid 不一致")
    return info


def _format_score(item: Dict[str, Any]) -> tuple:
    return (
        int(item.get("height") or 0),
        int(item.get("width") or 0),
        float(item.get("tbr") or 0),
        int(item.get("filesize") or item.get("filesize_approx") or 0),
    )


def select_progressive_mp4(info: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for item in info.get("formats") or []:
        if not isinstance(item, dict):
            continue
        format_id = str(item.get("format_id") or "")
        if not SAFE_FORMAT_ID_RE.fullmatch(format_id):
            continue
        if item.get("ext") != "mp4":
            continue
        if item.get("vcodec") in {None, "none"}:
            continue
        if item.get("acodec") in {None, "none"}:
            continue
        if item.get("protocol") not in {"http", "https"}:
            continue
        candidates.append(item)
    if not candidates:
        raise ArchiveError(
            "unsupported_media_format",
            "未找到同时含音视频的单文件 MP4；为避免合并和临时清理，已停止",
        )
    return max(candidates, key=_format_score)


def sanitized_metadata(
    info: Dict[str, Any], target: KnownWeiboTarget, selected: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "schema_version": "weibo-known-url/v1",
        "platform": "weibo",
        "route_backend": ROUTE_BACKEND,
        "authentication": "anonymous-visitor",
        "source_url": target.canonical_url,
        "fetched_at": now_iso(),
        "post_id": str(info.get("id") or ""),
        "title": info.get("title"),
        "description": info.get("description"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id") or target.user_id,
        "timestamp": info.get("timestamp"),
        "upload_date": info.get("upload_date"),
        "duration_seconds": info.get("duration"),
        "selected_format": {
            "format_id": selected.get("format_id"),
            "ext": selected.get("ext"),
            "protocol": selected.get("protocol"),
            "width": selected.get("width"),
            "height": selected.get("height"),
            "fps": selected.get("fps"),
            "vcodec": selected.get("vcodec"),
            "acodec": selected.get("acodec"),
            "filesize": selected.get("filesize"),
            "filesize_approx": selected.get("filesize_approx"),
        },
    }


def choose_unique_run_dir(requested: Path) -> Path:
    requested = requested.expanduser()
    requested.parent.mkdir(parents=True, exist_ok=True)
    candidate = requested
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = requested.with_name(f"{requested.name}-run-{counter}")
        counter += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate.resolve()


def default_output_dir(post_hint: str) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    safe_hint = re.sub(r"[^A-Za-z0-9_-]", "_", post_hint)[:40]
    return Path.home() / "Downloads" / f"weibo-{safe_hint}-{timestamp}"


def write_json_exclusive(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_media(path: Path) -> Optional[Dict[str, Any]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        process = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None
    if process.returncode != 0:
        return None
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return None


def download_media(
    target: KnownWeiboTarget,
    info: Dict[str, Any],
    selected: Dict[str, Any],
    output_dir: Path,
    timeout: int,
) -> Path:
    post_id = str(info["id"])
    output_template = output_dir / f"weibo_{post_id}.%(ext)s"
    command = [
        *ytdlp_base_command(ytdlp_binary(), timeout),
        "--format",
        str(selected["format_id"]),
        "--output",
        str(output_template),
        "--print",
        "after_move:filepath",
        target.canonical_url,
    ]
    output = run_process(
        command,
        max_runtime=max(600, timeout * 20),
        reason="download_failed",
    )
    printed = [Path(line.strip()).expanduser() for line in output.splitlines() if line.strip()]
    expected = output_dir / f"weibo_{post_id}.mp4"
    media_path = printed[-1] if printed else expected
    if media_path.is_symlink():
        raise ArchiveError("unsafe_output_path", "后端返回了符号链接")
    try:
        resolved = media_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArchiveError("download_missing", "下载命令成功但未找到视频文件") from exc
    if resolved.parent != output_dir.resolve():
        raise ArchiveError("unsafe_output_path", "后端返回了输出目录之外的文件")
    if resolved.suffix.lower() != ".mp4" or resolved.stat().st_size <= 0:
        raise ArchiveError("invalid_media", "下载结果不是有效的非空 MP4 文件")
    return resolved


def write_run_artifacts(
    *,
    output_dir: Path,
    operation: str,
    post_id: str,
    metadata_path: Optional[Path],
    media_path: Optional[Path],
    verification: Optional[Dict[str, Any]],
    status: str,
    failure_reason: Optional[str] = None,
    failure_message: Optional[str] = None,
) -> Dict[str, Path]:
    fetched_at = now_iso()
    artifact_paths = [str(path) for path in (metadata_path, media_path) if path]
    failure = None
    if status != "success":
        failure = {
            "item_ref": f"weibo:{post_id}",
            "stage": operation,
            "reason": failure_reason or "unknown_failure",
            "message": sanitized_error(failure_message or "unknown failure"),
        }

    manifest_path = output_dir / "archive-manifest.jsonl"
    manifest = {
        "item_ref": f"weibo:{post_id}",
        "platform": "weibo",
        "source_url_ref": "input:1",
        "requested_actions": ["read" if operation == "info" else "download"],
        "status": status,
        "artifact_paths": artifact_paths,
        "route_backend": ROUTE_BACKEND,
        "fetched_at": fetched_at,
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False) + "\n")

    failures_path = output_dir / "failures.json"
    write_json_exclusive(failures_path, [] if failure is None else [failure])

    counts = {
        "input": 1,
        "success": 1 if status == "success" else 0,
        "failed": 0 if status == "success" else 1,
        "skipped": 0,
        "unsupported": 0,
    }
    summary_path = output_dir / "run-summary.json"
    write_json_exclusive(
        summary_path,
        {
            "operation": operation,
            "scope": {
                "platforms": ["weibo"],
                "input_kind": "known_urls",
                "discovery_performed": False,
            },
            "route_backend": ROUTE_BACKEND,
            "authorization": {
                "private_read_authorized_this_turn": False,
                "download_authorized_this_turn": operation == "download",
                "authorization_not_transferable": True,
            },
            "counts": counts,
            "artifacts": artifact_paths,
            "verification": verification,
            "failures": [] if failure is None else [failure],
            "finished_at": fetched_at,
        },
    )

    handoff_path = output_dir / "handoff.json"
    handoff_artifacts = [
        {"kind": "archive_manifest", "path": str(manifest_path), "count": 1},
        {"kind": "run_summary", "path": str(summary_path), "count": 1},
        {"kind": "failures", "path": str(failures_path), "count": len([] if failure is None else [failure])},
    ]
    if metadata_path:
        handoff_artifacts.append(
            {"kind": "metadata", "path": str(metadata_path), "count": 1}
        )
    if media_path:
        handoff_artifacts.append(
            {"kind": "video", "path": str(media_path), "count": 1}
        )
    write_json_exclusive(
        handoff_path,
        {
            "handoff_version": HANDOFF_VERSION,
            "producer_skill": "yichen-content-archive",
            "operation": "content_archive",
            "scope": {
                "platforms": ["weibo"],
                "input_kind": "known_urls",
                "discovery_performed": False,
            },
            "authorization": {
                "private_read_authorized_this_turn": False,
                "download_authorized_this_turn": operation == "download",
                "authorization_not_transferable": True,
            },
            "artifacts": handoff_artifacts,
            "counts": counts,
            "failures": [] if failure is None else [failure],
            "next_step": {
                "action": "none",
                "requires_explicit_user_request": True,
            },
        },
    )
    return {
        "manifest": manifest_path,
        "summary": summary_path,
        "failures": failures_path,
        "handoff": handoff_path,
    }


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    target = normalize_known_url(args.url)
    requested = Path(args.output_dir) if args.output_dir else default_output_dir(target.post_hint)
    output_dir = choose_unique_run_dir(requested)
    metadata_path: Optional[Path] = None
    media_path: Optional[Path] = None
    post_id = target.post_hint
    try:
        info = fetch_info(target, args.timeout)
        post_id = str(info["id"])
        selected = select_progressive_mp4(info)
        metadata = sanitized_metadata(info, target, selected)
        metadata_path = output_dir / "metadata.json"
        write_json_exclusive(metadata_path, metadata)

        verification: Dict[str, Any] = {
            "metadata_sanitized": True,
            "signed_media_url_persisted": False,
        }
        if args.operation == "download":
            media_path = download_media(
                target, info, selected, output_dir, args.timeout
            )
            verification.update(
                {
                    "sha256": sha256_file(media_path),
                    "size_bytes": media_path.stat().st_size,
                    "ffprobe": probe_media(media_path),
                }
            )

        artifacts = write_run_artifacts(
            output_dir=output_dir,
            operation=args.operation,
            post_id=post_id,
            metadata_path=metadata_path,
            media_path=media_path,
            verification=verification,
            status="success",
        )
        return {
            "ok": True,
            "status": "success",
            "platform": "weibo",
            "operation": args.operation,
            "post_id": post_id,
            "output_dir": str(output_dir),
            "media_path": str(media_path) if media_path else None,
            "metadata_path": str(metadata_path),
            "manifest_path": str(artifacts["manifest"]),
            "failures_path": str(artifacts["failures"]),
            "handoff_path": str(artifacts["handoff"]),
        }
    except ArchiveError as exc:
        try:
            artifacts = write_run_artifacts(
                output_dir=output_dir,
                operation=args.operation,
                post_id=post_id,
                metadata_path=metadata_path,
                media_path=media_path,
                verification=None,
                status="failed",
                failure_reason=exc.reason,
                failure_message=str(exc),
            )
            failure_path = str(artifacts["failures"])
        except Exception:
            failure_path = None
        return {
            "ok": False,
            "status": "failed",
            "platform": "weibo",
            "operation": args.operation,
            "post_id": post_id,
            "reason": exc.reason,
            "error": sanitized_error(str(exc)),
            "output_dir": str(output_dir),
            "failures_path": failure_path,
        }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="匿名读取或下载一个用户已提供的公开微博单条链接"
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("info", "download"):
        command = subparsers.add_parser(operation)
        command.add_argument("url")
        command.add_argument(
            "--output-dir",
            help="输出 run 目录；目标存在时自动使用不冲突的 -run-N 目录",
        )
        command.add_argument(
            "--timeout",
            type=int,
            default=30,
            choices=range(5, 121),
            metavar="SECONDS",
        )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        result = execute(args)
    except ArchiveError as exc:
        result = {
            "ok": False,
            "status": "rejected",
            "platform": "weibo",
            "reason": exc.reason,
            "error": sanitized_error(str(exc)),
            "side_effects_performed": False,
        }
    except Exception as exc:
        result = {
            "ok": False,
            "status": "failed",
            "platform": "weibo",
            "reason": "unexpected_local_error",
            "error": sanitized_error(str(exc)),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
