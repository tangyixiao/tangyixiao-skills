import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "x_known_url", ROOT / "scripts" / "x_known_url.py"
)
XURL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = XURL
SPEC.loader.exec_module(XURL)


def status(**overrides):
    value = {
        "type": "status",
        "id": "2000000000000000001",
        "text": "outer post",
        "created_at": "2026-07-30T12:00:00Z",
        "likes": 3,
        "reposts": 2,
        "quotes": 1,
        "replies": 4,
        "bookmarks": 5,
        "views": 100,
        "lang": "en",
        "author": {
            "id": "42",
            "name": "Example",
            "screen_name": "example",
            "followers": 99,
            "verification": {"verified": True},
        },
    }
    value.update(overrides)
    return value


class KnownXUrlTests(unittest.TestCase):
    def test_status_url_is_normalized(self):
        parsed = XURL.parse_known_url(
            "https://twitter.com/example/status/2000000000000000001?s=20"
        )
        self.assertEqual(parsed["input_kind"], "x_status_url")
        self.assertEqual(parsed["id"], "2000000000000000001")
        self.assertEqual(
            parsed["canonical_url"],
            "https://x.com/example/status/2000000000000000001",
        )

    def test_article_url_is_recognized(self):
        parsed = XURL.parse_known_url(
            "https://x.com/i/article/2032093606551707648"
        )
        self.assertEqual(parsed["input_kind"], "x_article_url")
        self.assertEqual(parsed["id"], "2032093606551707648")

    def test_non_x_host_is_rejected(self):
        with self.assertRaises(XURL.KnownUrlError):
            XURL.parse_known_url("https://example.com/user/status/123")

    def test_plain_post_normalizes_without_login(self):
        normalized = XURL.normalize_status(status())
        self.assertEqual(normalized["content_type"], "x_post")
        self.assertEqual(normalized["author"]["screen_name"], "example")
        self.assertEqual(normalized["metrics"]["bookmarks"], 5)

    def test_quote_keeps_nested_post(self):
        normalized = XURL.normalize_status(
            status(
                quote=status(
                    id="1999999999999999999",
                    text="quoted post",
                    author={
                        "id": "43",
                        "name": "Quoted",
                        "screen_name": "quoted",
                    },
                )
            )
        )
        self.assertEqual(normalized["content_type"], "x_quote_post")
        self.assertEqual(normalized["quote"]["text"], "quoted post")
        self.assertEqual(normalized["quote"]["author"]["screen_name"], "quoted")

    def test_exact_article_parent_ignores_noise_and_accepts_nested_quote(self):
        noise = status(article={"id": "111"})
        exact_quote = status(
            id="1888888888888888888",
            article={"id": "2032093606551707648"},
        )
        outer = status(quote=exact_quote)
        parent = XURL.find_article_parent(
            [noise, outer],
            "2032093606551707648",
        )
        self.assertEqual(parent["id"], "1888888888888888888")

    def test_resolve_article_rechecks_fetched_parent_and_article_identity(self):
        article_id = "2032093606551707648"
        parent_id = "1888888888888888888"
        search_payload = {
            "results": [status(id=parent_id, article={"id": article_id})]
        }
        for fetched in (
            status(id="1777777777777777777", article={"id": article_id}),
            status(id=parent_id, article={"id": "1111111111111111111"}),
        ):
            with self.subTest(fetched_id=fetched["id"]), mock.patch.object(
                XURL, "fetch_json", return_value=search_payload
            ), mock.patch.object(XURL, "fetch_status", return_value=fetched):
                with self.assertRaises(XURL.KnownUrlError) as raised:
                    XURL.resolve_article(article_id, timeout=30)
            self.assertEqual(raised.exception.category, "source_identity_mismatch")

    def test_article_markdown_renders_structure_links_and_media(self):
        article = {
            "id": "2032093606551707648",
            "title": "Article title",
            "preview_text": "Preview",
            "content": {
                "blocks": [
                    {
                        "type": "header-two",
                        "text": "Heading",
                        "entityRanges": [],
                    },
                    {
                        "type": "unstyled",
                        "text": "Read this site",
                        "entityRanges": [{"key": 1, "offset": 10, "length": 4}],
                    },
                    {
                        "type": "unordered-list-item",
                        "text": "A list item",
                        "entityRanges": [],
                    },
                    {
                        "type": "blockquote",
                        "text": "A quote",
                        "entityRanges": [],
                    },
                    {
                        "type": "atomic",
                        "text": " ",
                        "entityRanges": [{"key": 0, "offset": 0, "length": 1}],
                    },
                ],
                "entityMap": [
                    {
                        "key": "0",
                        "value": {
                            "type": "MEDIA",
                            "data": {
                                "caption": "Chart",
                                "mediaItems": [{"mediaId": "1234567890"}],
                            },
                        },
                    },
                    {
                        "key": "1",
                        "value": {
                            "type": "LINK",
                            "data": {"url": "https://example.com"},
                        },
                    },
                ],
            },
            "media_entities": [
                {
                    "media_id": "1234567890",
                    "media_info": {
                        "original_img_url": "https://pbs.twimg.com/media/chart.jpg"
                    },
                }
            ],
        }
        markdown = XURL.render_article_markdown(article)
        self.assertIn("## Heading", markdown)
        self.assertIn("[site](https://example.com)", markdown)
        self.assertIn("- A list item", markdown)
        self.assertIn("> A quote", markdown)
        self.assertIn(
            "![Chart](https://pbs.twimg.com/media/chart.jpg)",
            markdown,
        )
        self.assertEqual(XURL.article_media(article)[0]["kind"], "photo")

    def test_article_video_projection_keeps_signal_and_never_renders_poster_as_photo(self):
        poster_url = "https://pbs.twimg.com/media/video-poster.jpg"
        article = {
            "id": "2032093606551707648",
            "title": "Video article",
            "content": {
                "blocks": [
                    {"type": "unstyled", "text": "Body", "entityRanges": []},
                    {
                        "type": "atomic",
                        "text": " ",
                        "entityRanges": [{"key": 0, "offset": 0, "length": 1}],
                    },
                ],
                "entityMap": [
                    {
                        "key": "0",
                        "value": {
                            "type": "MEDIA",
                            "data": {
                                "caption": "Video",
                                "mediaItems": [{"mediaId": "video-1234567890"}],
                            },
                        },
                    }
                ],
            },
            "media_entities": [
                {
                    "media_id": "video-1234567890",
                    "media_info": {
                        "__typename": "ApiVideo",
                        "thumbnail_url": poster_url,
                        "duration_millis": 1234,
                        "variants": [
                            {
                                "type": "video/mp4",
                                "bitrate": 832000,
                                "url": "https://video.twimg.com/ext_tw_video/123/pu/vid/video.mp4?token=redacted",
                            }
                        ],
                    },
                }
            ],
        }
        projected = XURL.article_projection(article)
        media = projected["media"][0]
        self.assertEqual(media["kind"], "video")
        self.assertEqual(media["url"], poster_url)
        self.assertEqual(media["video_info"]["variant_count"], 1)
        self.assertEqual(
            media["video_info"]["variants"][0]["url"],
            "https://video.twimg.com/ext_tw_video/123/pu/vid/video.mp4",
        )
        self.assertNotIn(poster_url, projected["body_markdown"])

    def test_article_thumbnail_without_type_is_projected_unknown(self):
        article = {
            "media_entities": [
                {
                    "media_id": "unknown-1",
                    "media_info": {
                        "thumbnail_url": "https://pbs.twimg.com/media/ambiguous.jpg"
                    },
                }
            ]
        }
        media = XURL.article_media(article)[0]
        self.assertEqual(media["kind"], "unknown")
        self.assertEqual(XURL.media_lookup(article), {})

    def test_article_projection_contains_body_but_not_raw_draftjs(self):
        article = {
            "id": "2032093606551707648",
            "title": "Article title",
            "content": {
                "blocks": [
                    {"type": "unstyled", "text": "Full body", "entityRanges": []}
                ],
                "entityMap": [],
            },
            "media_entities": [],
        }
        projected = XURL.article_projection(article)
        self.assertEqual(projected["body_markdown"], "Full body")
        self.assertTrue(projected["render_complete"])
        self.assertEqual(projected["render_errors"], [])
        self.assertNotIn("content", projected)

    def test_article_render_audit_rejects_malformed_block_atomic_and_link(self):
        article = {
            "id": "2032093606551707648",
            "title": "Malformed article",
            "content": {
                "blocks": [
                    {"type": "unstyled", "text": "Visible body", "entityRanges": []},
                    None,
                    {
                        "type": "atomic",
                        "text": " ",
                        "entityRanges": [{"key": 0, "offset": 0, "length": 1}],
                    },
                    {
                        "type": "unstyled",
                        "text": "bad link",
                        "entityRanges": [
                            {"key": 1, "offset": "zero", "length": 3}
                        ],
                    },
                    {"type": "unstyled", "text": "", "entityRanges": []},
                ],
                "entityMap": [
                    {
                        "key": "0",
                        "value": {
                            "type": "MEDIA",
                            "data": {"mediaItems": [{"mediaId": "missing-media"}]},
                        },
                    },
                    {
                        "key": "1",
                        "value": {
                            "type": "LINK",
                            "data": {"url": "https://example.com"},
                        },
                    },
                ],
            },
            "media_entities": [],
        }
        projected = XURL.article_projection(article)
        self.assertIn("Visible body", projected["body_markdown"])
        self.assertFalse(projected["render_complete"])
        categories = {error["category"] for error in projected["render_errors"]}
        self.assertIn("block_not_object", categories)
        self.assertIn("atomic_media_unrenderable", categories)
        self.assertIn("link_range_invalid", categories)
        self.assertEqual(projected["render_audit"]["status"], "incomplete")

    def test_authenticated_fallbacks_are_authorization_gated(self):
        parsed = XURL.parse_known_url(
            "https://x.com/example/status/2000000000000000001"
        )
        fallbacks = XURL.authenticated_fallbacks(
            parsed,
            parsed["canonical_url"],
        )
        self.assertEqual(
            [item["backend"] for item in fallbacks],
            ["opencli-twitter", "xreach"],
        )
        self.assertTrue(
            all(item["requires_current_turn_authorization"] for item in fallbacks)
        )
        self.assertTrue(all(item["login_state_used"] for item in fallbacks))

    def test_status_article_uses_opencli_article_fallback(self):
        parsed = XURL.parse_known_url(
            "https://x.com/example/status/2000000000000000001"
        )
        fallbacks = XURL.authenticated_fallbacks(
            parsed,
            parsed["canonical_url"],
            "x_article",
        )
        self.assertEqual(
            fallbacks[0]["argv"],
            [
                "opencli",
                "twitter",
                "article",
                parsed["canonical_url"],
                "-f",
                "md",
            ],
        )

    def test_status_article_with_incomplete_body_uses_jina(self):
        status = {
            "type": "status",
            "id": "2000000000000000001",
            "url": "https://x.com/example/status/2000000000000000001",
            "author": {"screen_name": "example"},
            "article": {
                "id": "2000000000000000002",
                "title": "Incomplete article",
            },
        }
        with mock.patch.object(
            XURL,
            "fetch_status",
            return_value=status,
        ), mock.patch.object(
            XURL,
            "fetch_jina",
            return_value="# Public article fallback",
        ) as jina:
            result = XURL.read_known_url(
                status["url"],
                timeout=30,
                allow_jina_fallback=True,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["content"]["content_type"], "x_article")
        self.assertEqual(result["route"]["backend_used"], "jina-reader")
        jina.assert_called_once_with(status["url"], timeout=30)
        self.assertEqual(result["authenticated_fallbacks"], [])

    def test_public_jina_fallback_does_not_use_login_state(self):
        with mock.patch.object(
            XURL,
            "fetch_status",
            side_effect=XURL.KnownUrlError("not_found", "missing"),
        ), mock.patch.object(
            XURL,
            "fetch_jina",
            return_value="# Public fallback",
        ):
            result = XURL.read_known_url(
                "https://x.com/example/status/2000000000000000001",
                timeout=30,
                allow_jina_fallback=True,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["route"]["backend_used"], "jina-reader")
        self.assertFalse(result["route"]["login_state_used"])
        self.assertEqual(result["authenticated_fallbacks"], [])

    def test_failed_public_chain_only_returns_authorized_fallback_plan(self):
        with mock.patch.object(
            XURL,
            "fetch_status",
            side_effect=XURL.KnownUrlError("not_found", "missing"),
        ), mock.patch.object(
            XURL,
            "fetch_jina",
            side_effect=XURL.KnownUrlError("login_wall", "login"),
        ):
            result = XURL.read_known_url(
                "https://x.com/example/status/2000000000000000001",
                timeout=30,
                allow_jina_fallback=True,
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [item["backend"] for item in result["authenticated_fallbacks"]],
            ["opencli-twitter", "xreach"],
        )
        self.assertTrue(
            all(
                item["requires_current_turn_authorization"]
                for item in result["authenticated_fallbacks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
