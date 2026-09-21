#!/usr/bin/env python3
"""Authorization-gated OpenCLI adapter for Xiaoyuzhou account-backed reads."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
OPENCLI_HOME = Path(
    os.environ.get("OPENCLI_HOME", str(Path.home() / ".opencli"))
).expanduser()
CREDENTIAL_FILE = Path(
    os.environ.get(
        "YICHEN_XIAOYUZHOU_CREDENTIAL_FILE",
        str(OPENCLI_HOME / "xiaoyuzhou.json"),
    )
).expanduser()


def add_authorization_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-account-token",
        action="store_true",
        help=(
            "Confirm current-turn authorization to let OpenCLI read and possibly refresh "
            "~/.opencli/xiaoyuzhou.json"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely route Xiaoyuzhou account-backed reads through OpenCLI. "
            "Every command requires explicit current-turn authorization."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    podcast = commands.add_parser("podcast", help="Read one podcast profile")
    podcast.add_argument("id", help="Podcast ID or podcast URL")
    add_authorization_flag(podcast)

    episodes = commands.add_parser(
        "episodes",
        help="List episodes for one podcast and export reviewable ID/URL files",
    )
    episodes.add_argument("id", help="Podcast ID or podcast URL")
    episodes.add_argument("--limit", type=int, default=20)
    episodes.add_argument(
        "--output-dir",
        help="Defaults to a new non-conflicting directory under /tmp",
    )
    episodes.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Compatibility-only destructive mode. Never use automatically; requires "
            "--confirm-overwrite-exact-dir with the same explicit absolute directory."
        ),
    )
    episodes.add_argument(
        "--confirm-overwrite-exact-dir",
        default="",
        help="High-friction confirmation: repeat the exact absolute --output-dir path",
    )
    add_authorization_flag(episodes)

    episode = commands.add_parser("episode", help="Read one episode's structured details")
    episode.add_argument("id", help="Episode ID or episode URL")
    add_authorization_flag(episode)

    download = commands.add_parser("download", help="Download one episode through OpenCLI")
    download.add_argument("id", help="Episode ID or episode URL")
    download.add_argument("--output-dir")
    add_authorization_flag(download)

    transcript = commands.add_parser(
        "transcript",
        help="Download one existing Xiaoyuzhou platform transcript through OpenCLI",
    )
    transcript.add_argument("id", help="Episode ID or episode URL")
    transcript.add_argument("--output-dir")
    add_authorization_flag(transcript)

    batch_download = commands.add_parser(
        "batch-download",
        help="Download episode IDs/URLs from a reviewed file through OpenCLI",
    )
    batch_download.add_argument("input", help="UTF-8 file containing one episode ID or URL per line")
    batch_download.add_argument("--output-dir")
    add_authorization_flag(batch_download)

    batch_transcript = commands.add_parser(
        "batch-transcript",
        help="Download platform transcripts for episode IDs/URLs from a reviewed file",
    )
    batch_transcript.add_argument("input", help="UTF-8 file containing one episode ID or URL per line")
    batch_transcript.add_argument("--output-dir")
    add_authorization_flag(batch_transcript)
    return parser


def normalize_id(value: str, kind: str) -> str:
    candidate = value.strip()
    if "/" in candidate:
        parts = [part for part in urlparse(candidate).path.split("/") if part]
        if kind not in parts:
            raise ValueError(f"不是小宇宙 {kind} 链接")
        index = parts.index(kind)
        if index + 1 >= len(parts):
            raise ValueError(f"小宇宙 {kind} 链接缺少 ID")
        candidate = parts[index + 1]
    candidate = candidate.strip()
    if not ID_PATTERN.fullmatch(candidate):
        raise ValueError(f"无效的 {kind} ID")
    return candidate


def load_episode_ids(path: str) -> list[str]:
    input_path = Path(path).expanduser().resolve()
    episode_ids: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        input_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            eid = normalize_id(value, "episode")
        except ValueError as exc:
            raise ValueError(f"输入文件第 {line_number} 行无效: {exc}") from exc
        if eid not in seen:
            seen.add(eid)
            episode_ids.append(eid)
    if not episode_ids:
        raise ValueError("输入文件中没有有效的 episode ID 或链接")
    return episode_ids


def run_opencli_json(arguments: list[str]) -> object:
    executable = shutil.which("opencli")
    if not executable:
        raise RuntimeError("opencli 命令不存在")
    result = subprocess.run(
        [executable, *arguments, "-f", "json"],
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip() or "unknown error")[:2000]
        raise RuntimeError(f"OpenCLI 执行失败: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenCLI 没有返回有效 JSON") from exc


def credentials_present() -> bool:
    """Check only whether the credential file exists; never read token values."""
    return CREDENTIAL_FILE.is_file()


def allocate_unique_directory(base: Path) -> Path:
    for attempt in range(1, 10_001):
        candidate = base if attempt == 1 else base.with_name(f"{base.name}-run-{attempt}")
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"无法分配不冲突的输出目录: {base}")


def validate_overwrite_authorization(
    *,
    overwrite: bool,
    output_arg: str | None,
    confirmation: str,
) -> Path | None:
    if not overwrite:
        if confirmation:
            raise ValueError("--confirm-overwrite-exact-dir 只能与 --overwrite 同时使用")
        return None
    if not output_arg:
        raise ValueError("--overwrite 必须同时显式提供 --output-dir")
    target = Path(output_arg).expanduser().resolve()
    if not target.is_absolute() or confirmation != str(target):
        raise ValueError(
            "--overwrite 需要独立高摩擦确认："
            "--confirm-overwrite-exact-dir 必须逐字等于解析后的绝对 --output-dir"
        )
    return target


def prepare_output_dir(
    output_arg: str | None,
    default_base: Path,
    *,
    overwrite: bool = False,
    confirmation: str = "",
) -> Path:
    confirmed_target = validate_overwrite_authorization(
        overwrite=overwrite,
        output_arg=output_arg,
        confirmation=confirmation,
    )
    if confirmed_target is not None:
        if not confirmed_target.is_dir():
            raise FileNotFoundError(
                f"高摩擦覆盖模式只接受已存在目录: {confirmed_target}"
            )
        return confirmed_target
    if output_arg:
        target = Path(output_arg).expanduser().resolve()
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise FileExistsError(
                f"用户指定的输出目录已存在，默认排他创建拒绝写入: {target}"
            ) from exc
        return target
    return allocate_unique_directory(default_base)


def write_text(path: Path, content: str, *, overwrite: bool) -> None:
    if overwrite:
        path.write_text(content, encoding="utf-8")
        return
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise FileExistsError(f"输出文件已存在，默认排他创建拒绝覆盖: {path}") from exc


def export_episodes(
    podcast_id: str,
    rows: object,
    output_dir: Path,
    *,
    overwrite: bool,
) -> dict[str, object]:
    if not isinstance(rows, list):
        raise RuntimeError("OpenCLI 节目列表格式异常：预期 JSON 数组")
    episode_ids: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not row.get("eid"):
            raise RuntimeError(f"OpenCLI 节目列表第 {index} 项缺少 eid")
        episode_ids.append(normalize_id(str(row["eid"]), "episode"))

    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"输出路径不是目录: {output_dir}")
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "episodes.json"
    ids_path = output_dir / "episode_ids.txt"
    urls_path = output_dir / "episode_urls.txt"
    if not overwrite:
        existing = [str(path) for path in (json_path, ids_path, urls_path) if path.exists()]
        if existing:
            raise FileExistsError(
                "输出文件已存在，改用新目录或显式传入 --overwrite: " + ", ".join(existing)
            )
    write_text(
        json_path,
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        overwrite=overwrite,
    )
    write_text(ids_path, "".join(f"{eid}\n" for eid in episode_ids), overwrite=overwrite)
    write_text(
        urls_path,
        "".join(f"https://www.xiaoyuzhoufm.com/episode/{eid}\n" for eid in episode_ids),
        overwrite=overwrite,
    )
    return {
        "event": "EPISODES_EXPORTED",
        "podcast_id": podcast_id,
        "count": len(episode_ids),
        "episodes_json": str(json_path),
        "episode_ids": str(ids_path),
        "episode_urls": str(urls_path),
    }


def run_batch(action: str, episode_ids: list[str], output_dir: Path) -> tuple[dict[str, object], int]:
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    opencli_action = "download" if action == "download" else "transcript"
    for eid in episode_ids:
        try:
            payload = run_opencli_json(
                ["xiaoyuzhou", opencli_action, eid, "--output", str(output_dir)]
            )
            results.append({"episode_id": eid, "result": payload})
        except Exception as exc:
            failures.append({"episode_id": eid, "error": str(exc)})
    report = {
        "event": "BATCH_DONE" if not failures else "BATCH_PARTIAL",
        "action": action,
        "total": len(episode_ids),
        "succeeded": len(results),
        "failed": len(failures),
        "output_dir": str(output_dir),
        "results": results,
        "failures": failures,
    }
    return report, 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.allow_account_token:
        parser.error(
            "OpenCLI 会读取并可能刷新 ~/.opencli/xiaoyuzhou.json；"
            "必须先取得用户对当前目标的明确授权，再传入 --allow-account-token"
        )
    if not credentials_present():
        print(
            json.dumps(
                {
                    "event": "AUTH_SETUP_REQUIRED",
                    "command": args.command,
                    "error": (
                        "本机没有 ~/.opencli/xiaoyuzhou.json。OpenCLI 1.8.6 没有小宇宙登录命令；"
                        "请先提醒用户完成凭证配置，不得自动创建或索取聊天中的明文令牌。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 3

    try:
        if args.command == "podcast":
            pid = normalize_id(args.id, "podcast")
            report = {
                "event": "PODCAST_READ",
                "podcast_id": pid,
                "result": run_opencli_json(["xiaoyuzhou", "podcast", pid]),
            }
            status = 0
        elif args.command == "episodes":
            if args.limit < 1:
                raise ValueError("--limit 必须是正整数")
            pid = normalize_id(args.id, "podcast")
            output_dir = prepare_output_dir(
                args.output_dir,
                Path(f"/tmp/xiaoyuzhou-opencli-{pid}"),
                overwrite=args.overwrite,
                confirmation=args.confirm_overwrite_exact_dir,
            )
            rows = run_opencli_json(
                ["xiaoyuzhou", "podcast-episodes", pid, "--limit", str(args.limit)]
            )
            report = export_episodes(pid, rows, output_dir, overwrite=args.overwrite)
            status = 0
        elif args.command == "episode":
            eid = normalize_id(args.id, "episode")
            report = {
                "event": "EPISODE_READ",
                "episode_id": eid,
                "result": run_opencli_json(["xiaoyuzhou", "episode", eid]),
            }
            status = 0
        elif args.command in {"download", "transcript"}:
            eid = normalize_id(args.id, "episode")
            output_dir = prepare_output_dir(
                args.output_dir,
                Path(f"/tmp/xiaoyuzhou-opencli-{args.command}-{eid}"),
            )
            report = {
                "event": "DOWNLOADED" if args.command == "download" else "TRANSCRIPT_DOWNLOADED",
                "episode_id": eid,
                "output_dir": str(output_dir),
                "result": run_opencli_json(
                    ["xiaoyuzhou", args.command, eid, "--output", str(output_dir)]
                ),
            }
            status = 0
        else:
            episode_ids = load_episode_ids(args.input)
            action = "download" if args.command == "batch-download" else "transcript"
            output_dir = prepare_output_dir(
                args.output_dir,
                Path(f"/tmp/xiaoyuzhou-opencli-batch-{action}"),
            )
            report, status = run_batch(action, episode_ids, output_dir)
    except Exception as exc:
        print(
            json.dumps(
                {"event": "ERROR", "command": args.command, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
