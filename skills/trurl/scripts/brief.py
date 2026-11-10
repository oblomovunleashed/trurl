#!/usr/bin/env python3
"""Validate and cache an agent-authored, evidence-bound curator's brief.

This stdlib-only helper does not summarize evidence or decide what it means.
Hashes establish byte freshness; the author remains responsible for source
permissions, faithful interpretation, uncertainty and preference scope.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile


SCHEMA_VERSION = 1
BRIEF_PATH = "model/curators-brief.json"
MANDATORY_SOURCES = ("model/profile.json", "model/feedback.jsonl")
MAX_WORDS = 350
MAX_DOCUMENT_BYTES = 131072
HASH = re.compile(r"^[0-9a-f]{64}$")
INVALIDATION_REASONS = ("manual", "source_corrected", "source_forgotten")


class BriefError(ValueError):
    """An unusable draft, cache or source; safe for concise CLI reporting."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BriefError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _nonfinite(value):
    raise BriefError("non-finite JSON value: " + value)


def _json(data, label):
    try:
        return json.loads(data, object_pairs_hook=_object,
                          parse_constant=_nonfinite)
    except (ValueError, UnicodeError) as error:
        raise BriefError("invalid JSON in {}: {}".format(label, error)) from error


def _root(root):
    result = Path(root).expanduser().resolve()
    if not result.is_dir():
        raise BriefError("curation root is not a directory")
    return result


def _path(root, relative):
    if (not isinstance(relative, str) or "\\" in relative
            or "\x00" in relative or not relative.startswith("model/")):
        raise BriefError("source path must be a normalized relative model/ path")
    parts = PurePosixPath(relative).parts
    if (any(part in ("", ".", "..") for part in parts)
            or str(PurePosixPath(relative)) != relative):
        raise BriefError("source path must be a normalized relative model/ path")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BriefError("symlinks are not allowed in private source/cache paths: " + relative)
    return current


def _read(root, relative):
    """Read a regular file without following a final symlink, or return None."""
    path = _path(root, relative)
    try:
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise BriefError("cannot read {}: {}".format(relative, error.strerror)) from error
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise BriefError("source/cache must be a regular file: " + relative)
        data = handle.read()
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise BriefError("source changed while being read: " + relative)
    return data


def _digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _parse_source(data, relative):
    if data is None:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise BriefError("source is not UTF-8: " + relative) from error
    if relative.endswith(".json"):
        value = _json(text, relative)
        if isinstance(value, dict) and {"summary", "sources", "source_refs"}.issubset(value):
            raise BriefError("derived briefs cannot be evidence sources: " + relative)
        if relative == "model/profile.json" and not isinstance(value, dict):
            raise BriefError("profile must be a JSON object")
        return value
    if relative.endswith(".jsonl"):
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip() and not isinstance(_json(line, relative + ":" + str(number)), dict):
                raise BriefError("JSONL source records must be objects: " + relative)
    return text


def _sources(root, paths, allow_missing=False):
    result = []
    content = {}
    for relative in sorted(set(paths)):
        if _derived_path(relative):
            raise BriefError("a brief cannot be its own source")
        data = _read(root, relative)
        if data is None and relative != "model/feedback.jsonl" and not allow_missing:
            raise BriefError("missing source: " + relative)
        _parse_source(data, relative)
        result.append({"path": relative, "sha256": _digest(data)})
        content[relative] = data
    return result, content


def _derived_path(relative):
    return (PurePosixPath(relative).name.lstrip(".").startswith(("curators-brief", "curator-brief"))
            or relative.startswith("model/.curators-brief"))


def snapshot(root, extra_sources=()):
    """Capture exact sources BEFORE composing a draft, including absent feedback."""
    root = _root(root)
    paths = list(MANDATORY_SOURCES) + list(extra_sources)
    sources, unused = _sources(root, paths)
    base = _digest(_read(root, BRIEF_PATH))
    again, unused = _sources(root, paths)
    if again != sources or base != _digest(_read(root, BRIEF_PATH)):
        raise BriefError("state changed during snapshot; retry")
    return {"schema_version": SCHEMA_VERSION, "base_brief_sha256": base, "sources": sources}


def _source_records(value):
    if not isinstance(value, list) or not value or len(value) > 128:
        raise BriefError("sources must be a nonempty list of at most 128 records")
    paths = []
    for source in value:
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            raise BriefError("each source needs only path and sha256")
        path, digest = source["path"], source["sha256"]
        if not isinstance(path, str):
            raise BriefError("source path must be text")
        # Validate paths even when no source read is needed (e.g. a stale cache).
        if _derived_path(path):
            raise BriefError("a brief cannot be its own source")
        if digest is None:
            if path != "model/feedback.jsonl":
                raise BriefError("only an absent feedback ledger may have a null sha256")
        elif not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise BriefError("source sha256 must be a lowercase SHA-256 digest")
        paths.append(path)
    if len(paths) != len(set(paths)) or not set(MANDATORY_SOURCES).issubset(paths):
        raise BriefError("sources need unique paths and both mandatory profile/feedback records")
    return paths


def _strings(value, label):
    if not isinstance(value, list) or len(value) > 64 or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise BriefError(label + " must be a list of nonempty strings")


def _document(value, saved=False):
    required = {"schema_version", "base_brief_sha256", "sources", "summary", "source_refs", "limits"}
    if saved:
        required |= {"version", "created_at", "previous_sha256", "profile_interest_ids"}
    if not isinstance(value, dict) or set(value) != required:
        raise BriefError("brief fields must be exactly: " + ", ".join(sorted(required)))
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise BriefError("unsupported brief schema_version")
    base = value["base_brief_sha256"]
    if base is not None and (not isinstance(base, str) or not HASH.fullmatch(base)):
        raise BriefError("base_brief_sha256 must be null or a SHA-256 digest from snapshot")
    summary = value["summary"]
    if not isinstance(summary, str) or not 1 <= len(summary.split()) <= MAX_WORDS:
        raise BriefError("summary must contain 1–350 whitespace-separated words")
    paths = _source_records(value["sources"])
    _strings(value["limits"], "limits")
    refs = value["source_refs"]
    if not isinstance(refs, list) or len(refs) > 256:
        raise BriefError("source_refs must be a list of at most 256 references")
    for ref in refs:
        if (not isinstance(ref, dict) or not {"path", "locator"}.issubset(ref)
                or not set(ref).issubset({"path", "locator", "note"})
                or not isinstance(ref["path"], str) or ref["path"] not in paths
                or not isinstance(ref["locator"], str) or not ref["locator"]
                or ("note" in ref and (not isinstance(ref["note"], str) or not ref["note"].strip()))):
            raise BriefError("each source reference needs a captured path and locator; note is optional")
    if saved:
        if type(value["version"]) is not int or value["version"] < 1:
            raise BriefError("saved brief version must be a positive integer")
        if value["previous_sha256"] != base:
            raise BriefError("previous_sha256 must match base_brief_sha256")
        ids = value["profile_interest_ids"]
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
            raise BriefError("profile_interest_ids must be unique nonempty IDs")
        _timestamp(value["created_at"])
    return paths


def _timestamp(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("missing timezone")
    except (ValueError, TypeError, AttributeError) as error:
        raise BriefError("created_at must be an ISO timestamp with timezone") from error


def _refs(value, content):
    covered = {ref["path"] for ref in value["source_refs"]}
    nonempty = {path for path, data in content.items() if data is not None and data.strip()}
    if not nonempty.issubset(covered):
        raise BriefError("source_refs must cover every nonempty captured source")
    for ref in value["source_refs"]:
        path, locator = ref["path"], ref["locator"]
        data = content[path]
        if data is None:
            if locator != "missing":
                raise BriefError("absent source requires locator 'missing': " + path)
            continue
        if not data.strip():
            if locator != "empty":
                raise BriefError("empty source requires locator 'empty': " + path)
            continue
        if path.endswith(".json"):
            target = _parse_source(data, path)
            if locator == "#":
                continue
            if not locator.startswith("#/"):
                raise BriefError("JSON reference requires a JSON Pointer '#/…': " + path)
            try:
                for token in locator[2:].split("/"):
                    if re.search(r"~(?![01])", token):
                        raise ValueError("invalid pointer escape")
                    token = token.replace("~1", "/").replace("~0", "~")
                    if isinstance(target, list):
                        if not re.fullmatch(r"0|[1-9][0-9]*", token):
                            raise ValueError("invalid array index")
                        target = target[int(token)]
                    elif isinstance(target, dict):
                        target = target[token]
                    else:
                        raise ValueError("pointer traverses a scalar")
            except (KeyError, IndexError, ValueError) as error:
                raise BriefError("source reference does not exist: {} {}".format(path, locator)) from error
        else:
            match = re.fullmatch(r"line:([1-9][0-9]*)", locator)
            lines = data.decode("utf-8").splitlines()
            if not match or int(match.group(1)) > len(lines) or not lines[int(match.group(1)) - 1].strip():
                raise BriefError("source reference requires an existing nonblank 'line:N': " + path)


def _load_cache(root):
    data = _read(root, BRIEF_PATH)
    if data is None:
        return None, None
    if len(data) > MAX_DOCUMENT_BYTES:
        raise BriefError("brief exceeds maximum JSON document size")
    return data, _json(data, BRIEF_PATH)


def _interest_ids(content):
    profile = _parse_source(content["model/profile.json"], "model/profile.json")
    interests = profile.get("interests", [])
    if not isinstance(interests, list):
        raise BriefError("profile interests must be a list when present")
    return sorted({item["id"] for item in interests
                   if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]})


def check(root):
    """Return fresh/missing/stale/invalid; callers must not use unusable prose."""
    try:
        root = _root(root)
        data, brief = _load_cache(root)
        if data is None:
            return {"status": "missing", "reasons": ["no cached curator's brief"]}
        if isinstance(brief, dict) and brief.get("invalidated") is True:
            _tombstone(brief)
            return {"status": "stale", "version": brief["version"], "reasons": ["brief explicitly invalidated"]}
        paths = _document(brief, saved=True)
        sources, content = _sources(root, paths, allow_missing=True)
        expected = {item["path"]: item["sha256"] for item in brief["sources"]}
        reasons = ["source changed or removed: " + item["path"] for item in sources
                   if item["sha256"] != expected[item["path"]]]
        if reasons:
            return {"status": "stale", "version": brief["version"], "reasons": reasons}
        _refs(brief, content)
        if brief["profile_interest_ids"] != _interest_ids(content):
            raise BriefError("saved profile_interest_ids do not match the source profile")
        return {"status": "fresh", "version": brief["version"], "reasons": [], "brief": brief}
    except (BriefError, OSError) as error:
        return {"status": "invalid", "reasons": [str(error)]}


@contextmanager
def _lock(root):
    path = _path(root, "model/.curators-brief.lock")
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise BriefError("another brief writer holds model/.curators-brief.lock; retry when it finishes") from error
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def _atomic(root, value):
    destination = _path(root, BRIEF_PATH)
    serialized = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise BriefError("brief exceeds maximum JSON document size")
    descriptor, temporary = tempfile.mkstemp(prefix=".curators-brief-", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(destination))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _tombstone(value):
    if (set(value) != {"schema_version", "version", "invalidated", "reason", "created_at", "previous_sha256"}
            or type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION
            or type(value["version"]) is not int or value["version"] < 1
            or value["invalidated"] is not True or value["reason"] not in INVALIDATION_REASONS
            or not isinstance(value["previous_sha256"], str) or not HASH.fullmatch(value["previous_sha256"])):
        raise BriefError("invalid brief invalidation record")
    _timestamp(value["created_at"])


def _version(data):
    if data is None:
        return 1
    try:
        value = _json(data, BRIEF_PATH)
        if isinstance(value, dict) and value.get("invalidated") is True:
            _tombstone(value)
        else:
            _document(value, saved=True)
        return value["version"] + 1
    except BriefError:
        # A corrupt cache is replaceable after its exact bytes were snapshotted.
        return 1


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save(root, draft):
    """Validate a reviewed draft and atomically replace the cache, never raw state."""
    root = _root(root)
    paths = _document(draft)
    for path in paths:
        _path(root, path)
    if len(json.dumps(draft, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise BriefError("draft exceeds maximum JSON document size")
    with _lock(root):
        previous = _read(root, BRIEF_PATH)
        if draft["base_brief_sha256"] != _digest(previous):
            raise BriefError("brief changed since snapshot; reread evidence and draft again")
        sources, content = _sources(root, paths)
        if sources != sorted(draft["sources"], key=lambda item: item["path"]):
            raise BriefError("sources changed since snapshot; reread evidence and draft again")
        _refs(draft, content)
        result = dict(draft, version=_version(previous), created_at=_now(), previous_sha256=_digest(previous),
                      profile_interest_ids=_interest_ids(content))
        result["sources"] = sources
        # Catch concurrent source edits and writers that do not honor our lock.
        current, unused = _sources(root, paths)
        if current != sources or _digest(_read(root, BRIEF_PATH)) != _digest(previous):
            raise BriefError("state changed during save; reread evidence and draft again")
        _atomic(root, result)
    return {"status": "saved", "path": BRIEF_PATH, "version": result["version"], "brief": result}


def invalidate(root, reason="manual"):
    """Discard derived prose after correct/forget; keep only content-free metadata."""
    root = _root(root)
    if reason not in INVALIDATION_REASONS:
        raise BriefError("unsupported invalidation reason")
    with _lock(root):
        previous = _read(root, BRIEF_PATH)
        if previous is None:
            return {"status": "missing", "reasons": ["no cached curator's brief"]}
        result = {"schema_version": SCHEMA_VERSION, "version": _version(previous),
                  "invalidated": True, "reason": reason,
                  "created_at": _now(), "previous_sha256": _digest(previous)}
        _atomic(root, result)
    return {"status": "invalidated", "path": BRIEF_PATH, "version": result["version"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "check", "save", "invalidate"):
        child = commands.add_parser(command)
        child.add_argument("--root", required=True, help="private curation root")
        if command == "snapshot":
            child.add_argument("--source", action="append", default=[], help="explicit additional model/ source")
        if command == "save":
            child.add_argument("--draft", required=True, help="agent-authored draft JSON file")
        if command == "invalidate":
            child.add_argument("--reason", choices=INVALIDATION_REASONS, default="manual")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot(args.root, args.source)
        elif args.command == "save":
            data = Path(args.draft).read_bytes()
            if len(data) > MAX_DOCUMENT_BYTES:
                raise BriefError("draft exceeds maximum JSON document size")
            result = save(args.root, _json(data, "draft"))
        elif args.command == "invalidate":
            result = invalidate(args.root, args.reason)
        else:
            result = check(args.root)
    except (BriefError, OSError) as error:
        result = {"status": "invalid", "reasons": [str(error)]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if (args.command != "check" and result.get("status") != "invalid") or result.get("status") == "fresh" else 1


if __name__ == "__main__":
    sys.exit(main())
