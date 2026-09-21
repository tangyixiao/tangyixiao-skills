#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "weibo_known_url.py"
    spec = importlib.util.spec_from_file_location("content_archive_weibo", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


weibo = load_module()


class WeiboKnownUrlTests(unittest.TestCase):
    def test_overlay_is_normalized_to_exact_mobile_detail(self) -> None:
        target = weibo.normalize_known_url(
            "https://weibo.com/u/5700099573?layerid=4930755200029647"
        )
        self.assertEqual(
            target.canonical_url,
            "https://m.weibo.cn/detail/4930755200029647",
        )
        self.assertEqual(target.expected_numeric_id, "4930755200029647")
        self.assertEqual(target.user_id, "5700099573")

    def test_mobile_status_and_desktop_status_are_single_items(self) -> None:
        mobile = weibo.normalize_known_url(
            "https://m.weibo.cn/status/4930755200029647"
        )
        self.assertEqual(
            mobile.canonical_url,
            "https://m.weibo.cn/detail/4930755200029647",
        )
        desktop = weibo.normalize_known_url(
            "https://weibo.com/5700099573/4930755200029647"
        )
        self.assertEqual(
            desktop.canonical_url,
            "https://weibo.com/5700099573/4930755200029647",
        )

    def test_account_search_hot_comments_external_and_duplicate_layerid_reject(self) -> None:
        rejected = (
            "https://weibo.com/u/5700099573",
            "https://weibo.com/search?q=test",
            "https://weibo.com/hot/search",
            "https://weibo.com/comments/4930755200029647",
            "https://example.com/u/5700099573?layerid=4930755200029647",
            "https://weibo.com/u/5700099573?layerid=4930755200029647&layerid=4930755200029648",
        )
        for url in rejected:
            with self.subTest(url=url):
                with self.assertRaises(weibo.ArchiveError):
                    weibo.normalize_known_url(url)

    def test_ytdlp_command_is_anonymous_closed_and_non_overwriting(self) -> None:
        command = weibo.ytdlp_base_command("/usr/bin/yt-dlp", 20)
        for flag in (
            "--ignore-config",
            "--no-config-locations",
            "--no-cookies",
            "--no-cookies-from-browser",
            "--no-cache-dir",
            "--no-playlist",
            "--no-overwrites",
            "--no-post-overwrites",
        ):
            self.assertIn(flag, command)
        self.assertNotIn("--cookies", command)
        self.assertNotIn("--cookies-from-browser", command)

    def test_best_progressive_mp4_is_selected(self) -> None:
        selected = weibo.select_progressive_mp4(
            {
                "formats": [
                    {
                        "format_id": "audio-only",
                        "ext": "m4a",
                        "protocol": "https",
                        "vcodec": "none",
                        "acodec": "mp4a",
                    },
                    {
                        "format_id": "mp4_hd",
                        "ext": "mp4",
                        "protocol": "https",
                        "width": 1620,
                        "height": 720,
                        "vcodec": "avc1",
                        "acodec": "mp4a",
                    },
                    {
                        "format_id": "mp4_1080p",
                        "ext": "mp4",
                        "protocol": "https",
                        "width": 2304,
                        "height": 1024,
                        "vcodec": "avc1",
                        "acodec": "mp4a",
                    },
                ]
            }
        )
        self.assertEqual(selected["format_id"], "mp4_1080p")

    def test_signed_urls_and_cookie_values_are_redacted(self) -> None:
        message = (
            "failed https://cdn.example/video.mp4?token=secret "
            "Cookie=session-secret Authorization=Bearer-secret"
        )
        sanitized = weibo.sanitized_error(message)
        self.assertNotIn("cdn.example", sanitized)
        self.assertNotIn("session-secret", sanitized)
        self.assertNotIn("Bearer-secret", sanitized)

    def test_full_auth_cookie_headers_and_scheme_relative_urls_are_redacted(self) -> None:
        message = (
            "Authorization: Bearer REALTOKEN\n"
            "Cookie: a=1; SUB=SECONDSECRET; csrftoken=THIRDSECRET\n"
            "failed //cdn.example/video.mp4?token=SIGNEDSECRET"
        )
        sanitized = weibo.sanitized_error(message)
        for secret in (
            "REALTOKEN",
            "SECONDSECRET",
            "THIRDSECRET",
            "SIGNEDSECRET",
            "cdn.example",
        ):
            self.assertNotIn(secret, sanitized)

    def test_existing_output_gets_new_run_without_touching_sentinel(self) -> None:
        root = Path(
            tempfile.mkdtemp(prefix="yichen-content-archive-weibo-", dir="/tmp")
        )
        requested = root / "weibo-test"
        requested.mkdir()
        sentinel = requested / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        selected = weibo.choose_unique_run_dir(requested)
        self.assertEqual(selected.name, "weibo-test-run-1")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
