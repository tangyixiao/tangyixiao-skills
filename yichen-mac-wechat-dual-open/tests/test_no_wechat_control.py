#!/usr/bin/env python3
"""The helper may prepare a copy but must never launch WeChat."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wechat_dual_open.py"
SPEC = importlib.util.spec_from_file_location("wechat_dual_open", SCRIPT)
assert SPEC and SPEC.loader
dual_open = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dual_open)


class NoWeChatControlTests(unittest.TestCase):
    def test_launch_is_always_fail_closed(self) -> None:
        with (
            mock.patch.object(dual_open.subprocess, "Popen") as popen,
            self.assertRaisesRegex(RuntimeError, "no WeChat process was started"),
        ):
            dual_open.launch(Path("/Applications/WeChat.app"))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
