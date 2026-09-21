#!/usr/bin/env python3
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "firecrawl_site", ROOT / "scripts" / "firecrawl_site.py"
)
SITE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = SITE
SPEC.loader.exec_module(SITE)

API_KEY = b"fc-test-key-never-print"
NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, map_links=None, crawl_documents=None):
        self.map_links = map_links or []
        self.crawl_documents = crawl_documents or []
        self.map_payloads = []
        self.crawl_payloads = []
        self.status_calls = []

    def map_site(self, payload):
        self.map_payloads.append(payload)
        return {"success": True, "links": self.map_links}

    def start_crawl(self, payload):
        self.crawl_payloads.append(payload)
        return {"success": True, "id": "job-safe-1"}

    def crawl_status(self, job_id):
        self.status_calls.append(job_id)
        return {"success": True, "status": "completed", "data": self.crawl_documents}

    def next_page(self, url):
        raise AssertionError(f"unexpected pagination: {url}")


def make_preflight(directory, *, links=None, limit=3, depth=1):
    scope = SITE.make_scope("https://example.com/docs", "/docs", limit, depth)
    client = FakeClient(
        map_links=links
        or [
            "https://example.com/docs",
            "https://example.com/docs/a?tracking=1",
        ]
    )
    result = SITE.run_preflight(
        scope,
        client=client,
        api_key=API_KEY,
        output_root=pathlib.Path(directory),
        now=NOW,
    )
    return scope, client, result


class ScopeTests(unittest.TestCase):
    def test_scope_is_public_https_bounded_and_seed_is_inside_prefix(self):
        scope = SITE.make_scope("https://Example.com/docs/", "/docs/", 100, 3)
        self.assertEqual(scope.site_url, "https://example.com/docs")
        self.assertEqual(scope.path_prefix, "/docs")
        for url, prefix, limit, depth in (
            ("http://example.com/docs", "/docs", 10, 1),
            ("https://127.0.0.1/docs", "/docs", 10, 1),
            ("https://example.com/admin", "/docs", 10, 1),
            ("https://example.com/docs?login=1", "/docs", 10, 1),
            ("https://0x7f.0.0.1/docs", "/docs", 10, 1),
            ("https://127%2e0%2e0%2e1/docs", "/docs", 10, 1),
            ("https://%65xample.com/docs", "/docs", 10, 1),
            ("https://foo.internal/docs", "/docs", 10, 1),
            ("https://example.com:0/docs", "/docs", 10, 1),
            ("https://example.com/docs", "/docs", 101, 1),
            ("https://example.com/docs", "/docs", 10, 4),
        ):
            with self.subTest(url=url, limit=limit, depth=depth):
                with self.assertRaises(SITE.SiteError):
                    SITE.make_scope(url, prefix, limit, depth)

    def test_idna_is_canonicalized_before_origin_binding(self):
        cases = (
            ("Bücher.example.com", "xn--bcher-kva.example.com"),
            ("faß.de", "xn--fa-hia.de"),
            ("βόλος.com", "xn--nxasmm1c.com"),
        )
        for hostname, expected in cases:
            with self.subTest(hostname=hostname):
                scope = SITE.make_scope(
                    f"https://{hostname}/docs", "/docs", 10, 1
                )
                self.assertEqual(scope.site_url, f"https://{expected}/docs")

        for hostname in ("ab\u200ccd.com", "１２７．０．０．１"):
            with self.subTest(hostname=hostname):
                with self.assertRaises(SITE.SiteError):
                    SITE.make_scope(f"https://{hostname}/docs", "/docs", 10, 1)

        with mock.patch.object(SITE, "IDNA_UTS46", None):
            ascii_scope = SITE.make_scope(
                "https://Example.com/docs", "/docs", 10, 1
            )
            self.assertEqual(ascii_scope.origin, "https://example.com")
            with self.assertRaises(SITE.SiteError):
                SITE.make_scope("https://Bücher.de/docs", "/docs", 10, 1)

    def test_deep_path_encoding_and_encoded_separators_fail_closed(self):
        dangerous_paths = (
            "/docs/%2525252e%2525252e/admin",
            "/docs/%2525252fadmin",
            "/docs/%2525255cadmin",
            "/docs/%5cadmin",
            "/docs/%2fadmin",
        )
        for path in dangerous_paths:
            with self.subTest(path=path):
                with self.assertRaises(SITE.SiteError):
                    SITE._policy_path(path, "test path")
                with self.assertRaises(SITE.SiteError):
                    SITE.make_scope("https://example.com" + path, "/docs", 10, 1)

        too_deep = "%2e"
        for _ in range(SITE.MAX_PATH_DECODE_ROUNDS):
            too_deep = too_deep.replace("%", "%25")
        with self.assertRaises(SITE.SiteError):
            SITE._policy_path("/docs/" + too_deep, "test path")

        for malformed in ("/docs/%FF", "/docs/%", "/docs/%2", "/docs/%GG", "/docs/100%25"):
            with self.subTest(malformed=malformed):
                with self.assertRaises(SITE.SiteError):
                    SITE._policy_path(malformed, "test path")

    def test_empty_path_prefix_does_not_expand_to_full_site(self):
        for path_prefix in ("", "//", "///"):
            with self.subTest(path_prefix=path_prefix):
                with self.assertRaises(SITE.SiteError):
                    SITE.make_scope("https://example.com", path_prefix, 10, 1)
        scope = SITE.make_scope("https://example.com", "/", 10, 1)
        self.assertEqual(scope.site_url, "https://example.com/")
        self.assertEqual(scope.path_prefix, "/")

    def test_returned_urls_are_same_origin_and_path_and_drop_queries(self):
        scope = SITE.make_scope("https://example.com/docs", "/docs", 10, 1)
        self.assertEqual(
            SITE.normalize_scoped_url(
                "https://example.com/docs/a?token=must-not-be-written#part", scope
            ),
            "https://example.com/docs/a",
        )
        for value in (
            "https://sub.example.com/docs/a",
            "https://example.com/admin",
            "http://example.com/docs/a",
            "https://127.0.0.1/docs/a",
        ):
            with self.subTest(value=value):
                with self.assertRaises(SITE.SiteError):
                    SITE.normalize_scoped_url(value, scope)


class PreflightTests(unittest.TestCase):
    def test_default_run_calls_map_only_filters_and_writes_signed_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = SITE.make_scope("https://example.com/docs", "/docs", 3, 2)
            client = FakeClient(
                map_links=[
                    "https://example.com/docs/a?tracking=1",
                    "https://example.com/docs/a?tracking=2",
                    "https://sub.example.com/docs/b",
                    "https://example.com/outside",
                    {"url": "https://example.com/docs/c"},
                ]
            )
            result = SITE.run_preflight(
                scope,
                client=client,
                api_key=API_KEY,
                output_root=pathlib.Path(directory),
                now=NOW,
            )
            self.assertEqual(result["status"], "preflight_ready")
            self.assertEqual(client.crawl_payloads, [])
            self.assertEqual(
                client.map_payloads[0],
                {
                    "url": "https://example.com/docs",
                    "limit": 3,
                    "includeSubdomains": False,
                    "ignoreQueryParameters": True,
                },
            )
            urls = pathlib.Path(result["enumerated_urls"]).read_text().splitlines()
            self.assertEqual(
                urls,
                ["https://example.com/docs/a", "https://example.com/docs/c"],
            )
            preflight_text = pathlib.Path(result["preflight"]).read_text()
            self.assertNotIn(API_KEY.decode(), preflight_text)
            preflight = json.loads(preflight_text)
            self.assertEqual(preflight["receipt"]["algorithm"], "HMAC-SHA256")
            self.assertFalse(preflight["policy"]["map"]["includeSubdomains"])
            self.assertEqual(
                preflight["quota_exposure"],
                {
                    "map_requests": 1,
                    "crawl_page_cap": 3,
                    "pricing_must_be_rechecked": True,
                },
            )
            self.assertNotIn("truncated", preflight["map_summary"])
            self.assertEqual(
                preflight["map_summary"],
                {
                    "returned_count": 5,
                    "accepted_count": 2,
                    "enumerated_count": 2,
                    "filtered_count": 3,
                    "rejected_count": 3,
                    "cap_reached": True,
                    "completeness": "unknown",
                },
            )
            site_map = json.loads(pathlib.Path(result["site_map"]).read_text())
            self.assertNotIn("truncated", site_map)
            self.assertEqual(site_map["filtered_count"], 3)
            summary = json.loads(pathlib.Path(result["run_summary"]).read_text())
            self.assertEqual(summary["counts"]["returned"], 5)
            self.assertEqual(summary["counts"]["accepted"], 2)
            self.assertEqual(summary["counts"]["filtered"], 3)
            self.assertEqual(summary["counts"]["rejected"], 3)
            self.assertTrue(summary["cap_reached"])
            self.assertEqual(summary["completeness"], "unknown")
            self.assertTrue(pathlib.Path(result["run_summary"]).is_file())
            self.assertEqual(json.loads(pathlib.Path(result["failures"]).read_text()), [])
            for artifact_key in ("preflight", "site_map", "enumerated_urls"):
                self.assertLessEqual(
                    pathlib.Path(result[artifact_key]).stat().st_size,
                    SITE.MAX_PREFLIGHT_BYTES,
                )

    def test_map_failure_still_creates_a_safe_exclusive_audit_run(self):
        class FailedMapClient:
            def map_site(self, payload):
                raise SITE.SiteError("firecrawl_rejected", "Firecrawl rejected the request.")

        with tempfile.TemporaryDirectory() as directory:
            scope = SITE.make_scope("https://example.com/docs", "/docs", 7, 2)
            result = SITE.run_preflight(
                scope,
                client=FailedMapClient(),
                api_key=API_KEY,
                output_root=pathlib.Path(directory),
                now=NOW,
            )
            self.assertEqual(result["status"], "failed")
            runs = list(pathlib.Path(directory).iterdir())
            self.assertEqual(len(runs), 1)
            summary_path = pathlib.Path(result["run_summary"])
            failures_path = pathlib.Path(result["failures"])
            self.assertTrue(summary_path.is_file())
            self.assertTrue(failures_path.is_file())
            summary = json.loads(summary_path.read_text())
            failures = json.loads(failures_path.read_text())
            self.assertEqual(summary["failure"], {"category": "firecrawl_rejected"})
            self.assertEqual(failures[0]["reason"], "firecrawl_rejected")
            self.assertEqual(summary["quota_exposure"]["crawl_page_cap"], 7)
            audit_text = summary_path.read_text() + failures_path.read_text()
            self.assertNotIn(API_KEY.decode(), audit_text)

    def test_oversized_map_artifacts_fail_before_preflight_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = SITE.make_scope("https://example.com/docs", "/docs", 1, 1)
            client = FakeClient(
                map_links=["https://example.com/docs/" + ("a" * 800)]
            )
            with mock.patch.object(SITE, "MAX_PREFLIGHT_BYTES", 512):
                result = SITE.run_preflight(
                    scope,
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    now=NOW,
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(
                result["error"]["category"], "preflight_artifact_too_large"
            )
            run_dir = pathlib.Path(result["run_dir"])
            self.assertFalse((run_dir / "preflight.json").exists())
            self.assertFalse((run_dir / "site-map.json").exists())
            self.assertFalse((run_dir / "enumerated-urls.txt").exists())
            summary = json.loads((run_dir / "run-summary.json").read_text())
            failures = json.loads((run_dir / "failures.json").read_text())
            self.assertEqual(
                summary["failure"], {"category": "preflight_artifact_too_large"}
            )
            self.assertEqual(
                failures[0]["reason"], "preflight_artifact_too_large"
            )

    def test_empty_or_fully_filtered_map_never_publishes_executable_preflight(self):
        cases = (
            ([], 0, 0),
            (
                [
                    "https://sub.example.com/docs/a",
                    "https://example.com/outside",
                ],
                2,
                2,
            ),
        )
        for links, returned_count, rejected_count in cases:
            with self.subTest(links=links), tempfile.TemporaryDirectory() as directory:
                scope = SITE.make_scope("https://example.com/docs", "/docs", 10, 1)
                result = SITE.run_preflight(
                    scope,
                    client=FakeClient(map_links=links),
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    now=NOW,
                )
                self.assertEqual(result["status"], "empty")
                self.assertEqual(result["error"]["category"], "empty_map")
                run_dir = pathlib.Path(result["run_dir"])
                self.assertFalse((run_dir / "preflight.json").exists())
                self.assertTrue((run_dir / "site-map.json").is_file())
                self.assertTrue((run_dir / "enumerated-urls.txt").is_file())
                self.assertEqual((run_dir / "enumerated-urls.txt").read_text(), "")
                summary = json.loads((run_dir / "run-summary.json").read_text())
                failures = json.loads((run_dir / "failures.json").read_text())
                self.assertEqual(summary["status"], "empty")
                self.assertEqual(summary["counts"]["returned"], returned_count)
                self.assertEqual(summary["counts"]["accepted"], 0)
                self.assertEqual(summary["counts"]["filtered"], rejected_count)
                self.assertEqual(summary["counts"]["rejected"], rejected_count)
                self.assertFalse(summary["cap_reached"])
                self.assertEqual(summary["completeness"], "unknown")
                self.assertEqual(failures[0]["reason"], "empty_map")
                site_map = json.loads((run_dir / "site-map.json").read_text())
                self.assertNotIn("truncated", site_map)
                self.assertEqual(site_map["accepted_count"], 0)
                self.assertEqual(site_map["filtered_count"], rejected_count)
                self.assertFalse(site_map["cap_reached"])
                self.assertEqual(site_map["completeness"], "unknown")

        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with (
                mock.patch.object(SITE, "_load_api_key", return_value=API_KEY),
                mock.patch.object(
                    SITE, "FirecrawlClient", return_value=FakeClient(map_links=[])
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = SITE.main(
                    [
                        "--site-url",
                        "https://example.com/docs",
                        "--path-prefix",
                        "/docs",
                        "--limit",
                        "10",
                        "--max-depth",
                        "1",
                        "--output-root",
                        directory,
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "empty")

    def test_tampered_preflight_scope_or_artifacts_are_rejected_before_crawl(self):
        with tempfile.TemporaryDirectory() as directory:
            scope, _, result = make_preflight(directory)
            preflight_path = pathlib.Path(result["preflight"])
            tampered = json.loads(preflight_path.read_text())
            tampered["request"]["limit"] = 99
            preflight_path.write_text(json.dumps(tampered), encoding="utf-8")
            client = FakeClient()
            with self.assertRaisesRegex(SITE.SiteError, "signature"):
                SITE.run_execute(
                    scope,
                    preflight_path=preflight_path,
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                )
            self.assertEqual(client.crawl_payloads, [])

        with tempfile.TemporaryDirectory() as directory:
            scope, _, result = make_preflight(directory)
            pathlib.Path(result["enumerated_urls"]).write_text(
                "https://example.com/docs/changed\n", encoding="utf-8"
            )
            client = FakeClient()
            with self.assertRaisesRegex(SITE.SiteError, "content has changed"):
                SITE.run_execute(
                    scope,
                    preflight_path=pathlib.Path(result["preflight"]),
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                )
            self.assertEqual(client.crawl_payloads, [])

    def test_expired_or_parameter_mismatched_preflight_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            scope, _, result = make_preflight(directory)
            client = FakeClient()
            with self.assertRaisesRegex(SITE.SiteError, "expired"):
                SITE.run_execute(
                    scope,
                    preflight_path=pathlib.Path(result["preflight"]),
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(hours=2),
                )
            with self.assertRaisesRegex(SITE.SiteError, "signature"):
                SITE.run_execute(
                    scope,
                    preflight_path=pathlib.Path(result["preflight"]),
                    client=client,
                    api_key=b"fc-different-key",
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                )
            mismatched = SITE.make_scope("https://example.com/docs", "/docs", 2, 1)
            with self.assertRaisesRegex(SITE.SiteError, "parameters"):
                SITE.run_execute(
                    mismatched,
                    preflight_path=pathlib.Path(result["preflight"]),
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                )
            self.assertEqual(client.crawl_payloads, [])


class ExecuteTests(unittest.TestCase):
    def test_execute_uses_fixed_crawl_policy_and_archives_only_signed_map_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            scope, _, preflight = make_preflight(directory)
            client = FakeClient(
                crawl_documents=[
                    {
                        "markdown": "# Root\n\nSafe",
                        "metadata": {"sourceURL": "https://example.com/docs"},
                    },
                    {
                        "markdown": "# External",
                        "metadata": {"sourceURL": "https://evil.example/docs"},
                    },
                    {
                        "markdown": "# Not mapped",
                        "metadata": {"sourceURL": "https://example.com/docs/new"},
                    },
                ]
            )
            result = SITE.run_execute(
                scope,
                preflight_path=pathlib.Path(preflight["preflight"]),
                client=client,
                api_key=API_KEY,
                output_root=pathlib.Path(directory),
                crawl_timeout=30,
                poll_seconds=0.25,
                now=NOW + timedelta(minutes=1),
                sleep=lambda _: None,
            )
            payload = client.crawl_payloads[0]
            self.assertFalse(payload["allowSubdomains"])
            self.assertFalse(payload["allowExternalLinks"])
            self.assertTrue(payload["ignoreQueryParameters"])
            self.assertFalse(payload["ignoreRobotsTxt"])
            self.assertFalse(payload["crawlEntireDomain"])
            self.assertEqual(payload["maxDiscoveryDepth"], 1)
            scrape = payload["scrapeOptions"]
            self.assertFalse(scrape["storeInCache"])
            self.assertFalse(scrape["skipTlsVerification"])
            self.assertEqual(scrape["proxy"], "basic")
            self.assertNotIn("zeroDataRetention", json.dumps(payload))
            self.assertNotIn(API_KEY.decode(), json.dumps(payload))
            self.assertNotIn("headers", scrape)
            self.assertNotIn("actions", scrape)

            run_dir = pathlib.Path(result["run_dir"])
            for name in (
                "preflight.json",
                "site-map.json",
                "enumerated-urls.txt",
                "archive-manifest.jsonl",
                "run-summary.json",
                "failures.json",
                "handoff.json",
                "web",
            ):
                self.assertTrue((run_dir / name).exists(), name)
            handoff = json.loads((run_dir / "handoff.json").read_text())
            self.assertTrue(handoff["scope"]["discovery_performed"])
            self.assertEqual(handoff["scope"]["container_kind"], "bounded_site")
            self.assertEqual(handoff["quota_exposure"]["crawl_page_cap"], 3)
            artifact_kinds = {artifact["kind"] for artifact in handoff["artifacts"]}
            self.assertTrue(
                {
                    "preflight",
                    "site_map",
                    "enumerated_url_list",
                    "archive_manifest",
                    "run_summary",
                    "failures",
                    "web_content",
                }.issubset(artifact_kinds)
            )
            summary = json.loads((run_dir / "run-summary.json").read_text())
            failures = json.loads((run_dir / "failures.json").read_text())
            self.assertEqual(summary["failures"], failures)
            self.assertIn(
                "not_returned_by_crawl", {row["reason"] for row in failures}
            )
            reasons = {row["reason"] for row in summary["rejected_crawl_documents"]}
            self.assertIn("outside_scope", reasons)
            self.assertIn("not_in_signed_preflight", reasons)
            self.assertEqual(
                summary["quota_exposure"],
                {
                    "map_requests": 1,
                    "crawl_page_cap": 3,
                    "pricing_must_be_rechecked": True,
                },
            )
            audit = summary["preflight_audit"]
            self.assertEqual(
                audit["source_preflight"]["sha256"],
                hashlib.sha256(pathlib.Path(preflight["preflight"]).read_bytes()).hexdigest(),
            )
            for copied in audit["copied_artifacts"].values():
                copied_path = pathlib.Path(copied["path"])
                self.assertEqual(copied_path.parent, run_dir)
                self.assertEqual(copied["sha256"], hashlib.sha256(copied_path.read_bytes()).hexdigest())
            self.assertEqual(
                audit["signed_artifact_hashes"]["site_map"],
                audit["copied_artifacts"]["site_map"]["sha256"],
            )
            self.assertEqual(
                audit["signed_artifact_hashes"]["enumerated_url_list"],
                audit["copied_artifacts"]["enumerated_url_list"]["sha256"],
            )

    def test_signed_url_rejection_reason_is_consistent_across_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            scope, _, preflight = make_preflight(
                directory,
                links=[
                    "https://example.com/docs/a",
                    "https://example.com/docs/b",
                ],
                limit=2,
            )
            client = FakeClient(
                crawl_documents=[
                    {
                        "markdown": "",
                        "metadata": {"sourceURL": "https://example.com/docs/a"},
                    },
                    {
                        "markdown": "12345",
                        "metadata": {"sourceURL": "https://example.com/docs/b"},
                    },
                ]
            )
            with mock.patch.object(SITE, "MAX_MARKDOWN_BYTES", 4):
                result = SITE.run_execute(
                    scope,
                    preflight_path=pathlib.Path(preflight["preflight"]),
                    client=client,
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                    sleep=lambda _: None,
                )
            run_dir = pathlib.Path(result["run_dir"])
            summary = json.loads((run_dir / "run-summary.json").read_text())
            manifest = [
                json.loads(line)
                for line in (run_dir / "archive-manifest.jsonl").read_text().splitlines()
            ]
            failures = json.loads((run_dir / "failures.json").read_text())
            handoff = json.loads((run_dir / "handoff.json").read_text())
            expected = ["missing_markdown", "page_too_large"]
            self.assertEqual([row["reason"] for row in manifest], expected)
            self.assertEqual([row["reason"] for row in failures], expected)
            self.assertEqual(summary["failures"], failures)
            self.assertEqual([row["reason"] for row in handoff["failures"]], expected)
            self.assertEqual(
                [row["reason"] for row in summary["rejected_crawl_documents"]],
                expected,
            )

    def test_transport_and_job_failures_are_sanitized_and_consistent(self):
        class TransportFailureClient(FakeClient):
            def start_crawl(self, payload):
                self.crawl_payloads.append(payload)
                raise SITE.SiteError(
                    "firecrawl_unavailable",
                    "transport-sensitive-response-must-not-persist",
                )

        class JobFailureClient(FakeClient):
            def crawl_status(self, job_id):
                self.status_calls.append(job_id)
                return {
                    "success": True,
                    "status": "failed",
                    "detail": "job-sensitive-response-must-not-persist",
                }

        cases = (
            (
                TransportFailureClient,
                "firecrawl_unavailable",
                "transport-sensitive-response-must-not-persist",
            ),
            (
                JobFailureClient,
                "firecrawl_crawl_failed",
                "job-sensitive-response-must-not-persist",
            ),
        )
        for client_type, category, forbidden_text in cases:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as directory:
                scope, _, preflight = make_preflight(directory)
                result = SITE.run_execute(
                    scope,
                    preflight_path=pathlib.Path(preflight["preflight"]),
                    client=client_type(),
                    api_key=API_KEY,
                    output_root=pathlib.Path(directory),
                    crawl_timeout=30,
                    poll_seconds=0.25,
                    now=NOW + timedelta(minutes=1),
                    sleep=lambda _: None,
                )
                run_dir = pathlib.Path(result["run_dir"])
                summary = json.loads((run_dir / "run-summary.json").read_text())
                manifest = [
                    json.loads(line)
                    for line in (run_dir / "archive-manifest.jsonl").read_text().splitlines()
                ]
                failures = json.loads((run_dir / "failures.json").read_text())
                handoff = json.loads((run_dir / "handoff.json").read_text())
                self.assertEqual(
                    summary["crawl_failure"],
                    {"stage": "crawl", "reason": category, "category": category},
                )
                self.assertEqual(summary["failures"], failures)
                self.assertTrue(all(row["reason"] == category for row in manifest))
                self.assertTrue(
                    all(row["error_category"] == category for row in manifest)
                )
                self.assertTrue(
                    all(
                        row["reason"] == category and row["category"] == category
                        for row in failures
                    )
                )
                self.assertEqual(handoff["failures"], failures)
                persisted = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in run_dir.rglob("*")
                    if path.is_file()
                )
                self.assertNotIn(forbidden_text, persisted)
                self.assertNotIn(API_KEY.decode(), persisted)

    def test_execute_flag_and_preflight_are_both_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                SITE.parse_args(
                    [
                        "--site-url", "https://example.com/docs",
                        "--path-prefix", "/docs",
                        "--limit", "10",
                        "--max-depth", "1",
                        "--execute",
                    ]
                )
            with self.assertRaises(SystemExit):
                SITE.parse_args(
                    [
                        "--site-url", "https://example.com/docs",
                        "--path-prefix", "/docs",
                        "--limit", "10",
                        "--max-depth", "1",
                        "--preflight", "/tmp/preflight.json",
                    ]
                )


class CredentialTests(unittest.TestCase):
    def test_api_key_is_only_loaded_from_env_or_private_default_file(self):
        self.assertEqual(SITE._load_api_key({SITE.API_KEY_ENV: API_KEY.decode()}), API_KEY)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "key"
            path.write_text(API_KEY.decode(), encoding="ascii")
            os.chmod(path, 0o644)
            with mock.patch.object(SITE, "API_KEY_FILE", path):
                with self.assertRaises(SITE.SiteError):
                    SITE._load_api_key({})
            os.chmod(path, 0o600)
            with mock.patch.object(SITE, "API_KEY_FILE", path):
                self.assertEqual(SITE._load_api_key({}), API_KEY)

    def test_authenticated_firecrawl_requests_refuse_redirects(self):
        request = urllib.request.Request(
            SITE.API_BASE + "/map",
            data=b"{}",
            method="POST",
            headers={"Authorization": "Bearer redacted"},
        )
        self.assertIsNone(
            SITE._NoRedirectHandler().redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://attacker.invalid/capture",
            )
        )

        class RedirectingOpener:
            def open(self, outgoing, timeout):
                raise urllib.error.HTTPError(
                    outgoing.full_url,
                    302,
                    "Found",
                    {"Location": "https://attacker.invalid/capture"},
                    None,
                )

        client = SITE.FirecrawlClient(API_KEY, opener=RedirectingOpener())
        with self.assertRaises(SITE.SiteError) as raised:
            client.map_site({"url": "https://example.com", "limit": 1})
        self.assertEqual(raised.exception.category, "firecrawl_redirect_refused")
        self.assertNotIn(API_KEY.decode(), raised.exception.message)

    def test_parser_exposes_no_key_header_action_or_monitor_options(self):
        destinations = {action.dest for action in SITE.build_parser()._actions}
        self.assertNotIn("api_key", destinations)
        self.assertNotIn("headers", destinations)
        self.assertNotIn("actions", destinations)
        self.assertNotIn("monitor", destinations)


if __name__ == "__main__":
    unittest.main()
