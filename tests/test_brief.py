"""Exercise evidence freshness, safe cache writes and portable brief use."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/brief.py"
spec = importlib.util.spec_from_file_location("trurl_brief", SCRIPT)
brief = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brief)


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "model").mkdir()
        self.profile = {"schema_version": 3, "interests": [
            {"id": "popular", "topic": "systems", "kind": "inferred"},
            {"id": "unusual", "topic": "historical automata", "kind": "explicit"}],
            "onboarding": {"context_sources": {"past_chats": {"permission": "declined"}}}}
        self.write_json("model/profile.json", self.profile)
        (self.root / "model/feedback.jsonl").write_text(
            json.dumps({"id": "feedback-1", "user_words": "More historical automata please."}) + "\n",
            encoding="utf-8")
        (self.root / "model/recommendations.jsonl").write_text('{"id":"suggestion-only"}\n', encoding="utf-8")
        (self.root / "model/batches.jsonl").write_text('{"id":"batch-1"}\n', encoding="utf-8")

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def draft(self, extra_sources=()):
        value = brief.snapshot(self.root, extra_sources)
        value.update(summary="Historical automata are an explicit interest; systems are tentative.",
                     source_refs=[{"path": "model/profile.json", "locator": "#/interests"},
                                  {"path": "model/feedback.jsonl", "locator": "line:1"}],
                     limits=["A recommendation does not establish consumption or enjoyment."])
        return value

    def cli(self, *args, script=SCRIPT, cwd=None):
        result = subprocess.run([sys.executable, str(script), *args], cwd=cwd,
                                capture_output=True, text=True)
        return result, json.loads(result.stdout)

    def test_save_is_fresh_and_does_not_mutate_authoritative_state(self):
        before = {path.name: path.read_bytes() for path in (self.root / "model").iterdir()}
        draft = self.draft()
        original = copy.deepcopy(draft)
        saved = brief.save(self.root, draft)
        self.assertEqual(saved["version"], 1)
        self.assertEqual(draft, original)
        self.assertEqual(brief.check(self.root)["status"], "fresh")
        for name, data in before.items():
            self.assertEqual((self.root / "model" / name).read_bytes(), data)
        if os.name == "posix":
            self.assertEqual((self.root / brief.BRIEF_PATH).stat().st_mode & 0o777, 0o600)

    def test_minority_explicit_interest_remains_in_machine_inventory(self):
        for number in range(15):
            self.profile["interests"].append({"id": "tentative-" + str(number), "topic": "popular topic", "kind": "inferred"})
        self.write_json("model/profile.json", self.profile)
        before = (self.root / "model/profile.json").read_bytes()
        draft = self.draft()
        draft["summary"] = "Several tentative interests are present; consult the full profile for anchors."
        saved = brief.save(self.root, draft)["brief"]
        self.assertIn("unusual", saved["profile_interest_ids"])
        self.assertEqual(len(saved["profile_interest_ids"]), 17)
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        self.assertEqual(brief.check(self.root)["status"], "fresh")

    def test_profile_and_new_feedback_invalidate_without_returning_obsolete_prose(self):
        for path in ("model/profile.json", "model/feedback.jsonl"):
            with self.subTest(path=path):
                brief.save(self.root, self.draft())
                with (self.root / path).open("a", encoding="utf-8") as handle:
                    handle.write("\n")
                result = brief.check(self.root)
                self.assertEqual(result["status"], "stale")
                self.assertIn(path, result["reasons"][0])
                self.assertNotIn("brief", result)

    def test_request_activity_does_not_invalidate_the_working_brief(self):
        brief.save(self.root, self.draft())
        for path in ("model/batches.jsonl", "model/recommendations.jsonl"):
            with (self.root / path).open("a", encoding="utf-8") as handle:
                handle.write('{"id":"another-request"}\n')
        self.assertEqual(brief.check(self.root)["status"], "fresh")

    def test_optional_history_and_explicit_raw_sources_are_tracked(self):
        extra = "model/experiments/example/ratings.user.json"
        self.write_json(extra, {"responses": [{"rating": 4}]})
        draft = self.draft([extra, "model/recommendations.jsonl"])
        draft["source_refs"] += [{"path": extra, "locator": "#/responses/0/rating"},
                                 {"path": "model/recommendations.jsonl", "locator": "line:1"}]
        brief.save(self.root, draft)
        self.assertEqual(brief.check(self.root)["status"], "fresh")
        (self.root / extra).unlink()
        self.assertEqual(brief.check(self.root)["status"], "stale")

    def test_stale_draft_cannot_be_restamped_after_a_source_correction(self):
        draft = self.draft()
        self.profile["interests"][0]["kind"] = "reference_only"
        self.write_json("model/profile.json", self.profile)
        with self.assertRaisesRegex(brief.BriefError, "sources changed"):
            brief.save(self.root, draft)
        self.assertFalse((self.root / brief.BRIEF_PATH).exists())

    def test_two_drafts_cannot_overwrite_each_other(self):
        first, second = self.draft(), self.draft()
        brief.save(self.root, first)
        saved = (self.root / brief.BRIEF_PATH).read_bytes()
        with self.assertRaisesRegex(brief.BriefError, "brief changed since snapshot"):
            brief.save(self.root, second)
        self.assertEqual((self.root / brief.BRIEF_PATH).read_bytes(), saved)
        self.assertFalse((self.root / "model/.curators-brief.lock").exists())

    def test_concurrent_source_edit_during_save_is_detected(self):
        draft = self.draft()
        original = brief._refs

        def edit_after_reference_validation(value, content):
            original(value, content)
            with (self.root / "model/feedback.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"id":"correction-2"}\n')

        with patch.object(brief, "_refs", side_effect=edit_after_reference_validation):
            with self.assertRaisesRegex(brief.BriefError, "state changed during save"):
                brief.save(self.root, draft)
        self.assertFalse((self.root / brief.BRIEF_PATH).exists())

    def test_lock_serializes_cooperating_writers(self):
        draft = self.draft()
        (self.root / "model/.curators-brief.lock").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(brief.BriefError, "another brief writer"):
            brief.save(self.root, draft)
        self.assertFalse((self.root / brief.BRIEF_PATH).exists())

    def test_versions_are_independent_and_forgetting_retains_no_prose_archive(self):
        first = self.draft()
        first["summary"] = "A superseded private detail that must be forgotten."
        brief.save(self.root, first)
        first_digest = brief._digest((self.root / brief.BRIEF_PATH).read_bytes())
        result = brief.invalidate(self.root, "source_forgotten")
        self.assertEqual(result["version"], 2)
        tombstone = json.loads((self.root / brief.BRIEF_PATH).read_text(encoding="utf-8"))
        self.assertEqual(tombstone["previous_sha256"], first_digest)
        self.assertEqual(tombstone["reason"], "source_forgotten")
        self.assertNotIn("summary", tombstone)
        self.assertEqual(brief.check(self.root)["status"], "stale")
        final = brief.save(self.root, self.draft())
        self.assertEqual(final["version"], 3)
        self.assertEqual(brief.check(self.root)["status"], "fresh")
        for path in (self.root / "model").iterdir():
            if path.is_file():
                self.assertNotIn(b"superseded private detail", path.read_bytes())
        self.assertFalse(list((self.root / "model").glob(".curators-brief*")))

    def test_absent_or_empty_imported_feedback_is_truthful_and_usable(self):
        feedback = self.root / "model/feedback.jsonl"
        for exists in (False, True):
            with self.subTest(exists=exists):
                feedback.unlink(missing_ok=True)
                if exists:
                    feedback.write_text("", encoding="utf-8")
                draft = self.draft()
                draft["source_refs"] = draft["source_refs"][:1]
                record = next(item for item in draft["sources"] if item["path"] == "model/feedback.jsonl")
                self.assertEqual(record["sha256"], brief._digest(b"") if exists else None)
                brief.save(self.root, draft)
                self.assertEqual(brief.check(self.root)["status"], "fresh")
                feedback.write_text('{"id":"first-feedback"}\n', encoding="utf-8")
                self.assertEqual(brief.check(self.root)["status"], "stale")

    def test_missing_profile_cannot_create_a_brief(self):
        (self.root / "model/profile.json").unlink()
        with self.assertRaisesRegex(brief.BriefError, "missing source"):
            brief.snapshot(self.root)

    def test_missing_cache_and_missing_source_are_reported_separately(self):
        self.assertEqual(brief.check(self.root)["status"], "missing")
        brief.save(self.root, self.draft())
        (self.root / "model/profile.json").unlink()
        self.assertEqual(brief.check(self.root)["status"], "stale")

    def test_unsafe_paths_and_derived_briefs_are_rejected(self):
        paths = ["../outside.json", "/tmp/outside.json", "model/../outside.json",
                 "model//profile.json", "model/./profile.json", "model\\profile.json",
                 brief.BRIEF_PATH, "model/experiments/curators-brief.v1.json"]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(brief.BriefError):
                brief.snapshot(self.root, [path])
        derived = "model/experiments/unrecognized-name.json"
        self.write_json(derived, {"summary": "derived", "sources": [], "source_refs": []})
        with self.assertRaisesRegex(brief.BriefError, "derived briefs"):
            brief.snapshot(self.root, [derived])

    def test_external_source_and_cache_symlinks_are_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text('{"private":"outside model"}', encoding="utf-8")
        (self.root / "model/linked.json").symlink_to(outside)
        with self.assertRaisesRegex(brief.BriefError, "symlinks"):
            brief.snapshot(self.root, ["model/linked.json"])
        (self.root / "model/linked-directory").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(brief.BriefError, "symlinks"):
            brief.snapshot(self.root, ["model/linked-directory/outside.json"])
        draft = self.draft()
        (self.root / brief.BRIEF_PATH).symlink_to(outside)
        self.assertEqual(brief.check(self.root)["status"], "invalid")
        with self.assertRaisesRegex(brief.BriefError, "symlinks"):
            brief.save(self.root, draft)
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"private":"outside model"}')

    def test_source_coverage_and_resolvable_references_are_required(self):
        for refs in ([{"path": "model/profile.json", "locator": "#"}],
                     [{"path": "model/profile.json", "locator": "#/missing"},
                      {"path": "model/feedback.jsonl", "locator": "line:1"}],
                     [{"path": "model/profile.json", "locator": "#"},
                      {"path": "model/feedback.jsonl", "locator": "line:99"}]):
            with self.subTest(refs=refs):
                draft = self.draft()
                draft["source_refs"] = refs
                with self.assertRaises(brief.BriefError):
                    brief.save(self.root, draft)

    def test_json_pointer_escaping(self):
        self.profile["odd/key"] = {"tilde~name": "an evidenced value"}
        self.write_json("model/profile.json", self.profile)
        draft = self.draft()
        draft["source_refs"][0]["locator"] = "#/odd~1key/tilde~0name"
        brief.save(self.root, draft)
        self.assertEqual(brief.check(self.root)["status"], "fresh")

    def test_oversized_summary_and_malformed_json_are_unusable(self):
        draft = self.draft()
        draft["summary"] = "word " * 351
        with self.assertRaisesRegex(brief.BriefError, "350"):
            brief.save(self.root, draft)
        (self.root / brief.BRIEF_PATH).write_text("{broken", encoding="utf-8")
        self.assertEqual(brief.check(self.root)["status"], "invalid")
        (self.root / brief.BRIEF_PATH).write_bytes(b" " * (brief.MAX_DOCUMENT_BYTES + 1))
        self.assertEqual(brief.check(self.root)["status"], "invalid")
        (self.root / "model/feedback.jsonl").write_text('{"id":NaN}\n', encoding="utf-8")
        with self.assertRaisesRegex(brief.BriefError, "invalid JSON"):
            brief.snapshot(self.root)

    def test_cli_rejects_invalid_json_without_mutating_sources(self):
        draft_path = self.root / "draft.json"
        draft_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        result, value = self.cli("save", "--root", str(self.root), "--draft", str(draft_path))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(value["status"], "invalid")
        self.assertIn("duplicate JSON key", value["reasons"][0])
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / brief.BRIEF_PATH).exists())

    def test_copied_skill_runtime_works_outside_repository(self):
        installed = self.root / "installed-trurl"
        shutil.copytree(SCRIPT.parents[1], installed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        runtime = installed / "scripts/brief.py"
        result, missing = self.cli("check", "--root", str(self.root), script=runtime, cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(missing["status"], "missing")
        result, captured = self.cli("snapshot", "--root", str(self.root), script=runtime, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        draft = self.draft()
        self.assertEqual(captured, {key: draft[key] for key in captured})
        self.write_json("draft.json", draft)
        result, saved = self.cli("save", "--root", str(self.root), "--draft", str(self.root / "draft.json"),
                                 script=runtime, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved["version"], 1)
        result, fresh = self.cli("check", "--root", str(self.root), script=runtime, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fresh["status"], "fresh")
        result, invalidated = self.cli("invalidate", "--root", str(self.root), "--reason", "source_corrected",
                                       script=runtime, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(invalidated["version"], 2)


if __name__ == "__main__":
    unittest.main()
