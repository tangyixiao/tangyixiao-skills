#!/usr/bin/env python3
"""Choose an ASR backend without calling either provider."""

from __future__ import annotations

import argparse
import json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline router for Step ASR and Doubao/Volcengine ASR."
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "step", "doubao"),
        default="auto",
        help="Explicit provider or automatic feature-based routing.",
    )
    parser.add_argument("--text-only", action="store_true")
    parser.add_argument("--need-timestamps", action="store_true")
    parser.add_argument("--need-srt", action="store_true")
    parser.add_argument("--rough-cut", action="store_true")
    parser.add_argument(
        "--already-submitted",
        action="store_true",
        help="Indicate that a provider request already exists.",
    )
    return parser.parse_args()


def route(args: argparse.Namespace) -> dict[str, object]:
    requires_doubao = any(
        (args.need_timestamps, args.need_srt, args.rough_cut)
    )

    if args.provider == "step":
        provider = "step"
        reason = "用户明确指定 Step ASR"
    elif args.provider == "doubao":
        provider = "doubao"
        reason = "用户明确指定豆包 ASR"
    elif requires_doubao:
        provider = "doubao"
        reason = "需求包含时间戳、SRT 或口播粗剪"
    else:
        provider = "step"
        reason = "纯文本转写默认使用 Step ASR"

    compatible = not (
        provider == "step" and requires_doubao
    )
    if not compatible:
        reason += "；Step 执行器不能满足当前精细时间轴要求"

    return {
        "provider": provider,
        "compatible": compatible,
        "reason": reason,
        "requirements": {
            "text_only": args.text_only,
            "timestamps": args.need_timestamps,
            "srt": args.need_srt,
            "rough_cut": args.rough_cut,
        },
        "fallback": {
            "allowed_before_submission": args.provider == "auto",
            "allowed_after_submission": False,
            "already_submitted": args.already_submitted,
            "instruction": (
                "恢复原服务商任务，禁止跨服务商重提"
                if args.already_submitted
                else "先运行 asr_doctor.py，再执行所选后端"
            ),
        },
    }


def main() -> int:
    args = parse_args()
    print(json.dumps(route(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
