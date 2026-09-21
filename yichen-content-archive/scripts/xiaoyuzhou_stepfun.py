#!/usr/bin/env python3
"""Download Xiaoyuzhou episodes and optionally transcribe them with StepFun."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SKILLS_ROOT = Path(
    os.environ.get(
        "YICHEN_SKILLS_ROOT",
        str(Path(__file__).resolve().parents[2]),
    )
).expanduser()
STEP_ASR = Path(
    os.environ.get(
        "YICHEN_STEP_ASR_SCRIPT",
        str(SKILLS_ROOT / "step-asr/scripts/step_asr_transcribe.py"),
    )
).expanduser()
DEFAULT_OUTPUT_ROOT = Path("/tmp")
ARTIFACT_CONTRACT_VERSION = 1
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EPISODE_HOSTS = {"xiaoyuzhoufm.com", "www.xiaoyuzhoufm.com"}
MEDIA_HOST_SUFFIX = ".xyzcdn.net"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Xiaoyuzhou episodes and optionally transcribe them with StepFun only."
    )
    parser.add_argument("url", nargs="?", help="Xiaoyuzhou episode URL")
    parser.add_argument(
        "--batch-file",
        help="UTF-8 text file containing one Xiaoyuzhou episode URL per line",
    )
    parser.add_argument(
        "--output-dir",
        help="Persistent output directory; in batch mode each episode gets its own subdirectory",
    )
    parser.add_argument("--title", default="", help="Override episode title")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--hotwords", default="AI,Agent,Codex,法律科技,小宇宙")
    parser.add_argument("--request-gap", type=float, default=0.8)
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Reuse an existing episode directory only when source.json, size, and "
            "SHA-256 match; never rewrite source.json"
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--inspect-only",
        action="store_true",
        help="Resolve title and audio metadata without downloading or calling StepFun",
    )
    action.add_argument(
        "--download-only",
        action="store_true",
        help="Download source audio and metadata without calling StepFun",
    )
    args = parser.parse_args()
    if bool(args.url) == bool(args.batch_file):
        parser.error("provide exactly one episode URL or --batch-file")
    return args


def fetch_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in EPISODE_HOSTS:
        raise ValueError("只接受 https://www.xiaoyuzhoufm.com/episode/... 链接")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def decode_json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        return html.unescape(raw.replace("\\/", "/"))


def extract_episode(page: str) -> tuple[str, str]:
    normalized = html.unescape(page).replace("\\/", "/")
    audio_patterns = (
        r'https://media\.xyzcdn\.net/[^"\'<>\\ ]+?\.(?:m4a|mp3)(?:\?[^"\'<>\\ ]*)?',
        r'"enclosureUrl"\s*:\s*"([^"]+)"',
        r'"audioUrl"\s*:\s*"([^"]+)"',
    )
    audio_url = ""
    for pattern in audio_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            audio_url = match.group(1) if match.lastindex else match.group(0)
            audio_url = decode_json_string(audio_url)
            break

    title = ""
    title_match = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', page)
    if title_match:
        title = decode_json_string(title_match.group(1))
    if not title:
        html_title = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.IGNORECASE | re.DOTALL)
        if html_title:
            title = html.unescape(re.sub(r"\s+", " ", html_title.group(1))).strip()

    if not audio_url:
        raise RuntimeError("无法从小宇宙页面解析音频 URL")
    parsed_audio = urlparse(audio_url)
    if (
        parsed_audio.scheme != "https"
        or not parsed_audio.hostname
        or not (
            parsed_audio.hostname == "xyzcdn.net"
            or parsed_audio.hostname.endswith(MEDIA_HOST_SUFFIX)
        )
    ):
        raise RuntimeError("页面返回了非预期音频主机，拒绝下载")
    return title or "小宇宙播客", audio_url


def episode_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in EPISODE_HOSTS:
        raise ValueError("只接受 https://www.xiaoyuzhoufm.com/episode/... 链接")
    parts = [part for part in parsed.path.split("/") if part]
    if "episode" not in parts:
        raise ValueError("URL 不是小宇宙 episode 链接")
    index = parts.index("episode")
    if index + 1 >= len(parts):
        raise ValueError("URL 缺少 episode id")
    value = re.sub(r"[^A-Za-z0-9_-]", "", parts[index + 1])
    if not value:
        raise ValueError("episode id 无效")
    return value


def load_batch_urls(path: str) -> list[str]:
    batch_path = Path(path).expanduser().resolve()
    urls: list[str] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        batch_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            episode_id(value)
        except ValueError as exc:
            raise ValueError(f"批量文件第 {line_number} 行无效: {exc}") from exc
        if value not in seen:
            seen.add(value)
            urls.append(value)
    if not urls:
        raise ValueError("批量文件中没有有效的小宇宙 episode 链接")
    return urls


def download(url: str, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖既有音频文件: {destination}")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not (
            parsed.hostname == "xyzcdn.net"
            or parsed.hostname.endswith(MEDIA_HOST_SUFFIX)
        )
    ):
        raise ValueError("拒绝从非 xyzcdn.net 主机下载音频")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response, destination.open("xb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def allocate_unique_directory(base: Path) -> Path:
    for attempt in range(1, 10_001):
        candidate = base if attempt == 1 else base.with_name(f"{base.name}-run-{attempt}")
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"无法分配不冲突的输出目录: {base}")


def select_output_dir(
    args: argparse.Namespace,
    eid: str,
    *,
    batch_mode: bool,
) -> tuple[Path, bool]:
    if args.output_dir:
        output_root = Path(args.output_dir).expanduser().resolve()
        base = output_root / f"xiaoyuzhou-stepfun-{eid}" if batch_mode else output_root
        explicit_single_dir = not batch_mode
    else:
        base = DEFAULT_OUTPUT_ROOT / f"xiaoyuzhou-stepfun-{eid}"
        explicit_single_dir = False

    if args.inspect_only:
        return base, False

    if args.resume:
        if not base.is_dir():
            raise FileNotFoundError(f"--resume 只允许复用既有 episode 目录: {base}")
        return base, True

    if explicit_single_dir and base.exists():
        raise FileExistsError(
            f"用户指定的输出目录已存在，默认拒绝写入；改用新目录或对一致产物显式使用 --resume: {base}"
        )
    return allocate_unique_directory(base), False


def load_reusable_source(
    output_dir: Path,
    *,
    eid: str,
    source_url: str,
    extension: str,
) -> Path:
    metadata_path = output_dir / "source.json"
    if not metadata_path.is_file():
        raise RuntimeError(f"续跑目录缺少 source.json，无法证明产物一致: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"source.json 损坏，拒绝续跑: {metadata_path}") from exc
    expected = {
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "episode_id": eid,
        "source_url": source_url,
        "audio_extension": extension,
        "source_filename": f"source{extension}",
    }
    if not isinstance(metadata, dict):
        raise RuntimeError(f"source.json 结构异常，拒绝续跑: {metadata_path}")
    conflicts = {
        key: {"expected": value, "actual": metadata.get(key)}
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if conflicts:
        raise RuntimeError(
            "续跑产物与当前 episode 不一致，拒绝复用: "
            + json.dumps(conflicts, ensure_ascii=False, sort_keys=True)
        )
    source = output_dir / str(metadata["source_filename"])
    if not source.is_file() or source.stat().st_size <= 0:
        raise RuntimeError(f"续跑音频缺失或为空，拒绝复用: {source}")
    if metadata.get("source_size") != source.stat().st_size:
        raise RuntimeError(f"续跑音频大小校验失败，拒绝复用: {source}")
    actual_sha256 = sha256_file(source)
    if metadata.get("source_sha256") != actual_sha256:
        raise RuntimeError(f"续跑音频 SHA-256 校验失败，拒绝复用: {source}")
    return source


def write_source_metadata(path: Path, report: dict[str, object], source: Path) -> None:
    payload = {
        **report,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "source_filename": source.name,
        "source_size": source.stat().st_size,
        "source_sha256": sha256_file(source),
    }
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def process_episode(args: argparse.Namespace, url: str, *, batch_mode: bool) -> dict[str, object]:
    eid = episode_id(url)
    page = fetch_text(url)
    detected_title, audio_url = extract_episode(page)
    title = args.title or detected_title
    extension = Path(urlparse(audio_url).path).suffix.lower()
    if extension not in {".mp3", ".m4a"}:
        extension = ".mp3"

    output_dir, reuse_existing = select_output_dir(args, eid, batch_mode=batch_mode)
    report = {
        "episode_id": eid,
        "title": title,
        "source_url": url,
        "audio_host": urlparse(audio_url).hostname,
        "audio_extension": extension,
        "output_dir_planned": str(output_dir),
        "backend": "none (download only)"
        if args.download_only
        else "StepFun stepaudio-2.5-asr",
    }
    if args.inspect_only:
        return report

    if not args.download_only and not STEP_ASR.exists():
        raise SystemExit(f"Step ASR script not found: {STEP_ASR}")
    if reuse_existing:
        source = load_reusable_source(
            output_dir,
            eid=eid,
            source_url=url,
            extension=extension,
        )
    else:
        source = output_dir / f"source{extension}"
        download(audio_url, source)
        if source.stat().st_size <= 0:
            raise RuntimeError(f"下载结果为空，保留现场并拒绝写入 source.json: {source}")
        write_source_metadata(output_dir / "source.json", report, source)

    if args.download_only:
        return {
            **report,
            "output_dir": str(output_dir),
            "source": str(source),
            "event": "REUSED" if reuse_existing else "DOWNLOADED",
        }

    command = [
        sys.executable,
        str(STEP_ASR),
        "--input",
        str(source),
        "--output-dir",
        str(output_dir / "asr"),
        "--title",
        title,
        "--language",
        args.language,
        "--hotwords",
        args.hotwords,
        "--request-gap",
        str(args.request_gap),
    ]
    if args.resume:
        command.append("--resume")
    subprocess.run(command, check=True)
    return {
        **report,
        "output_dir": str(output_dir),
        "source_reused": reuse_existing,
        "event": "DONE",
    }


def main() -> None:
    args = parse_args()
    batch_mode = bool(args.batch_file)
    urls = load_batch_urls(args.batch_file) if args.batch_file else [args.url]
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    for url in urls:
        try:
            results.append(process_episode(args, url, batch_mode=batch_mode))
        except Exception as exc:
            if not batch_mode:
                raise
            failures.append({"source_url": url, "error": str(exc)})

    if not batch_mode:
        print(json.dumps(results[0], ensure_ascii=False, indent=2))
        return

    print(
        json.dumps(
            {
                "event": "BATCH_DONE" if not failures else "BATCH_PARTIAL",
                "total": len(urls),
                "succeeded": len(results),
                "failed": len(failures),
                "results": results,
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
