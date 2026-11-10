"""Bounded graph ingestion must retain provenance and truthful completion state."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/graph_updates.py"
API = runpy.run_path(str(MODULE))


class GraphUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = self.root / "model"
        self.model.mkdir()
        self.write("profile.json", {"interests": [], "taste": {"axes_weights": {"depth": 1}},
                                    "delivery": {"weekly": {"enabled": False}},
                                    "source_permissions": {"past_chats": False}})
        self.write("curators-brief.json", {"summary": "Untouched synthetic brief"})
        (self.model / "feedback.jsonl").write_text('{"id":"f","signal":"unknown"}\n')
        (self.model / "recommendations.jsonl").write_text('{"id":"r","status":"recommended"}\n')
        (self.model / "batches.jsonl").write_text('{"id":"previous-batch"}\n')
        self.research = [{"id": "candidate-one", "title": "Synthetic Tea History",
                          "creator": "Synthetic Author", "medium": "book",
                          "canonical_url": "https://publisher.example/book",
                          "description": "A synthetic account of tea and history.",
                          "verification": {"checked_at": "2026-11-09", "urls": [
                              "https://publisher.example/book"]}}]
        self.delta = {
            "schema_version": 1,
            "sources": [{"id": "source-one", "kind": "publisher",
                         "locator": "https://publisher.example/book", "checked_at": "2026-11-09"}],
            "nodes": [{"id": "work-one", "type": "work", "label": "Synthetic Tea History",
                       "canonical_url": "https://publisher.example/book"},
                      {"id": "topic-tea", "type": "topic", "label": "Tea"},
                      {"id": "topic-history", "type": "topic", "label": "History"},
                      {"id": "creator-one", "type": "creator", "label": "Synthetic Author"}],
            "edges": [
                {"id": "edge-tea", "source": "work-one", "relation": "about", "target": "topic-tea",
                 "status": "verified", "confidence": .9, "source_provenance": ["source-one"],
                 "assertion_method": "host_verified_publisher_description",
                 "support_note": "The publisher identifies tea as the subject."},
                {"id": "edge-history", "source": "work-one", "relation": "about", "target": "topic-history",
                 "status": "verified", "confidence": .9, "source_provenance": ["source-one"],
                 "assertion_method": "host_verified_publisher_description",
                 "support_note": "The publisher describes the work as a history."},
                {"id": "edge-creator", "source": "work-one", "relation": "created_by", "target": "creator-one",
                 "status": "verified", "confidence": 1, "source_provenance": ["source-one"],
                 "assertion_method": "host_verified_publisher_metadata",
                 "support_note": "The publisher names the author."}]
        }

    def write(self, name, value):
        (self.model / name).write_text(json.dumps(value), encoding="utf-8")

    def read(self, name):
        return json.loads((self.model / name).read_text(encoding="utf-8"))

    def review(self, batch="batch-one", research=None):
        return API["update_plan"](self.root, self.research if research is None else research, batch)

    def check(self, batch="batch-one", research=None):
        return API["check_update"](self.root, self.research if research is None else research, batch)

    def complete(self, review=None, delta=None, research=None, reason="Saved the verified content relationships."):
        return API["complete_update"](self.root, self.research if research is None else research,
                                      review or self.review(), delta=delta, reason=reason)

    def save(self):
        return self.complete(delta=copy.deepcopy(self.delta))

    def test_missing_graph_is_empty_and_planning_is_read_only(self):
        before = {p.name: p.read_bytes() for p in self.model.iterdir()}
        review = self.review()
        self.assertTrue(review["review_due"])
        self.assertFalse(review["completed"])
        self.assertEqual(review["counts"], {"sources": 0, "nodes": 0, "edges": 0})
        self.assertFalse(self.check()["completed"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.model.iterdir()})

    def test_saved_receipt_matches_actual_graph_and_preserves_personal_state(self):
        before = {p.name: p.read_bytes() for p in self.model.iterdir()}
        result = self.save()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["receipt"]["outcome"], "saved")
        graph = self.read("graph.json")
        self.assertEqual([len(graph[k]) for k in ("sources", "nodes", "edges")], [1, 4, 3])
        self.assertTrue(self.check()["completed"])
        self.assertFalse(self.check()["review_due"])
        self.assertEqual(before, {name: (self.model / name).read_bytes() for name in before})

    def test_saved_relationships_supply_real_convergence_without_preference_updates(self):
        self.save()
        profile = {"interests": [
            {"id": "interest-tea", "topic": "Tea", "kind": "explicit", "source_provenance": ["user-tea"]},
            {"id": "interest-history", "topic": "History", "kind": "explicit", "source_provenance": ["user-history"]}]}
        before = copy.deepcopy(profile)
        result = API["GRAPH"]["frontier"](self.read("graph.json"), profile, history=[], feedback=[], seed=42, count=3)
        work = next(route for route in result["connected"] if route["destination"]["id"] == "work-one")
        self.assertIn("converging_route", work)
        self.assertNotEqual(work["anchor_id"], work["converging_route"]["anchor_id"])
        self.assertEqual({work["anchor_id"], work["converging_route"]["anchor_id"]},
                         {"interest-tea", "interest-history"})
        self.assertEqual(profile, before)
        self.assertFalse(result["profile_changed"])

    def test_current_completion_reuses_without_writes_or_full_graph_context(self):
        self.save()
        before = {p.name: p.read_bytes() for p in self.model.iterdir()}
        for _ in range(3):
            review = self.review()
            self.assertFalse(review["review_due"])
            self.assertTrue(self.check()["completed"])
            self.assertNotIn("nodes", review)
            self.assertNotIn("edges", review)
            self.assertNotIn("research", review)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.model.iterdir()})

    def test_no_supported_changes_completes_without_creating_preference_or_graph_facts(self):
        result = self.complete(reason="Research supplied no defensible new content relationship.")
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertTrue(self.check()["completed"])
        if (self.model / "graph.json").exists():
            self.assertEqual(len(self.read("graph.json")["edges"]), 0)

    def test_batch_identity_is_part_of_completion_freshness(self):
        self.save()
        self.assertFalse(self.check("another-batch")["completed"])
        self.assertTrue(self.review("another-batch")["review_due"])

    def test_research_content_or_source_changes_expire_completion(self):
        self.save()
        for mutate in (
            lambda r: r[0].update(description="A corrected factual account."),
            lambda r: r[0]["verification"].update(checked_at="2026-11-10"),
            lambda r: r[0]["verification"]["urls"].append("https://publisher.example/correction"),
            lambda r: r.append({**copy.deepcopy(r[0]), "id": "another-candidate"}),
        ):
            research = copy.deepcopy(self.research)
            mutate(research)
            self.assertFalse(self.check(research=research)["completed"])

    def test_scoring_and_personal_rationale_do_not_trigger_graph_research_again(self):
        self.save()
        research = copy.deepcopy(self.research)
        research[0].update(scores={"depth": 5}, personal_connection={"explanation": "Different fit rationale"},
                           hypothesis_id="tentative-personal-hypothesis")
        self.assertTrue(self.check(research=research)["completed"])

    def test_changed_graph_expires_receipt_and_rejects_stale_review(self):
        self.save()
        review = self.review("next-batch")
        graph = self.read("graph.json")
        graph["nodes"].append({"id": "new-topic", "type": "topic", "label": "New independent fact"})
        self.write("graph.json", graph)
        self.assertFalse(self.check()["completed"])
        with self.assertRaises(ValueError):
            self.complete(review=review)

    def test_changed_research_rejects_old_review(self):
        review = self.review()
        research = copy.deepcopy(self.research)
        research[0]["description"] = "Corrected description"
        with self.assertRaises(ValueError):
            self.complete(review=review, research=research, delta=self.delta)
        self.assertFalse((self.model / "graph.json").exists())

    def test_intervening_completion_rejects_old_review(self):
        first, second = self.review(), self.review()
        self.complete(review=first, delta=self.delta)
        with self.assertRaises(ValueError):
            self.complete(review=second, delta=self.delta)

    def test_same_delta_in_next_batch_is_idempotent(self):
        self.save()
        before = (self.model / "graph.json").read_bytes()
        result = self.complete(review=self.review("batch-two"), delta=self.delta)
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertEqual(before, (self.model / "graph.json").read_bytes())
        self.assertTrue(self.check("batch-two")["completed"])

    def test_partial_verified_edge_cannot_inherit_validation_for_another_work_source(self):
        other = {"id": "candidate-two", "title": "Another work", "creator": "Another author",
                 "canonical_url": "https://publisher.example/other",
                 "verification": {"checked_at": "2026-11-09", "urls": ["https://publisher.example/other"]}}
        self.research.append(other)
        self.delta["sources"].append({"id": "source-two", "kind": "publisher",
                                      "locator": "https://publisher.example/other", "checked_at": "2026-11-09"})
        self.delta["nodes"].append({"id": "work-two", "type": "work", "label": "Another work",
                                    "canonical_url": "https://publisher.example/other"})
        self.save()
        before = {name: (self.model / name).read_bytes() for name in ("graph.json", "graph-maintenance.json")}
        for support in (None, "The other publisher source supposedly supports the first work."):
            with self.subTest(explicit_support=support is not None):
                edge = {"id": "edge-tea", "source": "work-one", "relation": "about", "target": "topic-tea",
                        "source_provenance": ["source-two"]}
                if support is not None:
                    edge["support_note"] = support
                delta = {"schema_version": 1, "sources": [], "nodes": [], "edges": [edge]}
                message = "support_note" if support is None else "not verified for that work"
                with self.assertRaisesRegex(ValueError, message):
                    self.complete(review=self.review("batch-two", [other]), research=[other], delta=delta)
                self.assertEqual(before, {name: (self.model / name).read_bytes() for name in before})
                self.assertFalse(self.check("batch-two", [other])["completed"])
                self.assertTrue(self.check()["completed"])

    def test_partial_verified_change_still_requires_current_research_sources(self):
        self.save()
        before = (self.model / "graph-maintenance.json").read_bytes()
        edge = {"id": "edge-tea", "source": "work-one", "relation": "about", "target": "topic-tea",
                "source_provenance": ["source-one"], "confidence": .8,
                "support_note": "A changed claim needs verification in this research batch."}
        delta = {"schema_version": 1, "sources": [], "nodes": [], "edges": [edge]}
        with self.assertRaisesRegex(ValueError, "current research"):
            self.complete(review=self.review("batch-two", []), research=[], delta=delta)
        self.assertEqual(before, (self.model / "graph-maintenance.json").read_bytes())
        self.assertEqual(self.read("graph.json")["edges"][0]["confidence"], .9)

    def test_partial_verified_change_with_current_work_evidence_records_a_saved_receipt(self):
        self.save()
        edge = {"id": "edge-tea", "source": "work-one", "relation": "about", "target": "topic-tea",
                "source_provenance": ["source-one"], "confidence": .8,
                "support_note": "Rechecked the publisher's account of tea."}
        delta = {"schema_version": 1, "sources": [], "nodes": [], "edges": [edge]}
        result = self.complete(review=self.review("batch-two"), delta=delta)
        stored = self.read("graph.json")["edges"][0]
        self.assertEqual(result["receipt"]["outcome"], "saved")
        self.assertEqual(result["receipt"]["counts"], {"sources": 0, "nodes": 0, "edges": 1})
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(stored["assertion_method"], "host_verified_publisher_description")
        self.assertEqual(stored["confidence"], .8)
        self.assertTrue(self.check("batch-two")["completed"])

    def test_partial_verified_noop_preserves_graph_without_current_research(self):
        self.save()
        before = (self.model / "graph.json").read_bytes()
        for identifier in ("edge-tea", "alias-edge-tea"):
            with self.subTest(identifier=identifier):
                edge = {"id": identifier, "source": "work-one", "relation": "about", "target": "topic-tea",
                        "source_provenance": ["source-one"]}
                delta = {"schema_version": 1, "sources": [], "nodes": [], "edges": [edge]}
                result = self.complete(review=self.review(identifier, []), research=[], delta=delta)
                self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
                self.assertEqual(result["receipt"]["counts"]["edges"], 0)
                self.assertEqual(before, (self.model / "graph.json").read_bytes())
                self.assertTrue(self.check(identifier, [])["completed"])

    def test_new_ids_for_existing_identities_remap_without_duplicate_graph_records(self):
        self.save()
        delta = copy.deepcopy(self.delta)
        mapping = {item["id"]: "alias-" + item["id"] for section in ("sources", "nodes", "edges")
                   for item in delta[section]}
        for section in ("sources", "nodes", "edges"):
            for item in delta[section]:
                item["id"] = mapping[item["id"]]
                for endpoint in ("source", "target"):
                    if endpoint in item:
                        item[endpoint] = mapping[item[endpoint]]
                if "source_provenance" in item:
                    item["source_provenance"] = [mapping[value] for value in item["source_provenance"]]
        result = self.complete(review=self.review("batch-two"), delta=delta)
        graph = self.read("graph.json")
        self.assertEqual([len(graph[k]) for k in ("sources", "nodes", "edges")], [1, 4, 3])
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertEqual({n["id"] for n in graph["nodes"]}, {n["id"] for n in self.delta["nodes"]})

    def test_existing_source_id_cannot_be_retargeted(self):
        self.save()
        research = copy.deepcopy(self.research)
        research[0]["verification"]["urls"].append("https://publisher.example/other")
        delta = copy.deepcopy(self.delta)
        delta["sources"][0]["locator"] = "https://publisher.example/other"
        with self.assertRaises(ValueError):
            self.complete(review=self.review("batch-two", research), research=research, delta=delta)

    def test_existing_work_id_cannot_be_retargeted(self):
        self.save()
        research = copy.deepcopy(self.research)
        research[0]["canonical_url"] = "https://publisher.example/other"
        research[0]["verification"]["urls"].append("https://publisher.example/other")
        delta = copy.deepcopy(self.delta)
        delta["nodes"][0]["canonical_url"] = "https://publisher.example/other"
        with self.assertRaises(ValueError):
            self.complete(review=self.review("batch-two", research), research=research, delta=delta)

    def test_existing_edge_id_cannot_be_retargeted(self):
        self.save()
        delta = copy.deepcopy(self.delta)
        delta["edges"][0]["target"] = "topic-history"
        with self.assertRaises(ValueError):
            self.complete(review=self.review("batch-two"), delta=delta)

    def test_new_verified_edge_requires_researched_dated_source_and_support_note(self):
        mutations = [
            lambda d: d["sources"][0].update(locator="https://unread.example/invented"),
            lambda d: d["sources"][0].update(checked_at=None),
            lambda d: d["edges"][0].update(source_provenance=[]),
            lambda d: d["edges"][0].pop("support_note"),
            lambda d: d["edges"][0].update(support_note=" " * 5),
            lambda d: d["edges"][0].update(support_note="x" * 501),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                delta = copy.deepcopy(self.delta)
                mutate(delta)
                with self.assertRaises(ValueError):
                    self.complete(delta=delta)
                self.assertFalse((self.model / "graph.json").exists())

    def test_preference_relations_and_personal_fields_are_not_content_facts(self):
        for section, key, value in (("edges", "relation", "likes"),
                                    ("nodes", "hypothesis_id", "personal-hypothesis"),
                                    ("edges", "personal_connection", {"basis": "explicit_interest"})):
            delta = copy.deepcopy(self.delta)
            delta[section][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.complete(delta=delta)

    def test_relation_types_and_dangling_endpoints_are_validated(self):
        for change in ({"relation": "created_by"}, {"target": "missing-topic"}, {"confidence": float("nan")}):
            delta = copy.deepcopy(self.delta)
            delta["edges"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.complete(delta=delta)

    def test_overlarge_delta_is_rejected_without_partial_write(self):
        for section, limit in (("sources", 8), ("nodes", 24), ("edges", 24)):
            delta = copy.deepcopy(self.delta)
            delta[section] = [{**copy.deepcopy(delta[section][0]), "id": section + str(n)}
                              for n in range(limit + 1)]
            with self.subTest(section=section), self.assertRaises(ValueError):
                self.complete(delta=delta)
            self.assertFalse((self.model / "graph.json").exists())

    def test_incoming_duplicate_ids_are_rejected(self):
        delta = copy.deepcopy(self.delta)
        delta["nodes"].append(copy.deepcopy(delta["nodes"][0]))
        with self.assertRaises(ValueError):
            self.complete(delta=delta)

    def test_invalid_existing_graph_is_not_silently_replaced(self):
        self.write("graph.json", {"schema_version": 1, "sources": [], "nodes": [], "edges": [{"id": "dangling"}]})
        before = (self.model / "graph.json").read_bytes()
        with self.assertRaises(ValueError):
            self.review()
        self.assertEqual(before, (self.model / "graph.json").read_bytes())

    def test_corrupt_receipt_requires_fresh_review_and_can_be_recovered(self):
        self.save()
        path = self.model / "graph-maintenance.json"
        for corrupt in (b"broken JSON", b"\xff", b'{"schema_version":1}'):
            with self.subTest(corrupt=corrupt):
                path.write_bytes(corrupt)
                self.assertFalse(self.check()["completed"])
                review = self.review()
                self.assertTrue(review["review_due"])
                self.complete(review=review)
                self.assertTrue(self.check()["completed"])

    def test_corrupt_receipt_repair_cannot_overwrite_an_intervening_repair(self):
        (self.model / "graph-maintenance.json").write_text("broken")
        review = self.review()
        self.complete(review=review)
        with self.assertRaises(ValueError):
            self.complete(review=review)

    def test_existing_graph_metadata_is_preserved(self):
        self.save()
        graph = self.read("graph.json")
        graph["editor_note"] = "Preserve unrelated graph metadata"
        graph["nodes"][0]["external_catalog_id"] = "catalog-123"
        self.write("graph.json", graph)
        self.complete(review=self.review("batch-two"), delta=self.delta)
        saved = self.read("graph.json")
        self.assertEqual(saved["editor_note"], graph["editor_note"])
        self.assertEqual(saved["nodes"][0]["external_catalog_id"], "catalog-123")

    def test_graph_lock_prevents_competing_writes(self):
        (self.model / ".graph.lock").write_text("another writer")
        with self.assertRaises(ValueError):
            self.complete(delta=self.delta)
        self.assertFalse((self.model / "graph.json").exists())

    def test_inputs_are_not_mutated(self):
        review = self.review()
        original = copy.deepcopy((self.research, review, self.delta))
        self.complete(review=review, delta=self.delta)
        self.assertEqual((self.research, review, self.delta), original)

    def test_empty_research_can_record_an_honest_no_changes_outcome(self):
        review = self.review(research=[])
        result = self.complete(review=review, research=[], reason="No candidates supplied verified content relationships.")
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertTrue(self.check(research=[])["completed"])

    def test_related_to_aliases_are_deduplicated_in_either_direction(self):
        delta = copy.deepcopy(self.delta)
        delta["edges"].append({"id": "edge-topics", "source": "topic-tea", "relation": "related_to",
                               "target": "topic-history", "status": "verified", "confidence": .7,
                               "source_provenance": ["source-one"], "assertion_method": "host_verified_source",
                               "support_note": "The synthetic source explicitly connects these two topics."})
        self.complete(delta=delta)
        delta["edges"][-1].update(id="alias-edge-topics", source="topic-history", target="topic-tea")
        result = self.complete(review=self.review("batch-two"), delta=delta)
        self.assertEqual(len(self.read("graph.json")["edges"]), 4)
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")

    def test_private_graph_and_receipt_symlinks_cannot_escape_the_model(self):
        outside = self.root / "outside.json"
        outside.write_text('{"private":"untouched"}')
        for name in ("graph.json", "graph-maintenance.json"):
            path = self.model / name
            path.symlink_to(outside)
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                self.review()
            self.assertEqual(outside.read_text(), '{"private":"untouched"}')
            path.unlink()

    def test_another_work_source_cannot_support_this_work_relationship(self):
        research = copy.deepcopy(self.research)
        research.append({"id": "candidate-two", "title": "Another work", "creator": "Another author",
                         "canonical_url": "https://publisher.example/other",
                         "verification": {"checked_at": "2026-11-09",
                                          "urls": ["https://publisher.example/other"]}})
        delta = copy.deepcopy(self.delta)
        delta["sources"][0]["locator"] = "https://publisher.example/other"
        with self.assertRaises(ValueError):
            self.complete(review=self.review(research=research), research=research, delta=delta)
        self.assertFalse((self.model / "graph.json").exists())

    def test_graph_replace_failure_does_not_create_completion_or_partial_graph(self):
        review = self.review()
        with mock.patch.object(API["os"], "replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.complete(review=review, delta=self.delta)
        self.assertFalse((self.model / "graph.json").exists())
        self.assertFalse((self.model / "graph-maintenance.json").exists())
        self.assertFalse((self.model / ".graph.lock").exists())
        self.assertFalse(list(self.model.glob(".graph-update-*")))
        self.assertFalse(self.check()["completed"])

    def test_receipt_replace_failure_leaves_graph_saved_but_workflow_incomplete(self):
        original_replace = API["os"].replace

        def replace(source, destination):
            if Path(destination).name == "graph-maintenance.json":
                raise OSError("synthetic interrupted receipt write")
            return original_replace(source, destination)

        with mock.patch.object(API["os"], "replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.complete(delta=self.delta)
        self.assertEqual(len(self.read("graph.json")["edges"]), 3)
        self.assertFalse(self.check()["completed"])
        self.assertFalse((self.model / ".graph.lock").exists())
        self.assertFalse(list(self.model.glob(".graph-update-*")))
        # A new reviewed no-op completes the interrupted batch honestly.
        result = self.complete(delta=self.delta)
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertTrue(self.check()["completed"])

    def test_change_during_graph_staging_is_not_overwritten(self):
        external = {"schema_version": 1, "sources": [], "nodes": [
            {"id": "concurrent", "type": "topic", "label": "Concurrent source"}], "edges": []}
        real_fsync = API["os"].fsync

        def sync_then_change(descriptor):
            real_fsync(descriptor)
            self.write("graph.json", external)

        with mock.patch.object(API["os"], "fsync", side_effect=sync_then_change):
            with self.assertRaises(ValueError):
                self.complete(delta=self.delta)
        self.assertEqual(self.read("graph.json"), external)
        self.assertFalse((self.model / "graph-maintenance.json").exists())

    def test_change_during_receipt_staging_is_not_overwritten(self):
        real_fsync = API["os"].fsync
        count = 0

        def sync_then_change(descriptor):
            nonlocal count
            real_fsync(descriptor)
            count += 1
            if count == 2:
                self.write("graph-maintenance.json", {"intervening_writer": True})

        with mock.patch.object(API["os"], "fsync", side_effect=sync_then_change):
            with self.assertRaises(ValueError):
                self.complete(delta=self.delta)
        self.assertEqual(self.read("graph-maintenance.json"), {"intervening_writer": True})
        self.assertFalse(self.check()["completed"])

    def test_retracted_edge_cannot_be_reactivated_through_an_alias_id(self):
        self.save()
        graph = self.read("graph.json")
        graph["edges"][0]["status"] = "retracted"
        self.write("graph.json", graph)
        delta = copy.deepcopy(self.delta)
        delta["edges"][0]["id"] = "alias-edge-tea"
        with self.assertRaises(ValueError):
            self.complete(review=self.review("batch-two"), delta=delta)
        self.assertEqual(self.read("graph.json")["edges"][0]["status"], "retracted")

    def test_partial_retracted_alias_noop_does_not_reactivate_the_edge(self):
        self.save()
        graph = self.read("graph.json")
        graph["edges"][0]["status"] = "retracted"
        self.write("graph.json", graph)
        before = (self.model / "graph.json").read_bytes()
        edge = {"id": "alias-edge-tea", "source": "work-one", "relation": "about", "target": "topic-tea",
                "source_provenance": ["source-one"]}
        delta = {"schema_version": 1, "sources": [], "nodes": [], "edges": [edge]}
        result = self.complete(review=self.review("batch-two", []), research=[], delta=delta)
        self.assertEqual(result["receipt"]["outcome"], "no_supported_changes")
        self.assertEqual(before, (self.model / "graph.json").read_bytes())
        self.assertEqual(self.read("graph.json")["edges"][0]["status"], "retracted")
        self.assertTrue(self.check("batch-two", [])["completed"])

    def test_explicit_reactivation_requires_fresh_checked_evidence(self):
        self.save()
        graph = self.read("graph.json")
        graph["edges"][0].update(status="retracted", checked_at="2026-11-10")
        self.write("graph.json", graph)
        with self.assertRaises(ValueError):
            self.complete(review=self.review("batch-two"), delta=self.delta)
        research = copy.deepcopy(self.research)
        research[0]["verification"]["checked_at"] = "2026-11-11"
        delta = copy.deepcopy(self.delta)
        delta["sources"][0]["checked_at"] = "2026-11-11"
        delta["edges"][0]["checked_at"] = "2026-11-11"
        self.complete(review=self.review("batch-two", research), research=research, delta=delta)
        self.assertEqual(self.read("graph.json")["edges"][0]["status"], "verified")

    def test_invalid_completion_reasons_do_not_mark_work_complete(self):
        for reason in ("", "   ", "x" * 501):
            with self.subTest(reason_length=len(reason)), self.assertRaises(ValueError):
                self.complete(delta=self.delta, reason=reason)
        self.assertFalse(self.check()["completed"])

    def test_planner_output_does_not_grow_with_full_graph_or_raw_research_prose(self):
        graph = {"schema_version": 1, "sources": [], "edges": [], "nodes": [
            {"id": "topic-" + str(i), "type": "topic", "label": "Synthetic topic " + str(i),
             "description": "Long unrelated context " * 100} for i in range(1000)]}
        self.write("graph.json", graph)
        self.research[0]["description"] = "Very long researched content " * 10000
        review = self.review()
        self.assertLess(len(json.dumps(review)), 3000)
        self.complete(review=review)
        self.assertLess(len(json.dumps(self.check())), 2000)

    def test_cli_pending_check_is_nonzero_and_completed_check_succeeds(self):
        path = self.model / "research.json"
        path.write_text(json.dumps(self.research))
        argv = ["graph-update-check", "--root", str(self.root), "--research", str(path), "--batch-id", "batch-one"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            pending = API["main"](argv)
        self.assertNotEqual(pending, 0)
        self.assertFalse(json.loads(stdout.getvalue())["completed"])
        self.save()
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            completed = API["main"](argv)
        self.assertEqual(completed, 0)
        self.assertTrue(json.loads(stdout.getvalue())["completed"])


if __name__ == "__main__":
    unittest.main()
