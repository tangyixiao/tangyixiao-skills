#!/usr/bin/env python3
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
ROUTE_REFERENCE = (ROOT / "references" / "platform-routes.md").read_text(
    encoding="utf-8"
)
ROUTES = json.loads((ROOT / "tests" / "routes.json").read_text(encoding="utf-8"))


class ContentArchiveContractTest(unittest.TestCase):
    def test_frontmatter_and_references(self):
        match = re.match(r"^---\n(.*?)\n---\n", SKILL, re.S)
        self.assertIsNotNone(match)
        keys = {
            line.split(":", 1)[0]
            for line in match.group(1).splitlines()
            if line and not line.startswith(" ")
        }
        self.assertEqual(keys, {"name", "description"})
        self.assertIn("name: yichen-content-archive", match.group(1))
        self.assertTrue((ROOT / "references" / "platform-routes.md").is_file())
        self.assertTrue((ROOT / "references" / "handoff-contract.md").is_file())
        self.assertTrue((ROOT / "references" / "xiaohongshu-bitable.md").is_file())

    def test_static_safety_gates(self):
        required = [
            "不得执行关键词搜索或开放式发现",
            "不得调用任何总路由",
            "不得再次调用 `$yichen-content-archive`",
            "不得自动读取私人收藏",
            "不得删除任何文件",
            "绝对不得操控微信客户端",
            "`known_collection`",
            "普通网页",
            "Twitter/X",
            "微博",
            "B站",
            "小宇宙",
            "Agent 禁止自动使用兼容 `--overwrite`",
            "安全兼容 stub",
            "`login`、`search`、`download`",
            "$yichen-wechat-mp-batch-exporter",
            "discovery_performed: false",
            "`xiaohongshu_fetch.py`",
            "`douyin_download.py`",
            "`weibo_known_url.py`",
            "`known_media_download.py`",
            "`firecrawl_site.py`",
            "--execute --preflight",
            "limit <= 100",
            "max-depth <= 3",
            "写入飞书多维表格",
        ]
        for marker in required:
            self.assertIn(marker, SKILL)
        scripts = {path.name for path in (ROOT / "scripts").glob("*.py")}
        self.assertEqual(
            scripts,
            {
                "wechat_mp_local.py",
                "xiaoyuzhou_stepfun.py",
                "xiaoyuzhou_opencli.py",
                "x_known_url.py",
                "xiaohongshu_fetch.py",
                "douyin_download.py",
                "weibo_known_url.py",
                "known_media_download.py",
                "youtube_known_url.py",
                "firecrawl_site.py",
            },
        )

    def test_legacy_social_fetcher_skills_are_retired(self):
        for name in (
            "douyin-fetcher",
            "xiaohongshu-fetch",
            "yichen-douyin-fetcher",
            "yichen-xiaohongshu-fetch",
        ):
            legacy = ROOT.parent / name
            self.assertFalse(legacy.exists() or legacy.is_symlink(), str(legacy))

    def test_route_fixtures_are_closed(self):
        allowed_skills = {
            "wechat-mp-batch-exporter",
        }
        allowed_backends = {
            "jina-reader",
            "web-reader",
            "exact-url-file",
            "yt-dlp",
            "bili-cli",
            "xiaoyuzhou-stepfun",
            "xiaoyuzhou-opencli+xiaoyuzhou-stepfun",
            "x-public-known-url",
            "xiaohongshu-known-url",
            "douyin-known-url",
            "weibo-known-url",
            "public-media-known-url",
            "youtube-known-url",
            "firecrawl-v2-bounded-site",
        }
        backend_markers = {
            "jina-reader": ("Jina Reader",),
            "web-reader": ("Web Reader",),
            "exact-url-file": ("URL 文件",),
            "yt-dlp": ("yt-dlp",),
            "bili-cli": ("bili-cli",),
            "xiaoyuzhou-stepfun": ("xiaoyuzhou_stepfun.py",),
            "xiaoyuzhou-opencli+xiaoyuzhou-stepfun": (
                "xiaoyuzhou_opencli.py",
                "xiaoyuzhou_stepfun.py",
            ),
            "x-public-known-url": ("x_known_url.py",),
            "xiaohongshu-known-url": ("xiaohongshu_fetch.py",),
            "douyin-known-url": ("douyin_download.py",),
            "weibo-known-url": ("weibo_known_url.py",),
            "public-media-known-url": ("known_media_download.py",),
            "youtube-known-url": ("youtube_known_url.py",),
            "firecrawl-v2-bounded-site": ("firecrawl_site.py",),
        }
        routable_decisions = {"route", "enumerate_then_route"}
        forbidden_branches = {
            "keyword-search",
            "channel",
            "recommend",
            "site-crawl",
            "cross-source-expand",
        }
        self.assertTrue(any(row["decision"] == "reject" for row in ROUTES))
        self.assertTrue(any(row["decision"] == "unsupported" for row in ROUTES))
        for row in ROUTES:
            if row["decision"] in routable_decisions:
                self.assertTrue(
                    ("route_skill" in row) ^ ("route_backend" in row),
                    row["case"],
                )
                if "route_skill" in row:
                    self.assertIn(row["route_skill"], allowed_skills)
                    self.assertIn(row["route_skill"], ROUTE_REFERENCE)
                else:
                    self.assertIn(row["route_backend"], allowed_backends)
                    for marker in backend_markers[row["route_backend"]]:
                        self.assertIn(marker, ROUTE_REFERENCE)
                self.assertNotIn(row["allowed_branch"], forbidden_branches)
            else:
                self.assertNotIn("route_skill", row)
                self.assertNotIn("route_backend", row)

    def test_known_collection_is_exact_and_bounded(self):
        collection_rows = [
            row for row in ROUTES if row["input_kind"] == "known_collection"
        ]
        self.assertGreaterEqual(len(collection_rows), 6)
        for row in collection_rows:
            if row["decision"] == "enumerate_then_route":
                self.assertIn(
                    row["container_scope"], {"exact", "exact_bounded"}, row["case"]
                )
        container_kinds = {
            row["container_kind"]
            for row in collection_rows
            if "container_kind" in row
        }
        self.assertTrue(
            {
                "url_file",
                "youtube_playlist_url",
                "bilibili_playlist_url",
                "episode_url_file",
                "xiaoyuzhou_podcast",
                "wechat_account_history",
                "bounded_site",
            }.issubset(container_kinds)
        )

    def test_wechat_account_history_route_is_retired(self):
        history = next(
            row for row in ROUTES if row["case"] == "known_wechat_account_history_archive"
        )
        self.assertEqual(history["decision"], "unsupported")
        self.assertEqual(history["reason"], "upstream_history_interface_retired")
        self.assertNotIn("route_backend", history)
        self.assertNotIn("wechat_mp_local.py search", ROUTE_REFERENCE)
        self.assertIn("最新 N 篇", ROUTE_REFERENCE)

    def test_wechat_retired_commands_fail_closed_before_side_effects(self):
        script = ROOT / "scripts" / "wechat_mp_local.py"
        temp_root = Path(
            tempfile.mkdtemp(prefix="wechat-mp-retired-contract-", dir="/tmp")
        )
        missing_input = temp_root / "must-not-be-read.txt"
        output_dir = temp_root / "must-not-be-created"
        commands = (
            ("login", "--open"),
            (
                "search",
                "--account",
                "example",
                "--accounts-file",
                str(missing_input),
                "--output-dir",
                str(output_dir),
                "--download",
                "--allow-local-account-session",
            ),
            (
                "download",
                "https://mp.weixin.qq.com/s/known",
                "--file",
                str(missing_input),
                "--output-dir",
                str(output_dir),
                "--resume-existing",
            ),
        )
        for arguments in commands:
            with self.subTest(arguments=arguments):
                process = subprocess.run(
                    [sys.executable, str(script), *arguments],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(process.stderr, "")
                payload = json.loads(process.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["status"], "unsupported")
                self.assertFalse(payload["side_effects_performed"])
                self.assertEqual(
                    payload["known_url_route"],
                    "wechat-mp-batch-exporter",
                )
                self.assertIn("$yichen-wechat-mp-batch-exporter", payload["error"])
                self.assertFalse(output_dir.exists())

    def test_wechat_stub_removes_retired_implementations(self):
        script = ROOT / "scripts" / "wechat_mp_local.py"
        source = script.read_text(encoding="utf-8")
        forbidden_source_fragments = (
            "DEFAULT_KV_BASE",
            "LoginRequired",
            "LocalExporterClient",
            "/api/public/v1/",
            "X-Auth-Key",
            "dashboard/account",
            "subprocess",
            "current_auth_key",
            "search_accounts",
            "resolve_account",
            "list_articles",
            "prepare_output_directory",
            "download_rows",
        )
        for fragment in forbidden_source_fragments:
            self.assertNotIn(fragment, source)

        spec = importlib.util.spec_from_file_location(
            "wechat_mp_local_contract",
            script,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in (
            "LocalExporterClient",
            "command_login",
            "command_search",
            "command_download",
            "read_urls",
            "download_rows",
            "current_auth_key",
        ):
            self.assertFalse(hasattr(module, name), name)
        self.assertEqual(module.RETIRED_COMMANDS, ("login", "search", "download"))

    def test_wechat_status_is_root_only_and_disclaims_capability(self):
        script = ROOT / "scripts" / "wechat_mp_local.py"
        process = subprocess.run(
            [sys.executable, str(script), "--timeout", "1", "status"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertIn(process.returncode, {0, 1})
        self.assertEqual(process.stderr, "")
        payload = json.loads(process.stdout)
        self.assertEqual(
            payload["diagnostic"],
            "localhost_root_reachability_only",
        )
        self.assertEqual(payload["root_url"], "http://127.0.0.1:18901/")
        self.assertTrue(payload["localhost_only"])
        self.assertFalse(payload["capability_proven"])
        self.assertIn("does not prove", payload["capability_note"])
        self.assertEqual(
            payload["retired_commands"],
            ["login", "search", "download"],
        )
        self.assertNotIn("login_status", payload)
        self.assertNotIn("kv_directory_exists", payload)

    def test_all_known_wechat_urls_route_to_batch_exporter(self):
        routed = [
            row
            for row in ROUTES
            if row["platform"] == "wechat" and row["decision"] == "route"
        ]
        self.assertGreaterEqual(len(routed), 2)
        self.assertTrue(
            all(
                row.get("route_skill") == "wechat-mp-batch-exporter"
                for row in routed
            )
        )
        self.assertNotIn("$wechat-article", SKILL)

    def test_required_known_url_platforms_are_covered(self):
        routed_platforms = {
            row["platform"]
            for row in ROUTES
            if row["decision"] in {"route", "enumerate_then_route"}
        }
        self.assertTrue(
            {
                "web",
                "x",
                "xiaohongshu",
                "douyin",
                "weibo",
                "wechat",
                "youtube",
                "bilibili",
                "xiaoyuzhou",
            }.issubset(routed_platforms)
        )
        rejected_actions = {
            row["action"] for row in ROUTES if row["decision"] == "reject"
        }
        self.assertTrue({"search", "crawl", "expand_similar"}.issubset(rejected_actions))


if __name__ == "__main__":
    unittest.main()
