"""Exercise local skill installation and the public, synthetic table demo."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/curation.py"
SOURCE = MODULE.parents[1]
spec = importlib.util.spec_from_file_location("curation_install", MODULE)
curation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(curation)


class InstallationTests(unittest.TestCase):
    def assert_only_literal_anchor_added(self, model, before, anchor_id, topic):
        """Rooted discovery may add representation, never preference or content facts."""
        after = {path.name: path.read_bytes() for path in model.iterdir()}
        self.assertEqual(set(after), set(before) | {"graph-anchors.json"})
        self.assertEqual({name: data for name, data in before.items() if name != "graph.json"},
                         {name: after[name] for name in before if name != "graph.json"})
        old_graph, graph = json.loads(before["graph.json"]), json.loads(after["graph.json"])
        self.assertEqual(graph["sources"], old_graph["sources"])
        self.assertEqual(graph["edges"], old_graph["edges"])
        old_nodes = {node["id"]: node for node in old_graph["nodes"]}
        self.assertEqual(old_nodes, {node["id"]: node for node in graph["nodes"] if node["id"] in old_nodes})
        added = [node for node in graph["nodes"] if node["id"] not in old_nodes]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0], {"id": added[0]["id"], "type": "topic", "label": topic})
        mappings = json.loads(after["graph-anchors.json"])["mappings"]
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["anchor_id"], anchor_id)
        self.assertEqual(mappings[0]["node_id"], added[0]["id"])
        self.assertEqual(mappings[0]["method"], "generated")

    def complete_synthetic_review(self, runtime, workspace, plan_path, cwd):
        """Exercise hypothesis maintenance before discovery and its anchor sync."""
        planned = subprocess.run(
            [sys.executable, str(runtime), "hypotheses", "maintenance-plan",
             "--root", str(workspace), "--plan", str(plan_path)],
            cwd=cwd, capture_output=True, text=True, check=True)
        review = json.loads(planned.stdout)
        if review["review_due"]:
            review_path = cwd / "maintenance-review.json"
            review_path.write_text(planned.stdout)
            completed = subprocess.run(
                [sys.executable, str(runtime), "hypotheses", "maintenance-complete",
                 "--root", str(workspace), "--review", str(review_path),
                 "--outcome", "no_proposal", "--reason",
                 "These synthetic anchors do not establish a defensible additional preference."],
                cwd=cwd, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(completed.stdout)["status"], "completed")

    def test_trurl_root_preserves_legacy_root_and_explicit_priority(self):
        args = SimpleNamespace(profile=None, root=None)
        cases = [({"CURATION_ROOT": "/legacy-root"}, None, "/legacy-root"),
                 ({"TRURL_ROOT": "/trurl-root"}, None, "/trurl-root"),
                 ({"CURATION_ROOT": "/legacy-root", "TRURL_ROOT": "/trurl-root"}, None, "/trurl-root"),
                 ({"TRURL_ROOT": "/trurl-root"}, "/explicit-root", "/explicit-root")]
        for environment, explicit, expected in cases:
            with self.subTest(environment=environment, explicit=explicit), patch.dict(os.environ, environment, clear=True):
                args.root = explicit
                self.assertEqual(curation._profile_path(args), Path(expected) / "model/profile.json")

    def test_only_skill_is_installed_without_private_state_or_caches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (source / "model").mkdir()
            (source / "model/profile.json").write_text('{"private":"do not copy"}')
            (source / "feedback.jsonl").write_text("private feedback")
            (source / "graph.json").write_text('{"private_graph":"must not be packaged"}')
            (source / "references/graph.json").write_text('{"private_graph":"nested state must not be packaged"}')
            (source / "references/curators-brief.json").write_text('{"summary":"private taste summary"}')
            (source / "scripts/__pycache__").mkdir()
            (source / "scripts/__pycache__/curation.pyc").write_bytes(b"generated cache")
            result = curation.install_skill(root / "installed", source=source)
            installed = Path(result["installed"])
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "LICENSE").is_file())
            self.assertTrue((installed / "references/adaptive-weights.md").is_file())
            self.assertFalse((installed / "model").exists())
            self.assertFalse((installed / "feedback.jsonl").exists())
            self.assertFalse((installed / "graph.json").exists())
            self.assertFalse((installed / "references/graph.json").exists())
            self.assertFalse((installed / "references/curators-brief.json").exists())
            self.assertTrue((installed / "scripts/graph.py").is_file())
            self.assertTrue((installed / "scripts/brief.py").is_file())
            self.assertFalse((installed / "scripts/__pycache__").exists())
            self.assertFalse(result["personal_model_copied"])

    def test_existing_install_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "existing"
            destination.mkdir()
            sentinel = destination / "user-changes.txt"
            sentinel.write_text("keep this")
            with self.assertRaises(FileExistsError):
                curation.install_skill(destination)
            self.assertEqual(sentinel.read_text(), "keep this")

    def test_installed_runtime_works_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "installed"
            curation.install_skill(destination)
            runtime = destination / "scripts/curation.py"
            workspace = root / "new-workspace"
            initialized = subprocess.run(
                [sys.executable, str(runtime), "init", "--root", str(workspace)],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            planned = subprocess.run(
                [sys.executable, str(runtime), "weights", "--root", str(workspace), "--request", "surprise me", "--seed", "42"],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(json.loads(planned.stdout)["mode"], "surprise")
            profile = json.loads((workspace / "model/profile.json").read_text())
            self.assertFalse(profile["delivery"]["weekly"]["enabled"])
            self.assertEqual(profile["onboarding"]["status"], "not_started")
            self.assertEqual(profile["onboarding"]["categories"], [])
            self.assertEqual(profile["onboarding"]["anchors"], [])
            self.assertEqual(profile["interests"], [])
            self.assertTrue(all(source["permission"] == "not_asked"
                                for source in profile["onboarding"]["context_sources"].values()))
            self.assertTrue({"podcast", "lecture"}.issubset(profile["media"]["enabled"]))
            self.assertEqual(json.loads((workspace / "model/graph.json").read_text()),
                             {"schema_version": 1, "sources": [], "nodes": [], "edges": []})

    def test_installed_graph_and_open_commands_are_self_contained_and_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed"
            curation.install_skill(installed)
            runtime = installed / "scripts/curation.py"
            workspace = root / "new-workspace"
            curation.initialize(workspace)
            model = workspace / "model"
            before = {p.name: p.read_bytes() for p in model.iterdir()}
            checked = subprocess.run([sys.executable, str(runtime), "graph-check", "--graph", str(model / "graph.json")],
                                     cwd=root, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            summary = json.loads(checked.stdout)
            self.assertTrue(summary["valid"])
            self.assertEqual(summary["counts"], {"sources": 0, "nodes": 0, "edges": 0})
            frontier = subprocess.run([sys.executable, str(runtime), "frontier", "--graph", str(model / "graph.json"),
                                       "--profile", str(model / "profile.json"), "--allow-open", "--open-count", "1", "--count", "4", "--seed", "17"],
                                      cwd=root, capture_output=True, text=True)
            self.assertEqual(frontier.returncode, 0, frontier.stderr)
            routes = json.loads(frontier.stdout)
            self.assertEqual(routes["connected"], [])
            self.assertEqual(len(routes["open"]), 1)
            self.assertEqual(routes["open"][0]["personal_fit_status"], "unknown")
            self.assertTrue(routes["eligible_strata"])
            planned = subprocess.run([sys.executable, str(runtime), "weights", "--root", str(workspace), "--mode", "open"],
                                     cwd=root, capture_output=True, text=True)
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan = json.loads(planned.stdout)
            self.assertEqual(plan["mode"], "open")
            self.assertEqual(plan["effective_weights"], plan["baseline_weights"])
            plan_path = root / "plan.json"
            plan_path.write_text(planned.stdout)
            explored = subprocess.run([sys.executable, str(runtime), "explore", "--plan", str(plan_path),
                                       "--root", str(workspace), "--profile", str(model / "profile.json"), "--graph", str(model / "graph.json"), "--count", "4", "--seed", "17"],
                                      cwd=root, capture_output=True, text=True)
            self.assertEqual(explored.returncode, 0, explored.stderr)
            result = json.loads(explored.stdout)
            self.assertEqual(sum(b["lane"] == "distant" for b in result["briefs"]), 1)
            self.assertEqual(result["graph_frontier"]["open"], routes["open"])
            self.assertEqual({p.name: p.read_bytes() for p in model.iterdir()}, before)

    def test_installed_graph_validation_fails_without_modifying_bad_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed"
            curation.install_skill(installed)
            malformed = root / "malformed-graph.json"
            malformed.write_text('{"schema_version":1,"sources":[],"nodes":[],"edges":[{"id":"dangling"}]}')
            before = malformed.read_bytes()
            result = subprocess.run([sys.executable, str(installed / "scripts/curation.py"), "graph-check", "--graph", str(malformed)],
                                    cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)
            self.assertEqual(malformed.read_bytes(), before)

    def test_installed_current_opt_out_overrides_standing_permission_without_changing_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed"
            curation.install_skill(installed)
            runtime = installed / "scripts/curation.py"
            workspace = root / "synthetic-workspace"
            curation.initialize(workspace)
            profile_path = workspace / "model/profile.json"
            profile = json.loads(profile_path.read_text())
            profile["discovery"].update(lane_mix={"familiar": .2, "adjacent": .2, "distant": .6}, open_exploration={"enabled": True})
            profile["interests"] = [{"id": "synthetic-alpha", "topic": "Synthetic field alpha", "kind": "explicit",
                                     "knowledge_level": "unknown", "source_provenance": ["synthetic-user-statement"]}]
            profile_path.write_text(json.dumps(profile))
            request = "Stay close to my existing interests; no open exploration."
            closed = subprocess.run([sys.executable, str(runtime), "weights", "--profile", str(profile_path), "--mode", "personal", "--scope", "broad", "--request", request],
                                    cwd=root, capture_output=True, text=True, check=True)
            closed_plan = json.loads(closed.stdout)
            self.assertEqual(closed_plan["lane_mix"], {"familiar": .5, "adjacent": .5, "distant": 0})
            self.assertIsNone(closed_plan["selection_policy"])
            self.assertFalse(closed_plan["constraints"]["open_exploration_enabled"])
            plan_path = root / "closed-plan.json"
            plan_path.write_text(closed.stdout)
            self.complete_synthetic_review(runtime, workspace, plan_path, root)
            before = {p.name: p.read_bytes() for p in profile_path.parent.iterdir()}
            discovery = subprocess.run([sys.executable, str(runtime), "explore", "--root", str(workspace), "--profile", str(profile_path), "--plan", str(plan_path), "--count", "4", "--seed", "1701"],
                                       cwd=root, capture_output=True, text=True, check=True)
            self.assertFalse(any(b["lane"] == "distant" for b in json.loads(discovery.stdout)["briefs"]))
            later = subprocess.run([sys.executable, str(runtime), "weights", "--profile", str(profile_path), "--mode", "personal", "--scope", "broad", "--request", "A few recommendations"],
                                   cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(later.stdout)["selection_policy"]["kind"], "open_exploration_v1")
            self.assert_only_literal_anchor_added(profile_path.parent, before, "synthetic-alpha", "Synthetic field alpha")

    def test_installed_discovery_uses_shared_anchor_policy_even_without_graph_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed"
            curation.install_skill(installed)
            runtime = installed / "scripts/curation.py"
            workspace = root / "synthetic-workspace"
            curation.initialize(workspace)
            profile_path = workspace / "model/profile.json"
            profile = json.loads(profile_path.read_text())
            profile["interests"] = [
                {"id": "quoted", "kind": "explicit", "topic": "Synthetic field alpha", "quoted": True},
                {"id": "assistant-only", "kind": "tentative", "topic": "Synthetic process beta", "confidence": .9,
                 "source_provenance": [{"kind": "assistant_generated", "locator": "synthetic-assistant-output"}]},
            ]
            profile_path.write_text(json.dumps(profile))
            before = {p.name: p.read_bytes() for p in profile_path.parent.iterdir()}
            planned = subprocess.run([sys.executable, str(runtime), "weights", "--profile", str(profile_path), "--mode", "surprise", "--scope", "broad", "--seed", "42"],
                                     cwd=root, capture_output=True, text=True, check=True)
            plan_path = root / "plan.json"
            plan_path.write_text(planned.stdout)
            base = [sys.executable, str(runtime), "explore", "--root", str(workspace), "--profile", str(profile_path), "--plan", str(plan_path), "--seed", "17"]
            for graph_arguments in ([], ["--graph", str(profile_path.parent / "graph.json")]):
                result = subprocess.run(base + graph_arguments, cwd=root, capture_output=True, text=True, check=True)
                discovery = json.loads(result.stdout)
                self.assertTrue(discovery["insufficient_context"])
                self.assertEqual(discovery["briefs"], [])
                if graph_arguments:
                    self.assertEqual(discovery["graph_frontier"]["connected"], [])
            self.assertEqual({p.name: p.read_bytes() for p in profile_path.parent.iterdir()}, before)

    def test_default_destination_respects_codex_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            configured = Path(temporary) / "configured-home"
            with patch.dict(os.environ, {"CODEX_HOME": str(configured)}):
                installed = curation.install_skill()
            self.assertEqual(Path(installed["installed"]), (configured / "skills/trurl").resolve())

    def test_installed_discovery_modes_keep_profile_and_registry_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "installed"
            curation.install_skill(destination)
            runtime = destination / "scripts/curation.py"
            workspace = root / "anonymous-workspace"
            curation.initialize(workspace)
            profile_path = workspace / "model/profile.json"
            profile = json.loads(profile_path.read_text())
            profile["interests"] = [{"id": "synthetic-computing", "topic": "computing",
                                     "kind": "explicit", "confidence": 1.0,
                                     "knowledge_level": "unknown", "source_provenance": ["synthetic-user"]}]
            profile_path.write_text(json.dumps(profile))
            weighted = subprocess.run(
                [sys.executable, str(runtime), "weights", "--root", str(workspace), "--request", "surprise me", "--seed", "42"],
                cwd=root, capture_output=True, text=True, check=True)
            weight_plan = root / "weight-plan.json"
            weight_plan.write_text(weighted.stdout)
            self.complete_synthetic_review(runtime, workspace, weight_plan, root)
            before = {p.name: p.read_bytes() for p in profile_path.parent.iterdir()}
            result = subprocess.run(
                [sys.executable, str(runtime), "explore", "--root", str(workspace), "--plan", str(weight_plan), "--profile", str(workspace / "model/profile.json"), "--seed", "1701"],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            discovery = json.loads(result.stdout)
            self.assertEqual(discovery["scope"], "broad")
            self.assertEqual(discovery["seed"], 1701)
            self.assertTrue(discovery["registry_version"])
            self.assertFalse(discovery["registry_used"])
            self.assertFalse(discovery["insufficient_context"])
            self.assertTrue(any(brief["lane"] == "adjacent" for brief in discovery["briefs"]))
            self.assertFalse(any(brief["lane"] == "distant" for brief in discovery["briefs"]))
            self.assertTrue(all(brief["field"] == "computing" for brief in discovery["briefs"]))
            self.assert_only_literal_anchor_added(profile_path.parent, before, "synthetic-computing", "computing")
            synced = {p.name: p.read_bytes() for p in profile_path.parent.iterdir()}
            wildcard = subprocess.run(
                [sys.executable, str(runtime), "weights", "--root", str(workspace), "--mode", "wildcard", "--scope", "broad", "--seed", "42"],
                cwd=root, capture_output=True, text=True, check=True)
            weight_plan.write_text(wildcard.stdout)
            wild_result = subprocess.run(
                [sys.executable, str(runtime), "explore", "--root", str(workspace), "--plan", str(weight_plan), "--profile", str(profile_path), "--seed", "1701"],
                cwd=root, capture_output=True, text=True, check=True)
            wild_discovery = json.loads(wild_result.stdout)
            self.assertTrue(wild_discovery["registry_used"])
            self.assertTrue(wild_discovery["eligible_pool"])
            self.assertTrue(any(brief["lane"] == "distant" for brief in wild_discovery["briefs"]))
            self.assertEqual({p.name: p.read_bytes() for p in profile_path.parent.iterdir()}, synced)

    def test_home_fallback_uses_current_codex_shared_skills_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"CODEX_HOME": ""}), patch.object(curation.Path, "home", return_value=Path(temporary)):
                installed = curation.install_skill()
            self.assertEqual(Path(installed["installed"]), (Path(temporary) / ".agents/skills/trurl").resolve())

    def test_all_targets_use_isolated_home_and_ignore_ambient_native_homes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ambient = {variable: str(root / "must-not-use" / agent)
                       for agent, variable in curation.AGENT_HOME_VARIABLES.items()}
            with patch.dict(os.environ, ambient), patch.object(curation.Path, "home", side_effect=AssertionError("real home was consulted")):
                targets = curation.resolve_install_targets("all", home=root / "isolated")
            expected = {"codex": ".agents", "claude-code": ".claude", "pi": ".pi/agent"}
            self.assertEqual([record["agent"] for record in targets], list(expected))
            for record in targets:
                self.assertEqual(Path(record["path"]), root / "isolated" / expected[record["agent"]] / "skills/trurl")
                self.assertEqual(record["path_source"], "user_default")
            self.assertFalse((root / "isolated").exists())
            self.assertFalse((root / "must-not-use").exists())

    def test_explicit_native_environment_overrides_and_path_expansion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"HOME": str(root), "CODEX_HOME": "$PORTABLE_BASE/codex-state",
                   "CLAUDE_CONFIG_DIR": "~/claude-config", "PI_CODING_AGENT_DIR": "~/pi-config",
                   "PORTABLE_BASE": str(root / "profiles")}
            targets = {record["agent"]: record for record in curation.resolve_install_targets("all", environ=env)}
            expected = {"codex": root / "profiles/codex-state", "claude-code": root / "claude-config",
                        "pi": root / "pi-config"}
            for agent, directory in expected.items():
                self.assertEqual(Path(targets[agent]["path"]), directory / "skills/trurl")
                self.assertIn(curation.AGENT_HOME_VARIABLES[agent], targets[agent]["path_source"])
            self.assertIn("legacy", targets["codex"]["path_source"])

    def test_all_install_preflights_later_existing_target_before_any_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "isolated"
            targets = curation.resolve_install_targets("all", home=home)
            existing = Path(targets[-1]["path"])
            existing.mkdir(parents=True)
            sentinel = existing / "user-changes.txt"
            sentinel.write_text("preserve existing installation")
            with self.assertRaises(FileExistsError):
                curation.install_skill(agent="all", home=home)
            self.assertEqual(sentinel.read_text(), "preserve existing installation")
            self.assertTrue(all(not Path(record["path"]).exists() for record in targets[:-1]))
            self.assertFalse((home / ".agents").exists())

    def test_pi_cli_installs_in_native_directory_and_preserves_existing_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            ambient = Path(temporary) / "ambient-pi"
            env = dict(os.environ, PI_CODING_AGENT_DIR=str(ambient))
            command = [sys.executable, str(MODULE), "install", "--agent", "pi", "--home", str(home)]
            result = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / ".pi/agent/skills/trurl"
            self.assertEqual(Path(json.loads(result.stdout)["installed"]), installed.resolve())
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertFalse((installed / "model").exists())
            self.assertFalse(ambient.exists())
            sentinel = installed / "local-note.txt"
            sentinel.write_text("preserve the existing skill")
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 2)
            self.assertIn("installation already exists", again.stderr)
            self.assertEqual(sentinel.read_text(), "preserve the existing skill")

    def test_pi_agent_directory_override_and_exact_project_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"HOME": str(root), "PI_CODING_AGENT_DIR": "~/custom-agent"}
            installed = curation.install_skill(agent="pi", environ=env)
            self.assertEqual(Path(installed["installed"]), (root / "custom-agent/skills/trurl").resolve())
            self.assertEqual(installed["path_source"], "PI_CODING_AGENT_DIR")
            project_skill = root / "project/.pi/skills/trurl"
            project = curation.install_skill(agent="pi", destination=project_skill, environ=env)
            self.assertEqual(Path(project["installed"]), project_skill.resolve())
            self.assertEqual(project["path_source"], "destination")
            self.assertFalse((root / ".pi").exists())

    def test_pi_native_override_does_not_expand_literal_environment_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"HOME": str(root), "PI_CODING_AGENT_DIR": "~/$PI_PROFILE",
                   "PI_PROFILE": "must-not-expand"}
            target, = curation.resolve_install_targets("pi", environ=env)
            self.assertEqual(Path(target["path"]), root / "$PI_PROFILE/skills/trurl")
            self.assertFalse((root / "$PI_PROFILE").exists())
            self.assertFalse((root / "must-not-expand").exists())

    def test_all_install_preflights_invalid_parent_and_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            (home / ".claude").write_text("this is not a directory")
            with self.assertRaises(ValueError):
                curation.install_skill(agent="all", home=home)
            self.assertFalse((home / ".agents").exists())
            shared = root / "shared"
            env = {"HOME": str(root), "CODEX_HOME": str(shared), "CLAUDE_CONFIG_DIR": str(shared)}
            with self.assertRaises(ValueError):
                curation.install_skill(agent="all", environ=env)
            self.assertFalse(shared.exists())

    def test_failed_all_copy_rolls_back_only_new_installations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "new-home"
            sentinel = root / "unrelated-file"
            sentinel.write_text("preserve")
            copytree = shutil.copytree
            calls = []
            def fail_second(source, destination, *args, **kwargs):
                if Path(source).resolve() == SOURCE.resolve():
                    calls.append(destination)
                    if len(calls) == 2:
                        raise OSError("synthetic copy failure")
                return copytree(source, destination, *args, **kwargs)
            with patch.object(curation.shutil, "copytree", side_effect=fail_second):
                with self.assertRaises(OSError):
                    curation.install_skill(agent="all", home=home)
            self.assertFalse(home.exists())
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_destination_stays_exact_for_single_host_and_is_rejected_for_all(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exact = root / "specific-directory"
            result = curation.install_skill(exact, agent="claude-code", home=root / "unused-home")
            self.assertEqual(Path(result["installed"]), exact.resolve())
            self.assertEqual(result["agent"], "claude-code")
            self.assertFalse((root / "unused-home").exists())
            with self.assertRaises(ValueError):
                curation.install_skill(root / "ambiguous", agent="all", home=root / "home")
            self.assertFalse((root / "home").exists())
            self.assertFalse((root / "ambiguous").exists())

    def test_all_host_copies_run_installed_cli_and_doctor_without_copying_personal_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (source / "model").mkdir()
            marker = "synthetic private state must stay outside installed copies"
            (source / "model/profile.json").write_text(marker)
            (source / "graph.json").write_text(marker)
            home = root / "home"
            installed = curation.install_skill(agent="all", home=home, source=source)["installations"]
            self.assertEqual([record["agent"] for record in installed], ["codex", "claude-code", "pi"])
            env = dict(os.environ, PATH="")
            for record in installed:
                folder = Path(record["installed"])
                self.assertFalse((folder / "model").exists())
                self.assertFalse((folder / "graph.json").exists())
                self.assertTrue(all(marker.encode() not in path.read_bytes() for path in folder.rglob("*") if path.is_file()))
                runtime = folder / "scripts/curation.py"
                workspace = root / ("workspace-" + record["agent"])
                initialized = subprocess.run([sys.executable, str(runtime), "init", "--root", str(workspace)],
                                             cwd=root, capture_output=True, text=True, env=env)
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                model_before = {path.name: path.read_bytes() for path in (workspace / "model").iterdir()}
                demo = subprocess.run([sys.executable, str(runtime), "demo", "--fixed"], cwd=workspace,
                                      capture_output=True, text=True, env=env)
                self.assertEqual(demo.returncode, 0, demo.stderr)
                self.assertFalse(json.loads(demo.stdout)["baseline_changed"])
                diagnosed = subprocess.run([sys.executable, str(runtime), "doctor", "--agent", record["agent"],
                                             "--home", str(home), "--root", str(workspace)],
                                            cwd=root, capture_output=True, text=True, env=env)
                self.assertEqual(diagnosed.returncode, 0, diagnosed.stderr)
                report = json.loads(diagnosed.stdout)
                self.assertTrue(report["ok"])
                self.assertFalse(report["root"]["contents_read"])
                self.assertTrue(all(report["hosts"][0]["checks"].values()))
                self.assertFalse(report["hosts"][0]["full_host_tested"])
                self.assertFalse(report["hosts"][0]["cli"]["available"])
                self.assertEqual({path.name: path.read_bytes() for path in (workspace / "model").iterdir()}, model_before)

    def test_doctor_reports_missing_install_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "missing-home"
            report = curation.doctor(home=home, environ={"PATH": ""})
            self.assertFalse(report["ok"])
            self.assertEqual([host["agent"] for host in report["hosts"]], ["codex", "claude-code", "pi"])
            self.assertTrue(all(not host["checks"]["folder"] for host in report["hosts"]))
            self.assertFalse(home.exists())

    def test_doctor_checks_actual_bundled_references_and_runtime_syntax(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "installed"
            curation.install_skill(target)
            (target / "references/onboarding.md").unlink()
            missing = curation.doctor(agent="codex", destination=target, environ={"PATH": ""})
            self.assertFalse(missing["hosts"][0]["checks"]["bundled_references"])
            self.assertFalse(missing["hosts"][0]["checks"]["runtime_smoke"])
            self.assertTrue(any("onboarding.md" in error for error in missing["hosts"][0]["errors"]))
            (target / "scripts/diversity.py").write_text("def invalid syntax")
            broken = curation.doctor(agent="codex", destination=target, environ={"PATH": ""})
            self.assertFalse(broken["hosts"][0]["checks"]["runtime_files"])
            self.assertFalse(broken["ok"])

    def test_doctor_separates_cli_presence_from_full_host_testing_and_reads_no_model_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "installed"
            curation.install_skill(target)
            workspace = root / "workspace"
            model = workspace / "model"
            model.mkdir(parents=True)
            (model / "profile.json").write_text("not JSON: contents should not be inspected")
            before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            with patch.object(curation.shutil, "which", return_value="/synthetic/bin/codex"):
                report = curation.doctor(agent="codex", destination=target, root=workspace)
            self.assertTrue(report["ok"])
            self.assertTrue(report["hosts"][0]["cli"]["available"])
            self.assertFalse(report["hosts"][0]["full_host_tested"])
            self.assertFalse(report["root"]["contents_read"])
            self.assertFalse(report["changed"])
            self.assertEqual({str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}, before)

    def test_cli_all_install_doctor_and_ambiguous_destination_exit_statuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "isolated"
            env = dict(os.environ, PATH="")
            missing = subprocess.run([sys.executable, str(MODULE), "doctor", "--agent", "all", "--home", str(home)],
                                     cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(missing.returncode, 1)
            self.assertFalse(json.loads(missing.stdout)["ok"])
            installed = subprocess.run([sys.executable, str(MODULE), "install", "--agent", "all", "--home", str(home)],
                                       cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual([record["agent"] for record in json.loads(installed.stdout)["installations"]],
                             ["codex", "claude-code", "pi"])
            report = subprocess.run([sys.executable, str(MODULE), "doctor", "--agent", "all", "--home", str(home)],
                                    cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertTrue(json.loads(report.stdout)["ok"])
            ambiguous = subprocess.run([sys.executable, str(MODULE), "install", "--agent", "all", "--home", str(root / "other"), "--destination", str(root / "one")],
                                       cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(ambiguous.returncode, 2)
            self.assertFalse((root / "other").exists())
            self.assertFalse((root / "one").exists())

    def test_removed_hosts_are_rejected_without_creating_installations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "unused-home"
            destination = root / "unused-destination"
            for agent in ("hermes", "unknown-host"):
                with self.subTest(agent=agent):
                    for operation in (curation.install_skill, curation.doctor):
                        with self.assertRaisesRegex(ValueError, "unknown agent"):
                            operation(agent=agent, home=home, destination=destination)
                    for command in ("install", "doctor"):
                        result = subprocess.run(
                            [sys.executable, str(MODULE), command, "--agent", agent,
                             "--home", str(home), "--destination", str(destination)],
                            cwd=root, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 2)
                        self.assertIn("invalid choice", result.stderr)
                    self.assertFalse(home.exists())
                    self.assertFalse(destination.exists())

    def test_source_overlap_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for target in (source, source / "nested"):
                with self.assertRaises(ValueError):
                    curation.install_skill(target, source=source)
            link = source / "linked-file"
            try:
                link.symlink_to(source / "LICENSE")
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ValueError):
                curation.install_skill(root / "installed", source=source)
            self.assertFalse((root / "installed").exists())
            link.unlink()
            target_link = root / "linked-destination"
            target_link.symlink_to(root / "missing")
            with self.assertRaises(ValueError):
                curation.install_skill(target_link, source=source)

    def test_table_demo_displays_actual_seeded_priorities(self):
        result = subprocess.run(
            [sys.executable, str(MODULE), "demo", "--format", "table", "--seed", "42"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: surprise", result.stdout)
        self.assertIn("Seed: 42", result.stdout)
        self.assertIn("26.9%", result.stdout)
        self.assertIn("25.0%", result.stdout)
        self.assertIn("Learned baseline: unchanged", result.stdout)
        self.assertIn("familiar 75%, adjacent 25%, distant 0%", result.stdout)

    def test_demo_json_remains_the_default(self):
        result = subprocess.run(
            [sys.executable, str(MODULE), "demo", "--seed", "42"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["mode"], "surprise")


if __name__ == "__main__":
    unittest.main()
