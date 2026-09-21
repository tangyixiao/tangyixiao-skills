#!/usr/bin/env python3
"""Fail-closed compatibility CLI for the retired local WeChat exporter entrypoint.

The command names remain parse-compatible for existing callers. Only `status`
performs I/O, and it probes the fixed localhost root without following redirects.
`login`, `search`, and `download` always fail before any client, file, or
browser action. Known article URLs belong to $yichen-wechat-mp-batch-exporter.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


DEFAULT_API_BASE = "http://127.0.0.1:18901"
ROOT_URL = DEFAULT_API_BASE + "/"
RETIRED_COMMANDS = ("login", "search", "download")
RETIRED_EXIT_CODE = 2
RETIREMENT_ERROR = (
    "unsupported: this legacy command is retired and no client, file, or browser "
    "action was performed; route known mp.weixin.qq.com article URLs to "
    "$yichen-wechat-mp-batch-exporter. Account search, complete-history sync, and "
    "latest-N sync remain unavailable."
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep the diagnostic request on the fixed localhost origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def retired_command(command: str) -> int:
    emit(
        {
            "ok": False,
            "command": command,
            "status": "unsupported",
            "error": RETIREMENT_ERROR,
            "side_effects_performed": False,
            "known_url_route": "wechat-mp-batch-exporter",
        }
    )
    return RETIRED_EXIT_CODE


def probe_localhost_root(timeout: int) -> tuple[bool, int | None, str | None]:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    request = urllib.request.Request(
        ROOT_URL,
        headers={"User-Agent": "yichen-content-archive-wechat-status/2.0"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return True, response.getcode(), None
    except urllib.error.HTTPError as exc:
        # An HTTP response proves that the localhost root answered. Redirects are
        # deliberately not followed, and no response body is read.
        return True, exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, None, str(exc)


def command_status(timeout: int) -> int:
    reachable, http_status, error = probe_localhost_root(timeout)
    emit(
        {
            "ok": reachable,
            "command": "status",
            "diagnostic": "localhost_root_reachability_only",
            "root_url": ROOT_URL,
            "localhost_only": True,
            "root_reachable": reachable,
            "http_status": http_status,
            "capability_proven": False,
            "capability_note": (
                "Root reachability does not prove login, account search, history "
                "enumeration, or article-body download capability."
            ),
            "retired_commands": list(RETIRED_COMMANDS),
            "error": error,
        }
    )
    return 0 if reachable else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retired local WeChat exporter compatibility CLI; use "
            "$yichen-wechat-mp-batch-exporter for known article URLs"
        )
    )
    parser.add_argument("--timeout", type=int, default=45)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    login = subparsers.add_parser("login")
    login.add_argument("--open", action="store_true")

    download = subparsers.add_parser("download")
    download.add_argument("urls", nargs="*")
    download.add_argument("--file", action="append", default=[])
    download.add_argument("--output-dir", default="")
    download.add_argument("--resume-existing", action="store_true")
    download.add_argument(
        "--format",
        choices=["markdown", "html", "text", "json"],
        default="markdown",
    )
    download.add_argument("--sleep", type=float, default=0.2)

    search = subparsers.add_parser("search")
    search.add_argument("--account", action="append", default=[])
    search.add_argument("--accounts-file", action="append", default=[])
    search.add_argument("--article-keyword", default="")
    search.add_argument("--limit-per-account", type=int, default=100)
    search.add_argument("--output-dir", default="")
    search.add_argument("--resume-existing", action="store_true")
    search.add_argument("--download", action="store_true")
    search.add_argument(
        "--format",
        choices=["markdown", "html", "text", "json"],
        default="markdown",
    )
    search.add_argument("--sleep", type=float, default=0.2)
    search.add_argument(
        "--allow-local-account-session",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command in RETIRED_COMMANDS:
        return retired_command(args.command)
    if args.command == "status":
        return command_status(args.timeout)
    emit(
        {
            "ok": False,
            "command": args.command,
            "error": f"unknown command: {args.command}",
            "side_effects_performed": False,
        }
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
