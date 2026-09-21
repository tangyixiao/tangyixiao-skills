import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "youtube_known_url", ROOT / "scripts" / "youtube_known_url.py"
)
YOUTUBE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = YOUTUBE
SPEC.loader.exec_module(YOUTUBE)


class YouTubeKnownUrlTests(unittest.TestCase):
    def test_video_url_is_canonicalized_and_channel_is_rejected(self):
        url, video_id = YOUTUBE.require_video_url(
            "https://youtu.be/abcdefghijk?si=temporary"
        )
        self.assertEqual(url, "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(video_id, "abcdefghijk")
        with self.assertRaises(YOUTUBE.ArchiveError):
            YOUTUBE.require_video_url("https://www.youtube.com/@example")

    def test_search_page_is_never_accepted(self):
        with self.assertRaises(YOUTUBE.ArchiveError):
            YOUTUBE.require_video_url(
                "https://www.youtube.com/results?search_query=example"
            )

    def test_playlist_requires_exact_playlist_container(self):
        url, playlist_id = YOUTUBE.require_playlist_url(
            "https://www.youtube.com/playlist?list=PLexample123"
        )
        self.assertEqual(playlist_id, "PLexample123")
        self.assertEqual(
            url, "https://www.youtube.com/playlist?list=PLexample123"
        )
        watch_url, watch_playlist_id = YOUTUBE.require_playlist_url(
            "https://www.youtube.com/watch?v=abcdefghijk&list=PLexample123"
        )
        self.assertEqual(watch_playlist_id, "PLexample123")
        self.assertEqual(
            watch_url, "https://www.youtube.com/playlist?list=PLexample123"
        )

    def test_output_collision_allocates_new_run_and_preserves_old(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = pathlib.Path(temp_dir) / "youtube-run"
            base.mkdir()
            sentinel = base / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            selected = YOUTUBE.allocate_output_dir(str(base), label="unused")
            self.assertEqual(selected.name, "youtube-run-run-2")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_subtitle_conversion_keeps_timestamps(self):
        source = (
            "1\n00:00:01,000 --> 00:00:04,000\nWelcome.\n\n"
            "2\n00:00:05,000 --> 00:00:09,000\nNext line.\n"
        )
        converted = YOUTUBE.srt_to_timestamped_text(source)
        self.assertNotIn("\n1\n", f"\n{converted}")
        self.assertIn("00:00:01,000 --> 00:00:04,000", converted)
        self.assertIn("Welcome.", converted)

    def test_download_command_is_no_overwrite_and_anonymous_by_default(self):
        command = YOUTUBE.download_command(
            binary="yt-dlp",
            url="https://www.youtube.com/watch?v=abcdefghijk",
            output_dir=pathlib.Path("/tmp/new-output"),
            quality="1080p",
            audio_only=False,
            allow_browser_cookies=False,
            browser="chrome",
        )
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-plugin-dirs", command)
        self.assertIn("--no-write-info-json", command)
        self.assertNotIn("--write-info-json", command)
        self.assertIn("--no-overwrites", command)
        self.assertIn("--no-playlist", command)
        self.assertNotIn("--cookies-from-browser", command)

    def test_all_operations_ignore_external_config_and_raw_info_files(self):
        # Observe the executable boundary without invoking yt-dlp or reading cookies.
        class Captured(Exception):
            pass
        calls = []
        def stop(command, **kwargs):
            calls.append(command)
            raise Captured()
        with tempfile.TemporaryDirectory() as temp_dir:
            args = SimpleNamespace(url="https://www.youtube.com/watch?v=abcdefghijk",
                allow_browser_cookies=False, browser="chrome", timeout=3,
                output_dir=temp_dir + "/out", langs="en", limit=2)
            with mock.patch.object(YOUTUBE, "dependency", return_value="yt-dlp"), mock.patch.object(YOUTUBE, "run", side_effect=stop):
                for operation in [YOUTUBE.info, YOUTUBE.subtitles, YOUTUBE.playlist]:
                    args.url = ("https://www.youtube.com/playlist?list=PLexample123"
                        if operation is YOUTUBE.playlist else "https://www.youtube.com/watch?v=abcdefghijk")
                    with self.assertRaises(Captured):
                        operation(args)
        self.assertEqual(len(calls), 3)
        for command in calls:
            self.assertIn("--ignore-config", command)
            self.assertIn("--no-plugin-dirs", command)
            self.assertNotIn("--write-info-json", command)
            self.assertNotIn("--cookies-from-browser", command)

    def test_browser_cookie_use_requires_explicit_flag(self):
        self.assertEqual(YOUTUBE.auth_args(False, "chrome"), [])
        self.assertEqual(
            YOUTUBE.auth_args(True, "chrome"),
            ["--cookies-from-browser", "chrome"],
        )


if __name__ == "__main__":
    unittest.main()
