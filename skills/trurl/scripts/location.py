#!/usr/bin/env python3
"""Locate a persistent Trurl workspace and remember a selected existing model."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import tempfile


def _environment(environ, cwd, home):
    environment = dict(os.environ if environ is None else environ)
    directory = Path(cwd or Path.cwd()).resolve()
    user_home = Path(home or environment.get("HOME") or environment.get("USERPROFILE") or Path.home()).resolve()
    return environment, directory, user_home


def _expand(value, environment, user_home):
    raw = os.fspath(value)
    if not raw.strip():
        raise ValueError("workspace path must be nonempty")
    if raw == "~" or raw.startswith("~/"):
        raw = str(user_home) + raw[1:]
    raw = re.sub(r"\$(\w+)|\$\{([^}]+)\}",
                 lambda match: environment.get(match.group(1) or match.group(2), match.group(0)), raw)
    return Path(raw)


def _absolute(value, environment, directory, user_home):
    path = _expand(value, environment, user_home)
    return (path if path.is_absolute() else directory / path).resolve()


def _config_path(environment, user_home):
    configured = environment.get("XDG_CONFIG_HOME")
    base = Path(configured) if configured else user_home / ".config"
    if not base.is_absolute():
        base = user_home / ".config"
    return base / "trurl" / "config.json"


def _check_config_path(path):
    for directory in (path.parent.parent, path.parent):
        if directory.is_symlink():
            raise ValueError("Trurl configuration directory is a symlink: " + str(directory))
        if directory.exists() and not directory.is_dir():
            raise ValueError("Trurl configuration directory is occupied by a file: " + str(directory))
    if path.is_symlink():
        raise ValueError("Trurl configuration file is a symlink: " + str(path))
    if path.exists() and not path.is_file():
        raise ValueError("Trurl configuration path is not a regular file: " + str(path))


def _read_config(path):
    _check_config_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Trurl configuration must be a regular file")
        try:
            config = json.load(handle)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Trurl configuration is invalid: " + str(path)) from error
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config["schema_version"] != 1 or not isinstance(config.get("root"), str)
            or not config["root"].strip() or not Path(config["root"]).is_absolute()):
        raise ValueError("Trurl configuration needs schema_version 1 and an absolute root: " + str(path))
    return config


def _result(root, source):
    if root.exists() and not root.is_dir():
        raise ValueError("curation root is not a directory: " + str(root))
    profile = root / "model" / "profile.json"
    return {"root": str(root), "source": source, "profile_path": str(profile),
            "profile_exists": profile.is_file()}


def resolve_root(explicit=None, *, environ=None, cwd=None, home=None):
    """Resolve one root without creating files or searching unrelated folders."""
    environment, directory, user_home = _environment(environ, cwd, home)
    choices = (("explicit", explicit), ("TRURL_ROOT", environment.get("TRURL_ROOT")),
               ("CURATION_ROOT", environment.get("CURATION_ROOT")))
    for source, value in choices:
        if value is not None and (source == "explicit" or value):
            return _result(_absolute(value, environment, directory, user_home), source)
    if (directory / "model" / "profile.json").is_file():
        return _result(directory, "workspace")
    config = _read_config(_config_path(environment, user_home))
    if config is not None:
        return _result(Path(config["root"]).resolve(), "registered")
    return _result(user_home / "Trurl", "default")


def remember_root(root, *, environ=None, cwd=None, home=None):
    """Remember an existing valid model without changing its contents."""
    environment, directory, user_home = _environment(environ, cwd, home)
    selected = resolve_root(root, environ=environment, cwd=directory, home=user_home)
    profile = Path(selected["profile_path"])
    if profile.parent.is_symlink() or profile.is_symlink():
        raise ValueError("the model folder and profile must not be symlinks")
    if not selected["profile_exists"]:
        raise ValueError("cannot remember a workspace without model/profile.json: " + selected["root"])
    with profile.open(encoding="utf-8") as handle:
        try:
            value = json.load(handle)
        except (ValueError, UnicodeError) as error:
            raise ValueError("profile.json is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("profile.json must contain a JSON object")
    config_path = _config_path(environment, user_home)
    previous = _read_config(config_path)
    updated = dict(previous or {}, schema_version=1, root=selected["root"])
    if updated == previous:
        return dict(selected, source="registered", config_path=str(config_path), status="unchanged")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _check_config_path(config_path)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=config_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _read_config(config_path) != previous:
            raise ValueError("Trurl configuration changed during save; retry with the current selection")
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return dict(selected, source="registered", config_path=str(config_path), status="saved")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("root", help="show the selected workspace without creating files")
    discovery.add_argument("--root", help="explicit root for this lookup")
    registration = commands.add_parser("use", help="remember an existing model for future local sessions")
    registration.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        result = remember_root(args.root) if args.command == "use" else resolve_root(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        parser.exit(2, "trurl location: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
