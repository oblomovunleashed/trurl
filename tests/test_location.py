"""Persistent root discovery with isolated homes and synthetic model files."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/location.py"
SPEC = importlib.util.spec_from_file_location("trurl_location", SCRIPT)
location = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(location)


class LocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home"
        self.cwd = self.base / "work"
        self.home.mkdir()
        self.cwd.mkdir()
        self.config = self.home / ".config/trurl/config.json"

    def resolve(self, explicit=None, **overrides):
        options = {"environ": {}, "cwd": self.cwd, "home": self.home}
        options.update(overrides)
        return location.resolve_root(explicit, **options)

    def remember(self, root, **overrides):
        options = {"environ": {}, "cwd": self.cwd, "home": self.home}
        options.update(overrides)
        return location.remember_root(root, **options)

    def model(self, name="private", data=None):
        root = self.base / name
        model = root / "model"
        model.mkdir(parents=True)
        (model / "profile.json").write_text(json.dumps(data if data is not None else {"name": "Synthetic reader"}))
        (model / "feedback.jsonl").write_text('{"id":"synthetic-event"}\n')
        return root

    def config_value(self, value):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(json.dumps(value))

    def test_default_is_persistent_and_discovery_does_not_create_any_files(self):
        before = sorted(str(item.relative_to(self.base)) for item in self.base.rglob("*"))
        result = self.resolve()
        self.assertEqual(result, {"root": str(self.home / "Trurl"), "source": "default",
                                  "profile_path": str(self.home / "Trurl/model/profile.json"),
                                  "profile_exists": False})
        self.assertEqual(sorted(str(item.relative_to(self.base)) for item in self.base.rglob("*")), before)

    def test_explicit_environment_and_workspace_precedence(self):
        workspace = self.model("work")
        registered = self.model("registered")
        self.remember(registered)
        environment = {"TRURL_ROOT": str(self.base / "environment"), "CURATION_ROOT": str(self.base / "legacy")}
        self.assertEqual(self.resolve(environ=environment)["source"], "TRURL_ROOT")
        self.assertEqual(self.resolve(environ={"CURATION_ROOT": environment["CURATION_ROOT"]})["source"], "CURATION_ROOT")
        self.assertEqual(self.resolve(self.base / "explicit", environ=environment)["source"], "explicit")
        self.assertEqual(self.resolve()["root"], str(workspace))
        self.assertEqual(self.resolve()["source"], "workspace")

    def test_expansion_uses_the_supplied_home_environment_and_working_directory(self):
        self.assertEqual(self.resolve("~/Taste Folder")["root"], str(self.home / "Taste Folder"))
        self.assertEqual(self.resolve("relative root")["root"], str(self.cwd / "relative root"))
        self.assertEqual(self.resolve("${TASTE_BASE}/profile", environ={"TASTE_BASE": str(self.base)})["root"], str(self.base / "profile"))
        with self.assertRaises(ValueError):
            self.resolve("")

    def test_registered_model_is_reused_from_different_directories_and_preserved(self):
        root = self.model()
        before = {item.name: item.read_bytes() for item in (root / "model").iterdir()}
        self.assertEqual(self.remember(root)["status"], "saved")
        second_cwd = self.base / "other-project"
        second_cwd.mkdir()
        self.assertEqual(self.resolve()["root"], str(root))
        self.assertEqual(self.resolve(cwd=second_cwd)["root"], str(root))
        self.assertEqual(self.resolve()["source"], "registered")
        self.assertTrue(self.resolve()["profile_exists"])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        config_before = self.config.read_bytes()
        self.assertEqual(self.remember(root)["status"], "unchanged")
        self.assertEqual(self.config.read_bytes(), config_before)
        self.assertEqual({item.name: item.read_bytes() for item in (root / "model").iterdir()}, before)

    def test_missing_registered_target_remains_selected(self):
        missing = self.base / "old-location"
        self.config_value({"schema_version": 1, "root": str(missing)})
        result = self.resolve()
        self.assertEqual(result["source"], "registered")
        self.assertEqual(result["root"], str(missing))
        self.assertFalse(result["profile_exists"])
        self.assertFalse(missing.exists())

    def test_malformed_registry_fails_but_explicit_env_and_workspace_bypass_it(self):
        self.config_value({"schema_version": 1, "root": "relative"})
        with self.assertRaises(ValueError):
            self.resolve()
        self.assertEqual(self.resolve(self.base / "chosen")["source"], "explicit")
        self.assertEqual(self.resolve(environ={"TRURL_ROOT": str(self.base / "chosen")})["source"], "TRURL_ROOT")
        self.model("work")
        self.assertEqual(self.resolve()["source"], "workspace")
        with self.assertRaises(ValueError):
            self.remember(self.cwd)
        self.config.write_text("{")
        with self.assertRaises(ValueError):
            self.resolve(cwd=self.base)

    def test_absolute_xdg_configuration_is_shared_and_relative_xdg_is_ignored(self):
        root = self.model()
        environment = {"XDG_CONFIG_HOME": str(self.base / "settings")}
        result = self.remember(root, environ=environment)
        self.assertEqual(result["config_path"], str(self.base / "settings/trurl/config.json"))
        self.assertEqual(self.resolve(environ=environment)["root"], str(root))
        self.assertFalse(self.config.exists())
        self.assertEqual(self.resolve(environ={"XDG_CONFIG_HOME": "relative-settings"})["source"], "default")

    def test_registration_requires_a_real_object_profile_and_preserves_bad_config(self):
        with self.assertRaises(ValueError):
            self.remember(self.base / "missing")
        root = self.model(data=[])
        with self.assertRaises(ValueError):
            self.remember(root)
        (root / "model/profile.json").write_text("{}")
        self.config_value({"schema_version": 9, "root": str(root)})
        before = self.config.read_bytes()
        with self.assertRaises(ValueError):
            self.remember(root)
        self.assertEqual(self.config.read_bytes(), before)

    def test_registry_collisions_and_symlinks_are_not_overwritten(self):
        root = self.model()
        self.config.parent.mkdir(parents=True)
        target = self.base / "unrelated.json"
        target.write_text('{"keep":true}')
        self.config.symlink_to(target)
        with self.assertRaises(ValueError):
            self.remember(root)
        self.assertEqual(target.read_text(), '{"keep":true}')
        self.config.unlink()
        self.config.mkdir()
        with self.assertRaises(ValueError):
            self.resolve()
        self.config.rmdir()
        self.config.parent.rmdir()
        self.config.parent.write_text("occupied")
        with self.assertRaises(ValueError):
            self.remember(root)
        self.assertEqual(self.config.parent.read_text(), "occupied")

    def test_failed_atomic_write_preserves_registry_and_cleans_temporary_file(self):
        first, second = self.model("first"), self.model("second")
        self.remember(first)
        before = self.config.read_bytes()
        with patch.object(location.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.remember(second)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual([item.name for item in self.config.parent.iterdir()], ["config.json"])

    def test_command_line_remembers_root_for_a_new_session(self):
        root = self.model()
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"HOME", "USERPROFILE", "TRURL_ROOT", "CURATION_ROOT", "XDG_CONFIG_HOME"}}
        environment["HOME"] = str(self.home)
        registered = subprocess.run([sys.executable, str(SCRIPT), "use", "--root", str(root)],
                                    cwd=self.cwd, env=environment, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(registered.stdout)["status"], "saved")
        discovered = subprocess.run([sys.executable, str(SCRIPT), "root"], cwd=self.base,
                                    env=environment, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(discovered.stdout)["root"], str(root))

    def test_installed_skill_initializes_and_reuses_the_same_model_across_sessions(self):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"HOME", "USERPROFILE", "TRURL_ROOT", "CURATION_ROOT", "XDG_CONFIG_HOME"}}
        environment["HOME"] = str(self.home)
        entrypoint = SCRIPT.with_name("curation.py")
        installed = subprocess.run(
            [sys.executable, str(entrypoint), "install", "--agent", "claude-code", "--home", str(self.home)],
            cwd=self.cwd, env=environment, capture_output=True, text=True, check=True,
        )
        runtime = Path(json.loads(installed.stdout)["installed"]) / "scripts/curation.py"
        second_cwd = self.base / "other-project"
        second_cwd.mkdir()

        def run(*arguments, cwd=self.cwd, check=True):
            return subprocess.run([sys.executable, str(runtime), *arguments], cwd=cwd,
                                  env=environment, capture_output=True, text=True, check=check)

        initial = json.loads(run("root").stdout)
        self.assertEqual(initial["root"], str(self.home / "Trurl"))
        self.assertFalse(initial["profile_exists"])
        initialized = json.loads(run("init").stdout)
        self.assertEqual(initialized["initialized"], str(self.home / "Trurl/model"))
        self.assertFalse((self.cwd / "model").exists())
        self.assertFalse(self.config.exists())
        self.assertTrue(json.loads(run("root", cwd=second_cwd).stdout)["profile_exists"])
        run("weights", "--fixed", "--seed", "42", cwd=second_cwd)

        custom = self.base / "Shared taste"
        run("init", "--root", str(custom))
        profile_path = custom / "model/profile.json"
        profile = json.loads(profile_path.read_text())
        profile["taste"]["axes_weights"] = {axis: float(axis == "depth") for axis in profile["taste"]["axes_weights"]}
        profile_path.write_text(json.dumps(profile))
        run("use", "--root", str(custom))
        for directory in (self.cwd, second_cwd):
            self.assertEqual(json.loads(run("root", cwd=directory).stdout)["root"], str(custom))
            plan = json.loads(run("weights", "--fixed", "--seed", "42", cwd=directory).stdout)
            self.assertEqual(plan["baseline_weights"], profile["taste"]["axes_weights"])

        saved_config = self.config.read_bytes()
        run("weights", "--root", str(self.home / "Trurl"), "--fixed")
        self.assertEqual(self.config.read_bytes(), saved_config)
        custom.rename(self.base / "Saved copy")
        failed = run("init", cwd=second_cwd, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(custom.exists())
        self.assertEqual(self.config.read_bytes(), saved_config)


if __name__ == "__main__":
    unittest.main()
