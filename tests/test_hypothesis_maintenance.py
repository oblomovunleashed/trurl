"""Proactive review must be bounded, evidence-triggered and actually completed."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


API = runpy.run_path(str(Path(__file__).resolve().parents[1]
                        / "skills/trurl/scripts/hypotheses.py"))
CURATION = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/curation.py"
BROAD = {"scope": "broad", "mode": "personal"}


class HypothesisMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "model").mkdir()
        self.profile = {
            "interests": [{"id": "tea", "topic": "Chinese tea", "kind": "explicit",
                           "scope": "persistent", "source_provenance": ["source-tea"]},
                          {"id": "history", "topic": "Urban history", "kind": "explicit",
                           "scope": "persistent", "source_provenance": ["source-history"]}],
            "provenance": [{"id": "source-tea", "kind": "user_statement",
                            "locator": "synthetic tea message"},
                           {"id": "source-history", "kind": "user_statement",
                            "locator": "synthetic history message"}],
            "taste": {"axes_weights": {"novelty": 1}},
            "delivery": {"weekly": {"enabled": False}},
            "source_permissions": {"past_chats": False},
        }
        self.feedback = []
        self.history = []
        self.write_profile(self.profile)
        self.write_ledgers()

    def write_profile(self, profile):
        (self.root / "model/profile.json").write_text(json.dumps(profile))

    def read_profile(self):
        return json.loads((self.root / "model/profile.json").read_text())

    def write_ledgers(self):
        for name, records in (("feedback", self.feedback), ("recommendations", self.history)):
            (self.root / "model" / (name + ".jsonl")).write_text(
                "".join(json.dumps(record) + "\n" for record in records))

    def review(self, plan=None, event="broad"):
        return API["maintenance_plan"](self.root, BROAD if plan is None else plan, event)

    def check(self, plan=None, event="broad"):
        return API["maintenance_check"](self.root, BROAD if plan is None else plan, event)

    def complete(self, review=None, outcome="no_proposal", ids=None):
        return API["complete_maintenance"](
            self.root, review or self.review(), outcome,
            "Reviewed the original anchors; no further defensible connection is needed.", ids)

    def save_hypotheses(self, ids=("h1",)):
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"].extend({
            "id": identifier, "topic": "Synthetic tea-city history " + identifier,
            "reason": "Tea supplies the cultural practice; history supplies the urban question.",
            "anchor_ids": ["tea", "history"], "status": "testing", "evidence": [],
        } for identifier in ids)
        API["save"](self.root, draft)

    def add_feedback(self, signal="disliked", **fields):
        self.feedback.append({"id": "f" + str(len(self.feedback) + 1), "signal": signal,
                              "user_words": "That was too technical for this interest.",
                              "source_provenance": ["synthetic-feedback-message"], **fields})
        self.write_ledgers()

    def test_first_review_is_pending_until_a_real_completion_is_recorded(self):
        review = self.review()
        self.assertTrue(review["eligible"])
        self.assertTrue(review["review_due"])
        self.assertIn("first_review", review["triggers"])
        self.assertFalse(self.check()["completed"])
        self.assertFalse((self.root / "model/hypothesis-maintenance.json").exists())
        self.complete(review)
        self.assertTrue(self.check()["completed"])
        self.assertFalse(self.review()["review_due"])

    def test_focused_first_review_can_complete_and_reuse_an_empty_pool(self):
        plan = {"scope": "focused", "mode": "personal"}
        review = self.review(plan)
        self.assertTrue(review["eligible"])
        self.assertEqual(review["triggers"], ["first_review"])
        before = (self.root / "model/profile.json").read_bytes()
        self.complete(review)
        receipt = (self.root / "model/hypothesis-maintenance.json").read_bytes()
        for _ in range(3):
            checked = self.check(plan)
            self.assertTrue(checked["completed"])
            self.assertFalse(checked["review_due"])
            self.assertEqual(checked["receipt"]["outcome"], "no_proposal")
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        self.assertEqual((self.root / "model/hypothesis-maintenance.json").read_bytes(), receipt)

    def test_focused_review_reopens_for_original_sources_and_meaningful_feedback(self):
        plan = {"scope": "focused", "mode": "personal"}
        self.complete(self.review(plan))
        profile = self.read_profile()
        profile["provenance"][0]["locator"] = "synthetic corrected original message"
        self.write_profile(profile)
        changed = self.review(plan)
        self.assertEqual(changed["triggers"], ["anchors_changed"])
        self.complete(changed)
        self.add_feedback()
        changed = self.review(plan)
        self.assertEqual(changed["triggers"], ["feedback_changed"])
        self.complete(changed)
        self.assertFalse(self.review(plan)["review_due"])

    def test_focused_review_ignores_pool_only_changes_but_broad_review_retains_them(self):
        plan = {"scope": "focused", "mode": "personal"}
        self.save_hypotheses(("h1", "h2"))
        self.complete(self.review(plan), outcome="reviewed", ids=["h1", "h2"])
        receipt = self.check(plan)["receipt"]["id"]
        self.history.append({"id": "r1", "title": "Synthetic probe", "hypothesis_id": "h1"})
        self.write_ledgers()
        self.assertFalse(self.review(plan)["review_due"])
        self.assertEqual(self.check(plan)["receipt"]["id"], receipt)
        self.assertIn("low_untried_pool", self.review()["triggers"])
        self.save_hypotheses(("h3",))
        self.assertFalse(self.review(plan)["review_due"])
        self.assertIn("pool_changed", self.review()["triggers"])

    def test_focused_invalid_record_can_be_repaired_with_a_saved_hypothesis(self):
        plan = {"scope": "focused", "mode": "personal"}
        (self.root / "model/hypothesis-maintenance.json").write_text("{broken")
        review = self.review(plan)
        self.assertEqual(review["triggers"], ["invalid_record"])
        self.save_hypotheses()
        self.complete(review, outcome="saved", ids=["h1"])
        checked = self.check(plan)
        self.assertTrue(checked["completed"])
        self.assertEqual(checked["receipt"]["hypothesis_ids"], ["h1"])
        self.assertEqual(self.read_profile()["taste_hypotheses"][0]["status"], "testing")

    def test_no_proposal_receipt_reuses_an_unchanged_empty_pool(self):
        self.complete()
        receipt_path = self.root / "model/hypothesis-maintenance.json"
        before = receipt_path.read_bytes()
        for _ in range(3):
            self.assertFalse(self.review()["review_due"])
            self.assertTrue(self.check()["completed"])
        self.assertEqual(receipt_path.read_bytes(), before)

    def test_reviewed_receipt_reuses_an_unchanged_sparse_pool(self):
        self.save_hypotheses()
        self.complete(outcome="reviewed", ids=["h1"])
        self.assertFalse(self.review()["review_due"])
        self.assertTrue(self.check()["completed"])

    def test_active_hypothesis_does_not_hide_a_new_original_interest(self):
        self.save_hypotheses()
        self.complete(outcome="reviewed", ids=["h1"])
        profile = self.read_profile()
        profile["interests"].append({"id": "ai", "topic": "AI research", "kind": "explicit",
                                     "source_provenance": ["source-ai"]})
        profile["provenance"].append({"id": "source-ai", "kind": "user_statement",
                                      "locator": "synthetic new interest"})
        self.write_profile(profile)
        review = self.review()
        self.assertTrue(review["review_due"])
        self.assertIn("anchors_changed", review["triggers"])
        self.assertFalse(self.check()["completed"])

    def test_correction_to_an_original_source_reopens_review(self):
        self.complete()
        profile = self.read_profile()
        profile["provenance"][0]["locator"] = "corrected synthetic original message"
        self.write_profile(profile)
        self.assertIn("anchors_changed", self.review()["triggers"])

    def test_unreferenced_provenance_does_not_reopen_review(self):
        self.complete()
        profile = self.read_profile()
        profile["provenance"].append({"id": "unrelated", "kind": "user_statement",
                                      "locator": "synthetic administrative message"})
        self.write_profile(profile)
        self.assertFalse(self.review()["review_due"])

    def test_noop_hypothesis_save_does_not_reopen_review_from_timestamps(self):
        self.save_hypotheses()
        self.complete(outcome="reviewed", ids=["h1"])
        API["save"](self.root, API["snapshot"](self.root))
        self.assertFalse(self.review()["review_due"])

    def test_meaningful_feedback_reopens_review_and_is_then_absorbed(self):
        self.complete()
        self.add_feedback()
        self.assertIn("feedback_changed", self.review()["triggers"])
        self.complete()
        self.assertFalse(self.review()["review_due"])

    def test_correction_to_feedback_reopens_review(self):
        self.add_feedback()
        self.complete()
        self.feedback[0]["user_words"] = "Actually I liked the technical detail."
        self.feedback[0]["signal"] = "enjoyed"
        self.write_ledgers()
        self.assertIn("feedback_changed", self.review()["triggers"])

    def test_unrelated_history_and_passive_signals_do_not_reopen_review(self):
        self.complete()
        self.history.append({"id": "r1", "title": "Synthetic suggestion",
                             "creator": "Synthetic author"})
        for signal in ("delivered", "completed", "clicked", "silence"):
            self.feedback.append({"id": signal, "signal": signal,
                                  "user_words": "Synthetic activity marker.",
                                  "source_provenance": ["synthetic-activity"]})
        self.write_ledgers()
        self.assertFalse(self.review()["review_due"])

    def test_unsourced_or_assistant_feedback_cannot_trigger_preference_work(self):
        self.complete()
        self.feedback = [{"id": "f1", "signal": "enjoyed", "user_words": "Looks appealing."},
                         {"id": "f2", "signal": "enjoyed", "user_words": "Assistant inference.",
                          "source_provenance": [{"kind": "assistant_suggestion", "id": "assistant"}]}]
        self.write_ledgers()
        self.assertFalse(self.review()["review_due"])

    def test_referenced_work_correction_reopens_feedback_review(self):
        self.history = [{"id": "r1", "title": "Original title", "creator": "Synthetic author"}]
        self.add_feedback(recommendation_id="r1")
        self.complete()
        self.history[0]["title"] = "Corrected work identity"
        self.write_ledgers()
        self.assertIn("feedback_changed", self.review()["triggers"])

    def test_one_used_opportunity_reopens_a_low_untried_pool_without_promotion(self):
        self.save_hypotheses(("h1", "h2"))
        self.complete(outcome="reviewed", ids=["h1", "h2"])
        before = (self.root / "model/profile.json").read_bytes()
        self.history.append({"id": "r1", "title": "Synthetic probe", "creator": "Synthetic author",
                             "hypothesis_id": "h1"})
        self.write_ledgers()
        self.assertIn("low_untried_pool", self.review()["triggers"])
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        self.assertEqual([item["status"] for item in self.read_profile()["taste_hypotheses"]],
                         ["testing", "testing"])
        self.complete(outcome="reviewed", ids=["h1", "h2"])
        self.assertFalse(self.review()["review_due"])
        self.history.append({"id": "r2", "title": "Another probe for the same hypothesis",
                             "creator": "Synthetic author", "hypothesis_id": "h1"})
        self.write_ledgers()
        self.assertFalse(self.review()["review_due"])

    def test_adequate_untried_pool_does_not_review_after_each_delivery(self):
        self.save_hypotheses(("h1", "h2", "h3"))
        self.complete(outcome="reviewed", ids=["h1", "h2", "h3"])
        self.history.append({"id": "r1", "hypothesis_id": "h1", "title": "Synthetic probe"})
        self.write_ledgers()
        self.assertFalse(self.review()["review_due"])

    def test_saved_requires_a_persisted_new_or_revised_hypothesis(self):
        review = self.review()
        with self.assertRaises(ValueError):
            self.complete(review, outcome="saved", ids=["imagined"])
        self.save_hypotheses()
        self.complete(review, outcome="saved", ids=["h1"])
        self.assertTrue(self.check()["completed"])
        self.assertFalse(self.review()["review_due"])
        with self.assertRaises(ValueError):
            self.complete(self.review(), outcome="saved", ids=["h1"])

    def test_saved_accepts_an_actual_revision(self):
        self.save_hypotheses()
        review = self.review()
        draft = API["snapshot"](self.root)
        draft["taste_hypotheses"][0]["reason"] = "Narrow to urban trade; rural craft is an alternative explanation."
        API["save"](self.root, draft)
        self.complete(review, outcome="saved", ids=["h1"])
        self.assertTrue(self.check()["completed"])

    def test_timestamp_only_save_cannot_be_claimed_as_a_revision(self):
        self.save_hypotheses()
        review = self.review()
        API["save"](self.root, API["snapshot"](self.root))
        with self.assertRaises(ValueError):
            self.complete(review, outcome="saved", ids=["h1"])

    def test_existing_evidence_revisions_can_be_reconciled_together(self):
        self.save_hypotheses(("h1", "h2"))
        self.history = [{"id": "r1", "title": "Synthetic tea-city work", "creator": "Synthetic author"}]
        self.add_feedback(signal="enjoyed", recommendation_id="r1",
                          user_words="I enjoyed the cultural history in this.")
        review = self.review()
        draft = API["snapshot"](self.root)
        for item in draft["taste_hypotheses"]:
            item["evidence"] = [{"feedback_id": "f1", "effect": "support", "scope": "work",
                                  "reason": "This enjoyed work is relevant to the cultural-history possibility."}]
        API["save"](self.root, draft)
        self.complete(review, outcome="reviewed", ids=["h1", "h2"])
        self.assertTrue(self.check()["completed"])
        self.assertEqual([item["supporting_work_count"] for item in self.read_profile()["taste_hypotheses"]],
                         [1, 1])
        self.assertEqual([item["status"] for item in self.read_profile()["taste_hypotheses"]],
                         ["testing", "testing"])

    def test_review_cannot_claim_two_new_hypotheses(self):
        review = self.review()
        self.save_hypotheses(("h1", "h2"))
        with self.assertRaises(ValueError):
            self.complete(review, outcome="saved", ids=["h1", "h2"])
        with self.assertRaises(ValueError):
            self.complete(review, outcome="saved", ids=["h1"])

    def test_reviewed_requires_an_existing_usable_hypothesis(self):
        with self.assertRaises(ValueError):
            self.complete(outcome="reviewed", ids=["missing"])

    def test_new_proposal_cannot_be_hidden_under_no_proposal_or_reviewed(self):
        review = self.review()
        self.save_hypotheses()
        with self.assertRaises(ValueError):
            self.complete(review, outcome="no_proposal")
        with self.assertRaises(ValueError):
            self.complete(review, outcome="reviewed", ids=["h1"])

    def test_blank_reason_cannot_complete_review(self):
        with self.assertRaises(ValueError):
            API["complete_maintenance"](self.root, self.review(), "no_proposal", "  ", [])

    def test_anchor_change_during_review_rejects_stale_completion(self):
        review = self.review()
        profile = self.read_profile()
        profile["interests"][0]["topic"] = "Japanese tea"
        self.write_profile(profile)
        with self.assertRaises(ValueError):
            self.complete(review)
        self.assertFalse(self.check()["completed"])

    def test_feedback_change_during_review_rejects_stale_completion(self):
        review = self.review()
        self.add_feedback()
        with self.assertRaises(ValueError):
            self.complete(review)
        self.assertFalse(self.check()["completed"])

    def test_unrelated_profile_edit_during_review_is_preserved(self):
        review = self.review()
        profile = self.read_profile()
        profile["delivery"]["weekly"]["enabled"] = True
        profile["taste"]["axes_weights"] = {"novelty": 0.5, "depth": 0.5}
        self.write_profile(profile)
        before = (self.root / "model/profile.json").read_bytes()
        self.complete(review)
        self.assertEqual((self.root / "model/profile.json").read_bytes(), before)
        self.assertTrue(self.check()["completed"])

    def test_another_completed_review_cannot_be_overwritten_with_an_old_snapshot(self):
        first = self.review()
        second = self.review()
        self.complete(first)
        before = (self.root / "model/hypothesis-maintenance.json").read_bytes()
        with self.assertRaises(ValueError):
            self.complete(second)
        self.assertEqual((self.root / "model/hypothesis-maintenance.json").read_bytes(), before)

    def test_wildcard_and_anchorless_requests_are_not_gated(self):
        for plan in ({"scope": "focused", "mode": "wildcard"},
                     {"scope": "broad", "mode": "wildcard"}):
            with self.subTest(plan=plan):
                review = self.review(plan)
                self.assertFalse(review["eligible"])
                self.assertFalse(review["review_due"])
        self.write_profile({**self.profile, "interests": []})
        self.assertFalse(self.review()["eligible"])
        self.assertFalse(self.review()["review_due"])

    def test_onboarding_and_feedback_events_allow_review_without_a_batch_plan(self):
        for event in ("onboarding", "feedback"):
            with self.subTest(event=event):
                review = API["maintenance_plan"](self.root, event=event)
                self.assertTrue(review["eligible"])
                self.assertTrue(review["review_due"])

    def test_maintenance_does_not_modify_personal_state_or_invalidate_brief(self):
        brief_path = self.root / "model/curators-brief.json"
        brief_path.write_text('{"synthetic": "derived brief"}')
        files = [self.root / "model" / name for name in
                 ("profile.json", "feedback.jsonl", "recommendations.jsonl", "curators-brief.json")]
        before = {str(path): path.read_bytes() for path in files}
        self.complete()
        self.assertEqual({str(path): path.read_bytes() for path in files}, before)

    def test_incomplete_receipt_does_not_pass_completion_check(self):
        path = self.root / "model/hypothesis-maintenance.json"
        path.write_text(json.dumps({"schema_version": 1, "outcome": "saved"}))
        try:
            result = self.check()
        except ValueError:
            pass
        else:
            self.assertFalse(result["completed"])

    def test_invalid_receipt_can_be_replaced_only_after_a_fresh_review(self):
        path = self.root / "model/hypothesis-maintenance.json"
        original_profile = (self.root / "model/profile.json").read_bytes()
        invalid_outcomes = [json.dumps({"schema_version": 1, "outcome": value}).encode()
                            for value in ([], {}, None, 1, True, "unknown")]
        for damaged in [b'{"schema_version":1,"outcome":"saved"}', b'{broken json', b'\xff', *invalid_outcomes]:
            with self.subTest(damaged=damaged):
                path.write_bytes(damaged)
                self.assertFalse(self.check()["completed"])
                review = self.review()
                self.assertEqual(review["triggers"], ["invalid_record"])
                self.assertEqual(path.read_bytes(), damaged)
                self.complete(review)
                self.assertTrue(self.check()["completed"])
                self.assertEqual(self.check()["receipt"]["triggers"], ["invalid_record"])
                self.assertEqual((self.root / "model/profile.json").read_bytes(), original_profile)

    def test_cli_malformed_outcome_returns_a_recovery_review(self):
        path = self.root / "model/hypothesis-maintenance.json"
        path.write_text('{"schema_version":1,"outcome":[]}')
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(BROAD))
        command = [sys.executable, str(CURATION), "hypotheses", "maintenance-plan",
                   "--root", str(self.root), "--plan", str(plan_path)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        review = json.loads(result.stdout)
        self.assertTrue(review["review_due"])
        self.assertEqual(review["triggers"], ["invalid_record"])
        self.complete(review)
        self.assertTrue(self.check()["completed"])

    def test_changed_invalid_receipt_rejects_a_stale_repair_review(self):
        path = self.root / "model/hypothesis-maintenance.json"
        path.write_text('{"incomplete":true}')
        review = self.review()
        path.write_text('{"different_incomplete":true}')
        with self.assertRaises(ValueError):
            self.complete(review)
        self.assertEqual(path.read_text(), '{"different_incomplete":true}')
        self.complete()
        self.assertTrue(self.check()["completed"])

    def test_completion_keeps_the_review_triggers_for_the_batch_record(self):
        self.complete()
        self.assertEqual(self.check()["receipt"]["triggers"], ["first_review"])
        self.add_feedback()
        self.complete()
        self.assertIn("feedback_changed", self.check()["receipt"]["triggers"])

    def test_cli_check_fails_when_due_and_succeeds_after_completion(self):
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(BROAD))
        command = [sys.executable, str(CURATION), "hypotheses", "maintenance-check",
                   "--root", str(self.root), "--plan", str(plan_path)]
        pending = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(pending.returncode, 0)
        self.assertFalse(json.loads(pending.stdout)["completed"])
        self.complete()
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["completed"])
        plan_path.write_text(json.dumps({"scope": "focused", "mode": "personal"}))
        focused = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(focused.returncode, 0, focused.stderr)
        self.assertTrue(json.loads(focused.stdout)["completed"])
        self.assertEqual(json.loads(focused.stdout)["receipt"]["id"],
                         json.loads(completed.stdout)["receipt"]["id"])


if __name__ == "__main__":
    unittest.main()
