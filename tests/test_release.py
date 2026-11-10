"""Exercise the public/private boundary with real exported archives."""
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


spec = importlib.util.spec_from_file_location("package_release", Path(__file__).resolve().parents[1] / "scripts" / "package_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def fixture(self, root):
        (root / "README.md").write_text("Public introduction")
        (root / "release-files.json").write_text(json.dumps({"files": ["README.md", "release-files.json"]}))
        (root / "model").mkdir()
        (root / "model" / "profile.json").write_text('{"private": "never publish"}')
        (root / ".env").write_text("SECRET=never-publish")

    def test_export_excludes_unlisted_private_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            result = release.package(root)
            with ZipFile(result["archive"]) as archive:
                self.assertEqual(set(archive.namelist()), {"trurl/README.md", "trurl/release-files.json"})
            self.assertFalse((Path(result["directory"]) / "model").exists())

    def test_manifest_cannot_include_private_model_or_escape(self):
        for name in ["model/profile.json", "nested/model/profile.json", ".env", "../README.md", "/tmp/private.json"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.fixture(root)
                (root / "release-files.json").write_text(json.dumps({"files": [name]}))
                with self.assertRaises(ValueError):
                    release.public_files(root)

    def test_symlink_cannot_smuggle_private_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "public.json").symlink_to(root / "model" / "profile.json")
            (root / "release-files.json").write_text(json.dumps({"files": ["public.json"]}))
            with self.assertRaises(ValueError):
                release.public_files(root)

    def test_existing_release_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            release.package(root)
            with self.assertRaises(FileExistsError):
                release.package(root)

    @unittest.skipUnless(shutil.which("git"), "Git is needed for the repository boundary check")
    def test_repository_check_rejects_forced_private_and_untracked_release_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "release-files.json"], check=True)
            with self.assertRaisesRegex(ValueError, "release files not tracked: README.md"):
                release.check_repository(root)
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            self.assertEqual(release.check_repository(root),
                             {"valid": True, "tracked_files": 2, "release_files": 2})
            subprocess.run(["git", "-C", str(root), "add", "-f", "model/profile.json"], check=True)
            with self.assertRaisesRegex(ValueError, "tracked files outside release manifest: model/profile.json"):
                release.check_repository(root)
            self.assertFalse((root / "dist").exists())

    def test_repository_manifest_includes_every_test_and_skill_resource(self):
        root = Path(__file__).resolve().parents[1]
        names = {name for name, _ in release.public_files(root)}
        required = {path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py")}
        required.update(path.relative_to(root).as_posix() for path in (root / "skills/trurl").rglob("*")
                        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
        self.assertFalse(required - names, "Source tests or installed resources missing from release: "
                         + ", ".join(sorted(required - names)))


if __name__ == "__main__":
    unittest.main()
