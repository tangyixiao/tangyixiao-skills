#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "scripts/route_asr.py"


def run_router(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROUTER), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


class UnifiedAsrContractTests(unittest.TestCase):
    def test_text_defaults_to_step(self) -> None:
        payload = run_router("--provider", "auto", "--text-only")
        self.assertEqual(payload["provider"], "step")
        self.assertTrue(payload["compatible"])

    def test_srt_defaults_to_doubao(self) -> None:
        payload = run_router("--provider", "auto", "--need-srt")
        self.assertEqual(payload["provider"], "doubao")
        self.assertTrue(payload["compatible"])

    def test_explicit_step_never_silently_switches(self) -> None:
        payload = run_router(
            "--provider", "step", "--need-timestamps", "--need-srt"
        )
        self.assertEqual(payload["provider"], "step")
        self.assertFalse(payload["compatible"])
        self.assertFalse(payload["fallback"]["allowed_before_submission"])

    def test_no_cross_provider_fallback_after_submission(self) -> None:
        payload = run_router(
            "--provider", "auto", "--text-only", "--already-submitted"
        )
        self.assertFalse(payload["fallback"]["allowed_after_submission"])
        self.assertIn("禁止跨服务商重提", payload["fallback"]["instruction"])

    def test_skill_points_to_both_configurable_executors(self) -> None:
        source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("YICHEN_STEP_ASR_SCRIPT", source)
        self.assertIn("yichen-volc-asr/scripts/transcribe.py", source)
        self.assertIn("unknown_requires_console_login", (
            ROOT / "scripts/asr_doctor.py"
        ).read_text(encoding="utf-8"))

    def test_public_doctor_contains_no_account_ids(self) -> None:
        source = (ROOT / "scripts/asr_doctor.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r'(?<![A-Za-z0-9])[0-9]{10,}(?![A-Za-z0-9])')
        self.assertIn("VOLC_ASR_TRIAL_APP_ID", source)
        self.assertIn("VOLC_ASR_PAID_APP_ID", source)


if __name__ == "__main__":
    unittest.main()
