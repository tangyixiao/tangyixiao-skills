#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = Path(
    tempfile.mkdtemp(prefix="yichen-content-archive-overwrite-", dir="/tmp")
)
print(f"TEST_ARTIFACT_ROOT={ARTIFACT_ROOT}", file=sys.stderr)


def load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEPFUN = load_script("xiaoyuzhou_stepfun")
OPENCLI = load_script("xiaoyuzhou_opencli")


class XiaoyuzhouStepfunOverwriteTest(unittest.TestCase):
    def args(self, *, resume=False):
        return SimpleNamespace(
            title="",
            output_dir=None,
            inspect_only=False,
            resume=resume,
            download_only=True,
            language="zh",
            hotwords="",
            request_gap=0.0,
        )

    def test_default_repeat_uses_new_dir_and_safe_resume_reuses(self):
        default_root = ARTIFACT_ROOT / "stepfun-default"
        url = "https://www.xiaoyuzhoufm.com/episode/episode-safe"

        def fake_download(_url, destination):
            with destination.open("xb") as handle:
                handle.write(b"complete-audio")

        with (
            mock.patch.object(STEPFUN, "DEFAULT_OUTPUT_ROOT", default_root),
            mock.patch.object(STEPFUN, "fetch_text", return_value="<html/>"),
            mock.patch.object(
                STEPFUN,
                "extract_episode",
                return_value=("Episode", "https://media.xyzcdn.net/audio.m4a"),
            ),
            mock.patch.object(STEPFUN, "download", side_effect=fake_download),
        ):
            first = STEPFUN.process_episode(self.args(), url, batch_mode=False)
            first_dir = Path(first["output_dir"])
            metadata_path = first_dir / "source.json"
            original_metadata = metadata_path.read_bytes()
            original_source = (first_dir / "source.m4a").read_bytes()

            second = STEPFUN.process_episode(self.args(), url, batch_mode=False)
            second_dir = Path(second["output_dir"])
            self.assertNotEqual(first_dir, second_dir)
            self.assertEqual(second_dir.name, "xiaoyuzhou-stepfun-episode-safe-run-2")
            self.assertEqual(metadata_path.read_bytes(), original_metadata)
            self.assertEqual((first_dir / "source.m4a").read_bytes(), original_source)

            resumed = STEPFUN.process_episode(
                self.args(resume=True),
                url,
                batch_mode=False,
            )
            self.assertEqual(resumed["event"], "REUSED")
            self.assertEqual(Path(resumed["output_dir"]), first_dir)
            self.assertEqual(metadata_path.read_bytes(), original_metadata)

    def test_resume_rejects_corrupt_source_without_rewriting_metadata(self):
        default_root = ARTIFACT_ROOT / "stepfun-corrupt"
        url = "https://www.xiaoyuzhoufm.com/episode/episode-corrupt"

        def fake_download(_url, destination):
            with destination.open("xb") as handle:
                handle.write(b"valid-before-corruption")

        with (
            mock.patch.object(STEPFUN, "DEFAULT_OUTPUT_ROOT", default_root),
            mock.patch.object(STEPFUN, "fetch_text", return_value="<html/>"),
            mock.patch.object(
                STEPFUN,
                "extract_episode",
                return_value=("Episode", "https://media.xyzcdn.net/audio.m4a"),
            ),
            mock.patch.object(STEPFUN, "download", side_effect=fake_download),
        ):
            first = STEPFUN.process_episode(self.args(), url, batch_mode=False)
            output_dir = Path(first["output_dir"])
            metadata_path = output_dir / "source.json"
            original_metadata = metadata_path.read_bytes()
            with (output_dir / "source.m4a").open("ab") as handle:
                handle.write(b"-corrupt")

            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                STEPFUN.process_episode(
                    self.args(resume=True),
                    url,
                    batch_mode=False,
                )
            self.assertEqual(metadata_path.read_bytes(), original_metadata)


class XiaoyuzhouOpencliOverwriteTest(unittest.TestCase):
    def test_explicit_existing_dir_rejected_and_default_conflict_gets_new_dir(self):
        existing = ARTIFACT_ROOT / "opencli-existing"
        existing.mkdir()
        sentinel = existing / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "排他创建"):
            OPENCLI.prepare_output_dir(
                str(existing),
                ARTIFACT_ROOT / "unused-default",
            )
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

        default_base = ARTIFACT_ROOT / "opencli-default"
        default_base.mkdir()
        (default_base / "old.txt").write_text("old", encoding="utf-8")
        selected = OPENCLI.prepare_output_dir(None, default_base)
        self.assertEqual(selected.name, "opencli-default-run-2")
        self.assertEqual((default_base / "old.txt").read_text(encoding="utf-8"), "old")

    def test_overwrite_requires_exact_independent_confirmation(self):
        existing = ARTIFACT_ROOT / "opencli-overwrite-confirm"
        existing.mkdir()
        sentinel = existing / "episodes.json"
        sentinel.write_text("original", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "高摩擦确认"):
            OPENCLI.prepare_output_dir(
                str(existing),
                ARTIFACT_ROOT / "unused",
                overwrite=True,
                confirmation="",
            )
        with self.assertRaisesRegex(ValueError, "高摩擦确认"):
            OPENCLI.prepare_output_dir(
                str(existing),
                ARTIFACT_ROOT / "unused",
                overwrite=True,
                confirmation=str(existing) + "-wrong",
            )
        selected = OPENCLI.prepare_output_dir(
            str(existing),
            ARTIFACT_ROOT / "unused",
            overwrite=True,
            confirmation=str(existing.resolve()),
        )
        self.assertEqual(selected, existing.resolve())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")

    def test_exclusive_episode_export_preserves_existing_file(self):
        output_dir = ARTIFACT_ROOT / "opencli-export-existing"
        output_dir.mkdir()
        existing = output_dir / "episodes.json"
        existing.write_text("do-not-replace", encoding="utf-8")
        rows = [{"eid": "episode1"}]

        with self.assertRaises(FileExistsError):
            OPENCLI.export_episodes(
                "podcast1",
                rows,
                output_dir,
                overwrite=False,
            )
        self.assertEqual(existing.read_text(encoding="utf-8"), "do-not-replace")
        self.assertFalse((output_dir / "episode_ids.txt").exists())


if __name__ == "__main__":
    unittest.main()
