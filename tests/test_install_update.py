"""Updating an installed copy, and what doctor reports about it."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/trurl/scripts"
SOURCE = SCRIPTS.parent
CURATION = runpy.run_path(str(SCRIPTS / "curation.py"))


def tree(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


class Installed(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.target = self.base / "skills" / "trurl"
        self.backups = self.base / "backups"
        self.backups.mkdir()
        # Keep the previous-copy backups of these tests inside their own temporary folder.
        redirected = patch.object(tempfile, "tempdir", str(self.backups))
        redirected.start()
        self.addCleanup(redirected.stop)
        self.first = CURATION["install_skill"](self.target)

    def run_cli(self, *arguments):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"TRURL_ROOT", "CURATION_ROOT", "XDG_CONFIG_HOME", "CODEX_HOME"}}
        environment.update(HOME=str(self.home), TMPDIR=str(self.backups), PYTHONDONTWRITEBYTECODE="1")
        self.home.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(SCRIPTS / "curation.py"), *arguments], cwd=str(self.base),
                              capture_output=True, text=True, env=environment)


class UpdateTests(Installed):
    def test_plain_install_still_refuses_and_names_the_update_option(self):
        self.assertEqual(self.first["action"], "installed")
        before = tree(self.target)
        with self.assertRaisesRegex(FileExistsError, "installation already exists.*--update"):
            CURATION["install_skill"](self.target)
        self.assertEqual(tree(self.target), before)

    def test_update_leaves_a_current_copy_alone(self):
        before = {path: path.stat().st_mtime_ns for path in self.target.rglob("*")}
        result = CURATION["install_skill"](self.target, update=True)
        self.assertEqual((result["action"], result["installed"]), ("current", str(self.target)))
        self.assertNotIn("previous_copy", result)
        self.assertEqual({path: path.stat().st_mtime_ns for path in self.target.rglob("*")}, before)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_update_replaces_a_changed_copy_and_keeps_the_old_one_outside_the_skills_folder(self):
        (self.target / "references/feedback.md").write_text("an older or locally edited copy", encoding="utf-8")
        (self.target / "scripts/retired.py").write_text("print('removed upstream')", encoding="utf-8")
        (self.target / "scripts/__pycache__").mkdir()
        (self.target / "scripts/__pycache__/curation.cpython-313.pyc").write_bytes(b"cache")
        result = CURATION["install_skill"](self.target, update=True)
        self.assertEqual((result["action"], result["personal_model_copied"]), ("updated", False))
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["trurl"])
        self.assertFalse((self.target / "scripts/retired.py").exists())
        self.assertEqual(CURATION["_fingerprint"](self.target), CURATION["_fingerprint"](SOURCE))
        previous = Path(result["previous_copy"])
        self.assertEqual(self.backups, previous.parent.parent)
        self.assertEqual((previous / "references/feedback.md").read_text(encoding="utf-8"),
                         "an older or locally edited copy")
        self.assertTrue((previous / "scripts/retired.py").is_file())
        self.assertEqual(CURATION["install_skill"](self.target, update=True)["action"], "current")

    def test_update_installs_when_nothing_is_there_yet(self):
        fresh = self.base / "elsewhere" / "skills" / "trurl"
        result = CURATION["install_skill"](fresh, update=True)
        self.assertEqual(result["action"], "installed")
        self.assertTrue((fresh / "SKILL.md").is_file())

    def test_update_only_replaces_a_plain_trurl_skill_folder(self):
        foreign = self.base / "notes"
        foreign.mkdir()
        (foreign / "README.md").write_text("someone's notes", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not a Trurl skill"):
            CURATION["install_skill"](foreign, update=True)
        (self.target / "model").mkdir()
        (self.target / "model/profile.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "move private files out.*model/profile.json"):
            CURATION["install_skill"](self.target, update=True)
        (self.target / "model/profile.json").unlink()
        (self.target / "model").rmdir()
        (self.target / "linked.md").symlink_to(foreign / "README.md")
        with self.assertRaisesRegex(ValueError, "contains a symlink"):
            CURATION["install_skill"](self.target, update=True)
        self.assertEqual((foreign / "README.md").read_text(encoding="utf-8"), "someone's notes")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_failed_swap_puts_the_previous_copy_back(self):
        (self.target / "references/feedback.md").write_text("edited", encoding="utf-8")
        before = tree(self.target)
        with patch("os.replace", side_effect=OSError("synthetic failure")):
            with self.assertRaisesRegex(OSError, "synthetic failure"):
                CURATION["install_skill"](self.target, update=True)
        self.assertEqual(tree(self.target), before)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["trurl"])

    def test_command_line_update(self):
        installed = self.run_cli("install", "--agent", "claude-code")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        again = self.run_cli("install", "--agent", "claude-code")
        self.assertEqual(again.returncode, 2)
        self.assertIn("--update", again.stderr)
        copy = self.home / ".claude/skills/trurl"
        (copy / "SKILL.md").write_text((copy / "SKILL.md").read_text(encoding="utf-8") + "\nlocal note\n", encoding="utf-8")
        updated = self.run_cli("install", "--agent", "claude-code", "--update")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        report = json.loads(updated.stdout)
        self.assertEqual(report["action"], "updated")
        self.assertIn("local note", (Path(report["previous_copy"]) / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(tree(copy), tree(Path(self.first["installed"])))


class DoctorTests(Installed):
    def test_doctor_finds_the_model_location_itself_and_needs_no_model_before_first_use(self):
        self.run_cli("install", "--agent", "claude-code")
        checked = self.run_cli("doctor", "--agent", "claude-code")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        report = json.loads(checked.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual((report["root"]["path"], report["root"]["source"]), (str(self.home / "Trurl"), "default"))
        self.assertEqual((report["root"]["profile_present"], report["root"]["contents_read"]), (False, False))
        self.assertFalse((self.home / "Trurl").exists())
        self.assertEqual(self.run_cli("init").returncode, 0)
        report = json.loads(self.run_cli("doctor", "--agent", "claude-code").stdout)
        self.assertEqual((report["ok"], report["root"]["profile_present"]), (True, True))

    def test_an_explicit_root_must_hold_a_model_and_an_empty_value_means_unset(self):
        self.run_cli("install", "--agent", "claude-code")
        missing = self.run_cli("doctor", "--agent", "claude-code", "--root", str(self.base / "nowhere"))
        self.assertEqual(missing.returncode, 1)
        report = json.loads(missing.stdout)
        self.assertEqual((report["ok"], report["root"]["source"]), (False, "explicit"))
        unset = self.run_cli("doctor", "--agent", "claude-code", "--root", "")
        self.assertEqual(unset.returncode, 0, unset.stderr)
        self.assertEqual(json.loads(unset.stdout)["root"]["source"], "default")

    def test_doctor_reports_whether_a_copy_matches_this_source(self):
        environment = {"PATH": ""}
        host = CURATION["doctor"](agent="codex", destination=self.target, home=self.home, environ=environment)["hosts"][0]
        self.assertEqual(host["update"], {"compared_with": str(SOURCE), "current": True})
        self.assertEqual(host["bundle_sha256"], CURATION["_fingerprint"](SOURCE))
        (self.target / "references/feedback.md").write_text("older", encoding="utf-8")
        report = CURATION["doctor"](agent="codex", destination=self.target, home=self.home, environ=environment)
        self.assertIs(report["hosts"][0]["update"]["current"], False)
        self.assertTrue(report["ok"])  # an older copy still works; being behind is information
        itself = CURATION["doctor"](agent="codex", destination=SOURCE, home=self.home, environ=environment)
        self.assertIsNone(itself["hosts"][0]["update"]["current"])
        absent = CURATION["doctor"](agent="codex", destination=self.base / "absent", home=self.home, environ=environment)
        self.assertEqual((absent["hosts"][0]["bundle_sha256"], absent["hosts"][0]["update"]["current"]), (None, None))
        self.assertFalse(self.home.exists())

    def test_planner_explains_a_missing_model(self):
        missing = self.run_cli("weights", "--request", "surprise me")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("no taste model at " + str(self.home / "Trurl" / "model" / "profile.json"), missing.stderr)
        self.assertIn("init", missing.stderr)
        self.assertNotIn("Errno", missing.stderr)


if __name__ == "__main__":
    unittest.main()
