"""Private curation roots stay ignored while public synthetic examples remain usable."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("git"), "Git is needed to exercise ignore behavior")
class GitignoreTests(unittest.TestCase):
    def test_private_models_are_ignored_at_any_depth_without_hiding_examples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copyfile(Path(__file__).resolve().parents[1] / ".gitignore", root / ".gitignore")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            private = {"model/profile.json", "model/feedback.jsonl", "nested/model/profile.json",
                       "nested/model/recommendations.jsonl", "deep/nested/model/batches.jsonl"}
            public = {"examples/profile.example.json", "examples/profile.demo.json",
                      "examples/graph.example.json", "skills/trurl/SKILL.md"}
            result = subprocess.run(
                ["git", "-c", "core.excludesFile=" + os.devnull, "-C", str(root),
                 "check-ignore", "--no-index", "--stdin"],
                input="\n".join(sorted(private | public)) + "\n",
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(result.stdout.splitlines()), private)


if __name__ == "__main__":
    unittest.main()
