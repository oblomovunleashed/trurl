#!/usr/bin/env python3
"""Export the explicit public-file manifest; never include personal model state."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def public_files(root):
    """Validate the release manifest before touching the destination."""
    root = Path(root).resolve()
    manifest = json.loads((root / "release-files.json").read_text(encoding="utf-8"))
    names = manifest["files"]
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ValueError("Release manifest needs a nonempty list of paths")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate release path")
    result = []
    for name in sorted(names):
        rel = PurePosixPath(name)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or "\\" in name:
            raise ValueError("Invalid release path: " + name)
        if any(part in {"model", ".git", "__pycache__"} or part.startswith(".env") for part in rel.parts):
            raise ValueError("Private/generated path in release manifest: " + name)
        path = root.joinpath(*rel.parts)
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            raise ValueError("Symlink in release path: " + name)
        if not path.is_file() or root not in path.resolve().parents:
            raise ValueError("Missing public file: " + name)
        result.append((name, path))
    return result


def package(root, destination=None):
    root = Path(root).resolve()
    files = public_files(root)
    destination = Path(destination or root / "dist").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    final_zip = destination / "trurl.zip"
    final_tree = destination / "trurl"
    if final_tree.exists():
        raise FileExistsError("Release directory already exists; choose a fresh --output directory")
    with tempfile.TemporaryDirectory(prefix=".curation-release-", dir=destination) as temp:
        staging = Path(temp) / "trurl"
        staging.mkdir()
        for name, source in files:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        temp_zip = Path(temp) / "trurl.zip"
        with ZipFile(temp_zip, "w", compression=ZIP_DEFLATED) as archive:
            for name, _ in files:
                info = ZipInfo("trurl/" + name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, (staging / name).read_bytes())
        staging.replace(final_tree)
        temp_zip.replace(final_zip)
    return {"directory": str(final_tree), "archive": str(final_zip), "files": len(files)}


def check_repository(root):
    """Require Git's published tree to match the reviewed release allowlist."""
    root = Path(root).resolve()
    expected = {name for name, _ in public_files(root)}
    try:
        top = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True, stderr=subprocess.PIPE).strip()
        if Path(top).resolve() != root:
            raise ValueError("Run the repository check at its Git root")
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        raise ValueError("Repository check requires a Git checkout") from error
    tracked = set(output.decode("utf-8").rstrip("\0").split("\0")) - {""}
    unexpected, missing = sorted(tracked - expected), sorted(expected - tracked)
    if unexpected or missing:
        problems = []
        if unexpected:
            problems.append("tracked files outside release manifest: " + ", ".join(unexpected))
        if missing:
            problems.append("release files not tracked: " + ", ".join(missing))
        raise ValueError("; ".join(problems))
    return {"valid": True, "tracked_files": len(tracked), "release_files": len(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Check Git tracked files against the manifest without writing an archive")
    args = parser.parse_args()
    try:
        result = check_repository(args.root) if args.check else package(args.root, args.output)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, "Release not created: " + str(error) + "\n")


if __name__ == "__main__":
    main()

