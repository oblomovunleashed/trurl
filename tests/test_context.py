"""Compact context preserves coverage, freshness and selective evidence access."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/trurl/scripts/context.py"
API = runpy.run_path(str(SCRIPT))
BRIEF = runpy.run_path(str(SCRIPT.with_name("brief.py")))
HYPOTHESES = runpy.run_path(str(SCRIPT.with_name("hypotheses.py")))


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "private"
        (self.root / "model").mkdir(parents=True)
        self.profile = {
            "person": {"id": "synthetic-person"},
            "interests": [{"id": "a", "topic": "Historical automata", "kind": "explicit",
                           "knowledge_level": "unknown", "source_provenance": ["user-a"]}],
            "provenance": [{"id": "user-a", "kind": "user_statement", "locator": "synthetic://a"}],
            "taste": {"axes_weights": {"novelty": 1}, "constraints": ["No horror"]},
            "discovery": {"open_exploration": {"enabled": False}},
            "delivery": {"weekly": {"enabled": False, "onboarding_default_pending": False}},
            "onboarding": {"context_sources": {"past_chats": {"permission": "declined"}}},
        }
        self.write_profile()
        self.write_ledger("feedback", [{"id": "f", "user_words": "RAW_FEEDBACK_ONLY"}])
        self.write_ledger("recommendations", [{"id": "r", "title": "RAW_RECOMMENDATION_ONLY"}])
        self.write_ledger("batches", [{"id": "b", "candidate_pool": "RAW_BATCH_ONLY"}])

    def write_profile(self):
        (self.root / "model/profile.json").write_text(json.dumps(self.profile), encoding="utf-8")

    def write_ledger(self, name, values):
        (self.root / "model" / (name + ".jsonl")).write_text(
            "".join(json.dumps(item) + "\n" for item in values), encoding="utf-8")

    def save_brief(self, summary="A synthetic explicit interest in historical automata."):
        draft = BRIEF["snapshot"](self.root)
        draft.update(summary=summary, source_refs=[
            {"path": "model/profile.json", "locator": "#/interests/0"},
            {"path": "model/feedback.jsonl", "locator": "line:1"}], limits=["Familiarity unknown."])
        return BRIEF["save"](self.root, draft)

    def test_fresh_brief_and_all_interests_without_raw_ledgers(self):
        for number in range(25):
            self.profile["interests"].append({"id": str(number), "topic": "Quiet interest " + str(number),
                                              "kind": "inferred", "scope": "persistent"})
        self.write_profile()
        self.save_brief()
        before = {path.name: path.read_bytes() for path in (self.root / "model").iterdir()}
        result = API["prepare"](self.root)
        self.assertEqual(len(result["interests"]), 26)
        self.assertEqual(result["interests"][-1]["id"], "24")
        self.assertEqual(result["brief"]["status"], "fresh")
        self.assertEqual(len(result["brief"]["file_sha256"]), 64)
        self.assertEqual(result["settings"]["taste"]["constraints"], ["No horror"])
        self.assertFalse(result["settings"]["discovery"]["open_exploration"]["enabled"])
        self.assertFalse(result["settings"]["delivery"]["weekly"]["enabled"])
        self.assertEqual(result["settings"]["onboarding"]["context_sources"]["past_chats"]["permission"], "declined")
        text = json.dumps(result)
        for marker in ("RAW_FEEDBACK_ONLY", "RAW_RECOMMENDATION_ONLY", "RAW_BATCH_ONLY"):
            self.assertNotIn(marker, text)
        for name, data in before.items():
            self.assertEqual((self.root / "model" / name).read_bytes(), data)

    def test_stale_missing_and_invalid_briefs_never_return_old_prose(self):
        self.assertEqual(API["prepare"](self.root)["brief"]["status"], "missing")
        self.save_brief("OBSOLETE_PROSE")
        self.write_ledger("feedback", [{"id": "f", "user_words": "A new correction."}])
        stale = API["prepare"](self.root)
        self.assertEqual(stale["brief"]["status"], "stale")
        self.assertNotIn("OBSOLETE_PROSE", json.dumps(stale))
        (self.root / "model/curators-brief.json").write_text('{"summary":"INVALID_PROSE"}')
        invalid = API["prepare"](self.root)
        self.assertEqual(invalid["brief"]["status"], "invalid")
        self.assertNotIn("INVALID_PROSE", json.dumps(invalid))

    def test_negative_reference_and_custom_fields_are_not_silently_omitted(self):
        self.profile["interests"] += [
            {"id": "avoid", "topic": "Synthetic excluded theme", "kind": "explicit", "signal": "avoid"},
            {"id": "quoted", "topic": "A third-party example", "kind": "explicit", "reference_only": True}]
        self.profile["custom_time_limit"] = "15 minutes"
        self.write_profile()
        result = API["prepare"](self.root)
        self.assertEqual(result["interests"][1]["signal"], "avoid")
        self.assertTrue(result["interests"][2]["reference_only"])
        self.assertEqual(result["other_profile_fields"], ["custom_time_limit"])

    def test_history_growth_changes_only_counts_and_hashes(self):
        self.save_brief()
        first = API["prepare"](self.root)
        self.write_ledger("batches", [{"id": "batch-" + str(i), "candidate_pool": "LARGE_RAW_TRACE" * 100}
                                      for i in range(1000)])
        self.write_ledger("recommendations", [{"id": "r" + str(i), "title": "LONG_WORK_RECORD" * 100}
                                               for i in range(1000)])
        second = API["prepare"](self.root)
        self.assertEqual(second["brief"]["status"], "fresh")
        self.assertLess(len(json.dumps(second)) - len(json.dumps(first)), 20)
        self.assertNotIn("LARGE_RAW_TRACE", json.dumps(second))
        self.assertEqual(second["ledgers"]["batch"]["count"], 1000)

    def test_reconciles_changed_hypothesis_evidence_before_reading_brief(self):
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"] = [{"id": "h", "topic": "Mechanical storytelling", "anchor_ids": ["a"],
                                     "reason": "A plausible aspect of the original interest.",
                                     "status": "testing", "evidence": []}]
        HYPOTHESES["save"](self.root, draft)
        current = json.loads((self.root / "model/profile.json").read_text())
        current["interests"][0]["topic"] = "Corrected original interest"
        (self.root / "model/profile.json").write_text(json.dumps(current))
        self.save_brief("STALE_HYPOTHESIS_READING")
        result = API["prepare"](self.root)
        self.assertEqual(result["hypothesis_reconciliation"]["status"], "refreshed")
        self.assertEqual(result["taste_hypotheses"][0]["status"], "stale")
        self.assertEqual(result["brief"]["status"], "stale")
        self.assertNotIn("STALE_HYPOTHESIS_READING", json.dumps(result))

    def test_raw_records_are_selective_paginated_and_unambiguous(self):
        result = API["records"](self.root, "feedback", ["f"])
        self.assertEqual(result["items"][0]["record"]["user_words"], "RAW_FEEDBACK_ONLY")
        self.assertEqual(result["items"][0]["locator"], "line:1")
        self.assertNotIn("RAW_BATCH_ONLY", json.dumps(result))
        self.write_ledger("feedback", [{"id": "f" + str(i)} for i in range(25)])
        page = API["records"](self.root, "feedback", offset=10, limit=10)
        self.assertEqual(page["total"], 25)
        self.assertEqual(page["next_offset"], 20)
        self.assertEqual(page["items"][0]["record"]["id"], "f10")
        self.assertEqual(API["records"](self.root, "interest", ["a"])["items"][0]["locator"], "#/interests/0")
        self.write_ledger("feedback", [{"id": "same"}, {"id": "same"}])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            API["records"](self.root, "feedback", ["same"])
        for options in ({"limit": 21}, {"offset": -1}, {"identifiers": ["a"], "offset": 1}):
            with self.assertRaises(ValueError):
                API["records"](self.root, "feedback", **options)

    def test_installed_copy_works_outside_repository_and_rejects_symlinks(self):
        installed = Path(self.temporary.name) / "installed-trurl"
        shutil.copytree(SCRIPT.parents[1], installed)
        completed = subprocess.run([sys.executable, str(installed / "scripts/context.py"),
                                    "prepare", "--root", str(self.root)],
                                   cwd=self.temporary.name, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["interests"][0]["id"], "a")
        ledger = self.root / "model/batches.jsonl"
        ledger.unlink()
        ledger.symlink_to(self.root / "model/feedback.jsonl")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            API["prepare"](self.root)


if __name__ == "__main__":
    unittest.main()
