import importlib.util
import json
import pathlib
import sys
import unittest
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fxtwitter_search", ROOT / "scripts" / "fxtwitter_search.py"
)
FX = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = FX
SPEC.loader.exec_module(FX)


def base_status(**overrides):
    value = {
        "type": "status",
        "id": "2000000000000000001",
        "text": "A public X post",
        "created_timestamp": 1785369600,
        "created_at": "2026-07-30T00:00:00Z",
        "likes": 12,
        "reposts": 3,
        "quotes": 2,
        "replies": 4,
        "views": 120,
        "bookmarks": 5,
        "lang": "en",
        "author": {
            "name": "Example Author",
            "screen_name": "example",
        },
    }
    value.update(overrides)
    return value


class FxTwitterSearchTests(unittest.TestCase):
    def setUp(self):
        self.retrieved_at = "2026-07-30T12:00:00Z"

    def normalize(self, status):
        return FX.normalize_status(
            status,
            query="GPT 5.6",
            rank=1,
            retrieved_at=self.retrieved_at,
        )

    def test_plain_post_maps_to_candidate_schema(self):
        candidate = self.normalize(base_status())
        self.assertEqual(candidate["content_type"], "x_post")
        self.assertEqual(candidate["candidate_id"], "x:2000000000000000001")
        self.assertEqual(
            candidate["canonical_url"],
            "https://x.com/example/status/2000000000000000001",
        )
        self.assertFalse(candidate["access"]["login_state_used"])
        self.assertEqual(candidate["metrics"]["comments"], 4)
        self.assertEqual(candidate["metrics"]["shares"], 3)

    def test_quote_keeps_nested_public_post_metadata(self):
        quote = base_status(
            id="1999999999999999999",
            text="Quoted body",
            author={"name": "Quoted", "screen_name": "quoted"},
        )
        candidate = self.normalize(base_status(text="My comment", quote=quote))
        self.assertEqual(candidate["content_type"], "x_quote_post")
        nested = candidate["platform_fields"]["quoted_post"]
        self.assertEqual(nested["id"], "1999999999999999999")
        self.assertEqual(nested["author"]["screen_name"], "quoted")
        self.assertEqual(nested["text"], "Quoted body")

    def test_article_returns_preview_but_never_full_blocks(self):
        article = {
            "id": "2032093606551707648",
            "title": "A Long X Article",
            "preview_text": "Public preview",
            "cover_media": {
                "media_info": {
                    "__typename": "ApiImage",
                    "original_img_url": "https://pbs.twimg.com/media/cover.jpg",
                }
            },
            "content": {
                "blocks": [{"text": "FULL BODY MUST NOT LEAK INTO SEARCH"}],
                "entityMap": [],
            },
        }
        candidate = self.normalize(base_status(article=article))
        self.assertEqual(candidate["content_type"], "x_article")
        self.assertEqual(candidate["title"], "A Long X Article")
        projected = candidate["platform_fields"]["article"]
        self.assertEqual(projected["id"], "2032093606551707648")
        self.assertEqual(projected["preview_text"], "Public preview")
        self.assertNotIn("content", projected)
        self.assertNotIn("FULL BODY", json.dumps(candidate))

    def test_quote_can_contain_article_metadata(self):
        quote = base_status(
            id="1999999999999999999",
            article={
                "id": "1888888888888888888",
                "title": "Quoted article",
                "preview_text": "Quoted preview",
            },
        )
        candidate = self.normalize(base_status(quote=quote))
        nested_article = candidate["platform_fields"]["quoted_post"]["article"]
        self.assertEqual(nested_article["title"], "Quoted article")

    def test_days_filter_uses_public_timestamp_and_drops_unknown_time(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        statuses = [
            base_status(id="recent", created_timestamp=now.timestamp() - 3600),
            base_status(id="old", created_timestamp=now.timestamp() - 172800),
            base_status(id="unknown", created_timestamp=None),
        ]
        filtered = FX.filter_by_days(statuses, 1, now=now)
        self.assertEqual([item["id"] for item in filtered], ["recent"])

    def test_envelope_marks_anonymous_third_party_coverage(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        envelope = FX.make_envelope(
            query="GPT 5.6",
            limit=5,
            days=None,
            feed="latest",
            payload={
                "code": 200,
                "results": [base_status()],
                "cursor": {"top": "top", "bottom": "next"},
            },
            error=None,
            now=now,
        )
        self.assertEqual(envelope["routes"][0]["backend"], "fxtwitter-public")
        self.assertFalse(envelope["routes"][0]["login_state_used"])
        self.assertTrue(envelope["coverage"][0]["truncated"])
        self.assertEqual(len(envelope["candidates"]), 1)

    def test_error_envelope_is_safe_and_requests_fallback(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        error = FX.SearchError(
            "rate_limited",
            "FxTwitter returned HTTP 429; continue to the configured X fallback chain.",
        )
        envelope = FX.make_envelope(
            query="GPT 5.6",
            limit=5,
            days=None,
            feed="latest",
            payload=None,
            error=error,
            now=now,
        )
        self.assertEqual(envelope["routes"][0]["status"], "failed")
        self.assertEqual(envelope["errors"][0]["category"], "rate_limited")
        self.assertEqual(envelope["candidates"], [])


if __name__ == "__main__":
    unittest.main()
