#!/usr/bin/env python3
"""Read-only readiness check for the portable unified ASR route."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = Path(
    os.environ.get("YICHEN_SKILLS_ROOT", str(REPOSITORY_ROOT))
).expanduser()
STEP_SCRIPT = Path(
    os.environ.get(
        "YICHEN_STEP_ASR_SCRIPT",
        str(SKILLS_ROOT / "step-asr/scripts/step_asr_transcribe.py"),
    )
).expanduser()
DOUBAO_SCRIPT = Path(
    os.environ.get(
        "YICHEN_DOUBAO_ASR_SCRIPT",
        str(SKILLS_ROOT / "yichen-volc-asr/scripts/transcribe.py"),
    )
).expanduser()
DOUBAO_SKILL = DOUBAO_SCRIPT.parent.parent / "SKILL.md"
ACCOUNT_URL = "https://console.volcengine.com/finance/account-overview/"


def step_key_available() -> bool:
    return bool(os.environ.get("STEPFUN_API_KEY") or os.environ.get("STEP_API_KEY"))


def main() -> int:
    env = os.environ
    trial_exhausted = env.get("VOLC_ASR_TRIAL_EXHAUSTED") == "1"
    trial_app_id = env.get("VOLC_ASR_TRIAL_APP_ID")
    paid_app_id = env.get("VOLC_ASR_PAID_APP_ID")
    selected_app_id = env.get("VOLC_ASR_APP_ID") or (
        paid_app_id if trial_exhausted else trial_app_id
    )
    if not trial_exhausted and selected_app_id == trial_app_id:
        token_present = bool(env.get("VOLC_ASR_TRIAL_TOKEN"))
        mode = "trial"
    elif trial_exhausted and selected_app_id == paid_app_id:
        token_present = bool(
            env.get("VOLC_ASR_PAID_TOKEN") or env.get("VOLC_ASR_TOKEN")
        )
        mode = "paid"
    else:
        token_present = bool(env.get("VOLC_ASR_TOKEN"))
        mode = "custom"

    ffmpeg_ready = shutil.which("ffmpeg") is not None
    step_ready = STEP_SCRIPT.is_file() and ffmpeg_ready and step_key_available()
    doubao_ready = (
        DOUBAO_SCRIPT.is_file()
        and DOUBAO_SKILL.is_file()
        and ffmpeg_ready
        and bool(selected_app_id)
        and token_present
    )

    payload = {
        "ok": step_ready or doubao_ready,
        "ffmpeg": {
            "status": "ok" if ffmpeg_ready else "warn",
        },
        "step": {
            "status": "ok" if step_ready else "warn",
            "script_present": STEP_SCRIPT.is_file(),
            "credential_present": step_key_available(),
            "billing_status": "unknown",
        },
        "doubao": {
            "status": "ok" if doubao_ready else "warn",
            "script_present": DOUBAO_SCRIPT.is_file(),
            "skill_present": DOUBAO_SKILL.is_file(),
            "mode": mode,
            "app_id_present": bool(selected_app_id),
            "token_present": token_present,
            "credential_source": "environment" if token_present else "missing",
            "trial_marked_exhausted": trial_exhausted,
            "billing_status": "unknown_requires_console_login",
            "account_url": ACCOUNT_URL,
        },
        "safety": {
            "paid_api_called": False,
            "secret_values_printed": False,
            "cross_provider_fallback_after_submission": False,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
