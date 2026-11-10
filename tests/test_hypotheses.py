"""Taste hypothesis lifecycle tests use only synthetic temporary profiles."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest

API = runpy.run_path(str(Path(__file__).resolve().parents[1] / "skills/trurl/scripts/hypotheses.py"))


class HypothesisLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "model").mkdir()
        self.profile = {
            "interests": [{"id": "a", "topic": "Synthetic creator", "kind": "explicit",
                           "source_provenance": ["source-a"]}],
            "provenance": [{"id": "source-a", "kind": "user_statement", "locator": "synthetic message"}],
            "taste": {"axes_weights": {"novelty": 1}},
            "delivery": {"weekly": {"enabled": False}},
        }
        self.write_profile(self.profile)
        self.feedback, self.history = [], []
        self.write_ledgers()

    def write_profile(self, value):
        (self.root / "model/profile.json").write_text(json.dumps(value))

    def read_profile(self):
        return json.loads((self.root / "model/profile.json").read_text())

    def write_ledgers(self):
        for filename, records in (("feedback", self.feedback), ("recommendations", self.history)):
            (self.root / "model" / (filename + ".jsonl")).write_text(
                "".join(json.dumps(record) + "\n" for record in records))

    def proposal(self):
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"] = [{"id": "h", "topic": "Synthetic absurd humour",
                                     "reason": "The creator's stated works may suggest this quality.",
                                     "anchor_ids": ["a"], "status": "testing", "evidence": []}]
        return draft

    def save_proposal(self):
        return API["save"](self.root, self.proposal())

    def enjoyment(self, number, source=None, title=None):
        identifier = str(number)
        self.history.append({"id": "r" + identifier, "title": title or "Synthetic work " + identifier,
                             "creator": "Synthetic author", "canonical_url": "https://example.test/work/" + identifier})
        self.feedback.append({"id": "f" + identifier, "recommendation_id": "r" + identifier,
                              "signal": "enjoyed", "user_words": "I enjoyed this.",
                              "source_provenance": [source or "synthetic-user-message-" + identifier]})
        return {"feedback_id": "f" + identifier, "effect": "support", "scope": "work",
                "reason": "The shared quality is plausibly part of the enjoyment."}

    def support(self):
        self.save_proposal()
        evidence = [self.enjoyment(1), self.enjoyment(2)]
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = evidence
        API["save"](self.root, draft)

    def test_proposal_stays_out_of_anchors_and_preserves_existing_fields(self):
        self.save_proposal()
        saved = self.read_profile()
        self.assertEqual(saved["interests"], self.profile["interests"])
        self.assertEqual(saved["taste"], self.profile["taste"])
        self.assertEqual(saved["delivery"], self.profile["delivery"])
        self.assertEqual(API["active_hypotheses"](saved)[0]["id"], "h")
        self.assertTrue(saved["taste_hypotheses"][0]["created_at"])

    def test_support_requires_two_distinct_works_and_independent_sources(self):
        for shared_title, shared_source in ((True, False), (False, True), (False, False)):
            with self.subTest(shared_title=shared_title, shared_source=shared_source):
                self.write_profile(self.profile)
                self.feedback, self.history = [], []
                self.write_ledgers()
                self.save_proposal()
                first = self.enjoyment(1)
                second = self.enjoyment(2, source="synthetic-user-message-1" if shared_source else None,
                                        title="Synthetic work 1" if shared_title else None)
                self.write_ledgers()
                draft = API["snapshot"](self.root)
                draft["taste_hypotheses"][0]["evidence"] = [first, second]
                result = API["save"](self.root, draft)
                expected = "testing" if shared_title or shared_source else "supported"
                self.assertEqual(result["hypotheses"][0]["status"], expected)
                self.assertEqual(len(self.read_profile()["interests"]), 1 if expected == "testing" else 2)

    def test_supported_interest_is_inferred_and_raw_views_fail_closed(self):
        self.support()
        saved = self.read_profile()
        managed = saved["interests"][-1]
        self.assertEqual(managed["kind"], "inferred")
        self.assertEqual(managed["knowledge_level"], "unknown")
        self.assertFalse(API["managed_interest_valid"](saved, managed))
        self.assertEqual(len(API["validated_profile"](saved)["interests"]), 1)
        reviewed = API["validated_profile"](saved, self.feedback, self.history)
        self.assertTrue(API["managed_interest_valid"](reviewed, reviewed["interests"][-1]))

    def test_direct_confirmation_alone_promotes_explicit_interest(self):
        self.save_proposal()
        self.feedback = [{"id": "confirm", "signal": "confirmed_interest",
                          "user_words": "I enjoy this kind of humour.",
                          "source_provenance": ["synthetic-confirmation"]}]
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": "confirm", "effect": "confirm", "scope": "hypothesis",
             "reason": "The user explicitly states this broader preference."}]
        API["save"](self.root, draft)
        saved = self.read_profile()
        self.assertEqual(saved["taste_hypotheses"][0]["status"], "confirmed")
        self.assertEqual(saved["interests"][-1]["kind"], "explicit")

    def test_unexperienced_feedback_cannot_promote(self):
        self.save_proposal()
        reference = self.enjoyment(1)
        for signal in ("completed", "would_try", "clicked", "useful"):
            with self.subTest(signal=signal):
                self.feedback[0]["signal"] = signal
                self.write_ledgers()
                draft = API["snapshot"](self.root)
                draft["taste_hypotheses"][0]["evidence"] = [reference]
                before = (self.root / "model/profile.json").read_bytes()
                with self.assertRaises(ValueError):
                    API["save"](self.root, draft)
                self.assertEqual((self.root / "model/profile.json").read_bytes(), before)

    def test_corrected_or_removed_evidence_rolls_back_promotion_on_refresh(self):
        self.support()
        before = self.read_profile()
        self.feedback[0]["user_words"] = "Actually I meant a different work."
        self.write_ledgers()
        view = API["validated_profile"](before, self.feedback, self.history)
        self.assertEqual(view["taste_hypotheses"][0]["status"], "stale")
        self.assertEqual(len(view["interests"]), 1)
        self.assertEqual(self.read_profile(), before)
        self.assertEqual(API["refresh"](self.root)["status"], "refreshed")
        self.assertEqual(len(self.read_profile()["interests"]), 1)
        self.assertEqual(API["refresh"](self.root)["status"], "unchanged")

    def test_anchor_and_referenced_provenance_changes_invalidate_probes(self):
        self.save_proposal()
        original = self.read_profile()
        for mutate in (lambda p: p["interests"].clear(),
                       lambda p: p["interests"][0].update(topic="Corrected topic"),
                       lambda p: p["provenance"][0].update(locator="corrected source"),
                       lambda p: p["provenance"].clear()):
            value = copy.deepcopy(original)
            mutate(value)
            self.assertEqual(API["active_hypotheses"](value), [])

    def test_hypotheses_cannot_seed_further_hypotheses(self):
        self.support()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"].append(
            {"id": "second", "topic": "Unjustified extension", "reason": "A guessed connection",
             "anchor_ids": ["hypothesis:h"], "evidence": []})
        with self.assertRaisesRegex(ValueError, "cannot anchor"):
            API["save"](self.root, draft)

    def test_duplicate_evidence_stale_save_and_retry_are_safe(self):
        draft = self.proposal()
        API["save"](self.root, draft)
        before = (self.root / "model/profile.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "sources changed"):
            API["save"](self.root, draft)
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        fresh = API["snapshot"](self.root)
        self.feedback.append({"id": "new"})
        self.write_ledgers()
        with self.assertRaisesRegex(ValueError, "sources changed"):
            API["save"](self.root, fresh)

    def test_legacy_refresh_is_a_noop_and_symlinks_are_rejected(self):
        before = (self.root / "model/profile.json").read_bytes()
        self.assertEqual(API["refresh"](self.root)["status"], "unchanged")
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        source = self.root / "model/profile.json"
        moved = self.root / "original.json"
        source.rename(moved)
        source.symlink_to(moved)
        with self.assertRaises(ValueError):
            API["snapshot"](self.root)

    def test_work_aliases_and_shared_source_locators_do_not_create_independence(self):
        self.save_proposal()
        refs = [self.enjoyment(1), self.enjoyment(2)]
        self.history[1]["canonical_url"] = self.history[0]["canonical_url"] + "?utm_source=copy"
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = refs
        self.assertEqual(API["save"](self.root, draft)["hypotheses"][0]["status"], "testing")

    def test_work_contradiction_keeps_a_pattern_tentative(self):
        self.support()
        self.history.append({"id": "r3", "title": "Another work", "creator": "Another creator"})
        self.feedback.append({"id": "f3", "recommendation_id": "r3", "signal": "not_for_me",
                              "user_words": "I disliked this.",
                              "source_provenance": ["another-source"]})
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"].append(
            {"feedback_id": "f3", "effect": "contradict", "scope": "work",
             "reason": "The reaction challenges the proposed shared quality."})
        self.assertEqual(API["save"](self.root, draft)["hypotheses"][0]["status"], "testing")
        self.assertEqual(len(self.read_profile()["interests"]), 1)

    def test_assistant_or_quoted_feedback_never_becomes_personal_support(self):
        self.save_proposal()
        reference = self.enjoyment(1)
        for source_kind in ("assistant_characterization", "assistant_generated", "quoted_third_party", "illustrative"):
            with self.subTest(source_kind=source_kind):
                self.feedback[0]["source_provenance"] = [
                    {"id": "not-user-evidence", "kind": source_kind, "locator": "synthetic-source"}]
                self.write_ledgers()
                draft = API["snapshot"](self.root)
                draft["taste_hypotheses"][0]["evidence"] = [reference]
                with self.assertRaises(ValueError):
                    API["save"](self.root, draft)

    def test_latest_dated_correction_wins_even_when_old_feedback_is_imported_last(self):
        self.save_proposal()
        self.feedback = [
            {"id": "new", "signal": "rejected_interest", "recorded_at": "2026-11-06T12:00:00Z",
             "user_words": "That is not a broader interest.", "source_provenance": ["new-source"]},
            {"id": "old", "signal": "confirmed_interest", "recorded_at": "2026-11-01T12:00:00Z",
             "user_words": "I like that kind of thing.", "source_provenance": ["old-source"]},
        ]
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": "old", "effect": "confirm", "scope": "hypothesis", "reason": "Earlier view"},
            {"feedback_id": "new", "effect": "contradict", "scope": "hypothesis", "reason": "Current correction"},
        ]
        self.assertEqual(API["save"](self.root, draft)["hypotheses"][0]["status"], "rejected")
        self.assertEqual(len(self.read_profile()["interests"]), 1)
        self.feedback[0].pop("recorded_at")
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["status"] = "testing"
        result = API["save"](self.root, draft)["hypotheses"][0]
        self.assertEqual(result["status"], "testing")
        self.assertTrue(result["ambiguous_broad_feedback"])

    def test_same_id_cannot_reinterpret_topic_and_retired_origins_can_be_missing(self):
        self.save_proposal()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["topic"] = "A different interpretation"
        with self.assertRaisesRegex(ValueError, "new hypothesis id"):
            API["save"](self.root, draft)
        changed = self.read_profile()
        changed["interests"] = []
        self.write_profile(changed)
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["status"] = "retired"
        result = API["save"](self.root, draft)
        self.assertEqual(result["hypotheses"][0]["status"], "retired")
        self.assertEqual(self.read_profile()["taste_hypotheses"][0]["status"], "retired")
        self.assertEqual(API["active_hypotheses"](self.read_profile()), [])

    def test_later_confirmation_can_restore_a_rejected_hypothesis(self):
        self.save_proposal()
        self.feedback = [{"id": "rejection", "signal": "rejected_interest",
                          "recorded_at": "2026-11-01T12:00:00Z",
                          "user_words": "That subject does not interest me.",
                          "source_provenance": ["reject-source"]}]
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": "rejection", "effect": "contradict", "scope": "hypothesis",
             "reason": "The person rejects the broader interest."}]
        API["save"](self.root, draft)
        self.assertEqual(self.read_profile()["taste_hypotheses"][0]["status"], "rejected")
        self.feedback.append({"id": "confirmation", "signal": "confirmed_interest",
                              "recorded_at": "2026-11-06T12:00:00Z",
                              "user_words": "I have changed my mind and enjoy this subject.",
                              "source_provenance": ["confirm-source"]})
        self.write_ledgers()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"].append(
            {"feedback_id": "confirmation", "effect": "confirm", "scope": "hypothesis",
             "reason": "The later explicit correction supersedes the earlier rejection."})
        result = API["save"](self.root, draft)
        self.assertEqual(result["hypotheses"][0]["status"], "confirmed")
        self.assertEqual(self.read_profile()["interests"][-1]["kind"], "explicit")


if __name__ == "__main__":
    unittest.main()
