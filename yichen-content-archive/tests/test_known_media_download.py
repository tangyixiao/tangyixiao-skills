#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "known_media_download", ROOT / "scripts" / "known_media_download.py"
)
MEDIA = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MEDIA
SPEC.loader.exec_module(MEDIA)


class KnownMediaDownloadTests(unittest.TestCase):
    def test_public_https_gate_rejects_local_and_credentials(self):
        self.assertEqual(
            MEDIA.validate_public_https_url(
                "https://8.8.8.8/video.mp4", resolve_dns=False
            ),
            "https://8.8.8.8/video.mp4",
        )
        with self.assertRaises(MEDIA.KnownMediaError):
            MEDIA.validate_public_https_url(
                "https://127.0.0.1/video.mp4", resolve_dns=False
            )
        with self.assertRaises(MEDIA.KnownMediaError):
            MEDIA.validate_public_https_url(
                "https://user:password@example.com/video", resolve_dns=False
            )

    def test_x_selector_uses_highest_bitrate_mp4(self):
        content = {
            "media": {
                "videos": [
                    {
                        "id": "123",
                        "url": "https://video.twimg.com/fallback.mp4",
                        "width": 1280,
                        "height": 720,
                        "duration": 10.5,
                        "formats": [
                            {
                                "url": "https://video.twimg.com/low.mp4",
                                "container": "mp4",
                                "bitrate": 256000,
                            },
                            {
                                "url": "https://video.twimg.com/high.mp4",
                                "container": "mp4",
                                "bitrate": 2176000,
                            },
                            {
                                "url": "https://video.twimg.com/master.m3u8",
                                "container": "m3u8",
                            },
                        ],
                    }
                ]
            }
        }
        selected = MEDIA.select_x_videos(content)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], "https://video.twimg.com/high.mp4")
        self.assertEqual(selected[0]["bitrate"], 2176000)

    def test_x_selector_rejects_unapproved_media_host(self):
        content = {
            "media": {
                "videos": [
                    {
                        "formats": [
                            {
                                "url": "https://example.com/video.mp4",
                                "container": "mp4",
                                "bitrate": 9999999,
                            }
                        ]
                    }
                ]
            }
        }
        with self.assertRaises(MEDIA.KnownMediaError):
            MEDIA.select_x_videos(content)

    def test_existing_output_directory_gets_new_run(self):
        artifact_root = pathlib.Path(
            tempfile.mkdtemp(prefix="known-media-download-test-", dir="/tmp")
        )
        requested = artifact_root / "media-example"
        requested.mkdir()
        selected = MEDIA.choose_unique_output_dir(requested)
        self.assertEqual(selected.name, "media-example-run-2")
        self.assertTrue(requested.is_dir())

    def test_generic_backend_is_single_url_anonymous(self):
        with mock.patch.object(MEDIA, "find_yt_dlp", return_value="yt-dlp"):
            command = MEDIA.yt_dlp_common(60)
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-playlist", command)
        self.assertIn("--no-cookies-from-browser", command)

    def test_saved_source_url_drops_query_and_fragment(self):
        self.assertEqual(
            MEDIA.safe_source_url("https://example.com/watch/1?token=secret#part"),
            "https://example.com/watch/1",
        )


if __name__ == "__main__":
    unittest.main()
