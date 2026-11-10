#!/usr/bin/env python3
"""Start a request, record a delivery and record feedback in one call each.

These helpers chain the existing root, context, planning, hypothesis and
discovery helpers and append to the private ledgers. They keep every existing
gate, author no preferences and verify no recommendations.
"""
import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
import tempfile


SCRIPTS = Path(__file__).resolve().parent
IO = runpy.run_path(str(SCRIPTS / "brief.py"))
RECOMMENDATIONS = "model/recommendations.jsonl"
FEEDBACK = "model/feedback.jsonl"
BATCHES = "model/batches.jsonl"
MODES = ("auto", "personal", "surprise", "deep", "playful", "perspective", "open", "wildcard")
PROTOCOLS = ("direct", "list_five", "vs_style", "varied_briefs")
IDENTITY_FIELDS = ("id", "title", "creator", "canonical_url", "medium", "lane")
# Delivered-item fields from the state contract, copied only when the selected item has them.
OPTIONAL_FIELDS = ("topics", "description", "detail", "rationale", "relation_to_profile", "personal_connection",
                   "graph_path", "selection_channel", "personal_fit_status", "value_rationale", "hypothesis_id",
                   "scores", "scoring_basis", "release_date", "duration_minutes", "verification", "source_family",
                   "discovery_domain", "random_seed")
POOL_FIELDS = ("canonical_url", "title", "creator", "medium", "lane", "verification", "source_provenance")
FEEDBACK_KINDS = ("curiosity", "first_impression", "experienced_enjoyment", "familiarity", "temporary_request")
# A delivery, a suggestion or an assistant's own view is never the person's reaction.
NOT_FEEDBACK = {"delivered", "suggested", "recommended", "exposure", "reference_only", "illustrative", "example",
                "quoted", "third_party", "quoted_third_party", "third_party_quote", "assistant_only",
                "assistant_suggestion", "assistant_characterization", "assistant_generated"}
CHANGE_FIELDS = {"path", "before", "after", "reason", "source_provenance"}


class WorkflowError(ValueError):
    """A step that cannot proceed; safe for concise CLI reporting."""


def _helper(name):
    return runpy.run_path(str(SCRIPTS / (name + ".py")))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _call(name, argv):
    """Run a sibling CLI in-process and return its JSON, keeping its own gates and messages."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = _helper(name)["main"](argv)
    except SystemExit as stop:
        code = stop.code
    if code not in (0, None):
        raise WorkflowError(err.getvalue().strip() or name + " failed")
    return json.loads(out.getvalue())


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path, label, jsonl=False):
    try:
        path = Path(path).expanduser()
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise WorkflowError("cannot read {}: {}".format(label, error.strerror or error)) from error
    if jsonl and path.suffix == ".jsonl":
        return [IO["_json"](line, label + ":" + str(number))
                for number, line in enumerate(raw.splitlines(), 1) if line.strip()]
    return IO["_json"](raw, label)


def _resolve(root):
    return _helper("location")["resolve_root"](root or None)


def _ledger(root, relative):
    """Return a ledger's bytes and parsed records; a missing ledger is empty."""
    data = IO["_read"](root, relative)
    records = [IO["_json"](line, relative + ":" + str(number))
               for number, line in enumerate((data or b"").decode("utf-8").splitlines(), 1) if line.strip()]
    if any(not isinstance(item, dict) for item in records):
        raise WorkflowError("ledger records must be objects: " + relative)
    return data, records


@contextmanager
def _lock(root):
    """Share the profile writers' lock: hypothesis saves snapshot these ledgers."""
    path = IO["_path"](root, "model/.profile.lock")
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise WorkflowError("another profile writer holds model/.profile.lock; retry when it finishes") from error
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def _append(root, relative, current, records):
    """Add whole records atomically; never leave a partial line in an append-only ledger."""
    destination = IO["_path"](root, relative)
    existing = current or b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    added = "".join(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n" for item in records)
    descriptor, staged = tempfile.mkstemp(prefix=".ledger-", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(existing + added.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if IO["_read"](root, relative) != current:
            raise WorkflowError(relative + " changed during save; retry")
        os.replace(staged, str(destination))
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def start(root=None, request="", context="on_demand", mode="auto", scope="auto", seed=None, fixed=False,
          repeat_count=0, count=5, discovery_seed=None, out=None):
    """Resolve the model, prepare context, make the one retained plan and, when nothing is due, the research briefs."""
    location = _resolve(root)
    result = {"schema_version": 1, "command": "start", "status": "no_model",
              "root": location["root"], "root_source": location["source"]}
    if not location["profile_exists"]:
        result["next"] = (["Restore access to the remembered model at " + location["profile_path"]
                           + " before creating another."] if location["source"] == "registered" else
                          ["Read references/onboarding.md, then create the model: curation.py init --root "
                           + location["root"]])
        return result
    root_path = IO["_root"](location["root"])
    result["root"] = str(root_path)

    def current_profile():
        return IO["_parse_source"](IO["_read"](root_path, "model/profile.json"), "model/profile.json")

    # A disabled scheduled run stops here, before context preparation can
    # reconcile hypotheses or anything else writes to the model.
    delivery = current_profile().get("delivery")
    weekly = delivery.get("weekly") if isinstance(delivery, dict) else None
    if context == "weekly" and not (isinstance(weekly, dict) and weekly.get("enabled") is True):
        result.update(status="weekly_delivery_disabled",
                      next=["Stop before research or delivery: weekly delivery is disabled in the current profile."])
        return result
    prepared = _helper("context")["prepare"](root_path)
    profile = current_profile()
    plan = _helper("curation")["make_plan"](profile, request, context, mode, seed, fixed, repeat_count, scope)
    skill = SCRIPTS.parent
    if out:
        workdir = Path(out).expanduser().resolve()
        if workdir == skill or skill in workdir.parents:
            raise WorkflowError("the working folder must be outside the installed skill")
        if (workdir / "start.json").exists():
            raise WorkflowError("this working folder already holds a request; choose a new folder for a new plan")
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="trurl-request-")).resolve()
    batch_id = "batch-" + _stamp()
    files = {"plan": str(workdir / "plan.json"), "start": str(workdir / "start.json")}
    _write_json(workdir / "plan.json", plan)
    review = _helper("hypotheses")["maintenance_plan"](root_path, plan=plan)
    profile_path = str(root_path / "model" / "profile.json")
    explore = ["explore", "--plan", files["plan"], "--profile", profile_path, "--root", str(root_path),
               "--count", str(count)] + (["--seed", str(discovery_seed)] if discovery_seed is not None else [])
    research = ["Research and verify candidates, then save them as candidates.json in the working folder.",
                "curation.py graph-update --root <root> --research <workdir>/candidates.json --batch-id <batch_id> "
                "--reason <what the sources support> [--delta <delta.json>]",
                "curation.py select --root <root> --batch-id <batch_id> --plan <workdir>/plan.json "
                "--candidates <workdir>/candidates.json --count <n> > <workdir>/selection.json",
                "After delivering the picks: curation.py record --workdir <workdir>"]
    if review["review_due"]:
        files["maintenance_review"] = str(workdir / "maintenance-review.json")
        _write_json(workdir / "maintenance-review.json", review)
        status, maintenance, exploration = "maintenance_due", review, None
        steps = ["Read references/taste-hypotheses.md and review the saved maintenance plan.",
                 "curation.py hypotheses maintenance-complete --root <root> --review <workdir>/maintenance-review.json "
                 "--outcome <saved|reviewed|no_proposal> --reason <text>",
                 "curation.py explore --root <root> --plan <workdir>/plan.json --profile <root>/model/profile.json "
                 "--count <n> > <workdir>/exploration.json"] + research
    else:
        files["exploration"] = str(workdir / "exploration.json")
        exploration = _call("diversity", explore)
        _write_json(workdir / "exploration.json", exploration)
        status, steps = "ready", research
        maintenance = {key: review[key] for key in ("eligible", "review_due", "triggers", "evidence_fingerprint")}
    result.update(status=status, batch_id=batch_id, workdir=str(workdir), files=files, context=prepared, plan=plan,
                  hypothesis_maintenance=maintenance, exploration=exploration, next=steps)
    _write_json(workdir / "start.json", result)
    return result


def _brief_used(root, started):
    """Describe the working brief for the batch trace without copying its prose."""
    shown = started.get("context", {}).get("brief", {}) if isinstance(started, dict) else {}
    if isinstance(shown, dict) and shown.get("status") == "fresh" and shown.get("file_sha256"):
        return {"version": shown.get("version"), "file_sha256": shown["file_sha256"], "status": "fresh",
                "checked": "at_start"}
    current = IO["check"](root)
    if current["status"] == "fresh":
        data = IO["_read"](root, IO["BRIEF_PATH"])
        return {"version": current["version"], "file_sha256": IO["_digest"](data), "status": "fresh",
                "checked": "at_record"}
    return {"status": "raw_model_fallback",
            "reason": "curator's brief was " + current["status"] + ": " + "; ".join(current.get("reasons", []))}


def _pool(selection, candidates, delivered):
    outcomes = {item["id"]: {"outcome": "delivered" if item["id"] in delivered else "selected_not_delivered"}
                for item in selection["selected"]}
    for item in selection.get("excluded", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            outcomes.setdefault(item["id"], {"outcome": "excluded", "reasons": item.get("reasons", [])})
    details = {item["id"]: item for item in list(candidates or []) + selection["selected"]
               if isinstance(item, dict) and isinstance(item.get("id"), str)}
    return [dict({"id": identifier}, **{key: details[identifier][key] for key in POOL_FIELDS
                                        if key in details.get(identifier, {})}, **outcome)
            for identifier, outcome in outcomes.items()]


def record(workdir=None, root=None, batch_id=None, plan=None, selection=None, exploration=None, candidates=None,
           deliver=(), protocol=None):
    """Append the delivered recommendations and their batch trace once; safe to repeat after an interrupted run."""
    folder = Path(workdir).expanduser() if workdir else None

    def source(explicit, name):
        if explicit:
            return Path(explicit).expanduser()
        return folder / name if folder is not None and (folder / name).is_file() else None

    started = _read_json(folder / "start.json", "start.json") if folder is not None and (folder / "start.json").is_file() else {}
    plan_path, selection_path = source(plan, "plan.json"), source(selection, "selection.json")
    if plan_path is None or selection_path is None:
        raise WorkflowError("record needs the retained plan and the select output: pass --workdir, or --plan and --selection")
    plan_data, chosen = _read_json(plan_path, "plan"), _read_json(selection_path, "selection")
    exploration_path, candidates_path = source(exploration, "exploration.json"), source(candidates, "candidates.json")
    if candidates_path is None:
        candidates_path = source(None, "candidates.jsonl")
    explored = _read_json(exploration_path, "exploration") if exploration_path else None
    researched = _read_json(candidates_path, "candidates", jsonl=True) if candidates_path else None
    if isinstance(researched, dict):
        researched = next((researched[key] for key in ("items", "candidates") if key in researched), None)
    batch_id = batch_id or started.get("batch_id")
    root = root or started.get("root")
    if not _text(batch_id) or len(batch_id) > 200:
        raise WorkflowError("record needs the batch id used for selection (--batch-id, or the start.json in --workdir)")
    if not isinstance(plan_data, dict) or not isinstance(plan_data.get("effective_weights"), dict):
        raise WorkflowError("the plan must be the planner's JSON output")
    if (not isinstance(chosen, dict) or not isinstance(chosen.get("selected"), list)
            or any(not isinstance(item, dict) or any(not _text(item.get(field)) for field in IDENTITY_FIELDS)
                   for item in chosen["selected"])):
        raise WorkflowError("the selection must be the select command's JSON output")
    update = chosen.get("graph_update")
    if isinstance(update, dict) and update.get("batch_id") not in (None, batch_id):
        raise WorkflowError("the selection was made for another batch: " + str(update.get("batch_id")))
    selected = {item["id"]: item for item in chosen["selected"]}
    wanted = list(deliver) or list(selected)
    unknown = [identifier for identifier in wanted if identifier not in selected]
    if unknown or len(set(wanted)) != len(wanted):
        raise WorkflowError("delivered ids must be distinct selected items: " + ", ".join(unknown or wanted))
    if not wanted:
        raise WorkflowError("nothing was selected, so there is no delivery to record")
    root_path = IO["_root"](_resolve(root)["root"])
    now = _now()
    items = []
    for identifier in wanted:
        item = selected[identifier]
        entry = {"id": batch_id + "." + identifier, "candidate_id": identifier,
                 "canonical_url": item["canonical_url"], "title": item["title"], "creator": item["creator"],
                 "medium": item["medium"], "status": "recommended", "engagement": "unknown", "batch_id": batch_id,
                 "recommended_at": now, "lane": item["lane"]}
        entry.update({key: item[key] for key in OPTIONAL_FIELDS if key in item})
        entry["weighted_total"] = (item.get("base_score") if item.get("scoring_basis") == "six_axis_weighted_fit"
                                   else None)
        entry["source_provenance"] = item.get("source_provenance") or [{"kind": "trurl_delivery", "batch_id": batch_id}]
        items.append(entry)
    identifiers = [entry["id"] for entry in items]
    constraints = plan_data.get("constraints") if isinstance(plan_data.get("constraints"), dict) else {}
    with _lock(root_path):
        history_bytes, history = _ledger(root_path, RECOMMENDATIONS)
        batch_bytes, batches = _ledger(root_path, BATCHES)
        earlier = next((item for item in batches if item.get("id") == batch_id), None)
        if earlier is not None:
            if earlier.get("recommendation_ids") != identifiers:
                raise WorkflowError("this batch id is already recorded with different items: " + batch_id)
            return {"schema_version": 1, "command": "record", "status": "already_recorded", "batch_id": batch_id,
                    "recommendation_ids": identifiers, "changed": False}
        known = {item.get("id"): item for item in history}
        fresh = []
        for entry in items:
            previous = known.get(entry["id"])
            if previous is None:
                fresh.append(entry)
            elif previous.get("batch_id") != batch_id or previous.get("canonical_url") != entry["canonical_url"]:
                raise WorkflowError("recommendation id is already used by another work: " + entry["id"])
        before = [item for item in history if item.get("batch_id") != batch_id]
        trace = {"id": batch_id, "created_at": now, "context": plan_data.get("context"),
                 "request": constraints.get("request"), "weight_plan": plan_data, "recommendation_ids": identifiers,
                 "hypothesis_maintenance": chosen.get("hypothesis_maintenance") or {
                     "status": "pending", "reason": "selection ran without a rooted maintenance check"},
                 "graph_update": update or {"status": "pending", "reason": "selection ran without a graph update check"},
                 "curators_brief": _brief_used(root_path, started),
                 "generation_protocol": protocol or ("varied_briefs" if explored is not None else "unspecified"),
                 "selection_plan": chosen,
                 "diversity_audit": _helper("diversity")["audit_items"]([selected[i] for i in wanted], before),
                 "candidate_pool": _pool(chosen, researched if isinstance(researched, list) else None, set(wanted))}
        if explored is not None:
            trace["discovery_plan"] = explored
        if fresh:
            _append(root_path, RECOMMENDATIONS, history_bytes, fresh)
        _append(root_path, BATCHES, batch_bytes, [trace])
    return {"schema_version": 1, "command": "record", "status": "recorded", "batch_id": batch_id,
            "recommendation_ids": identifiers, "changed": True,
            "pending": [name for name in ("hypothesis_maintenance", "graph_update")
                        if trace[name].get("status") == "pending"],
            "next": ["Delivery is not feedback. Record a reaction only when the person volunteers one: "
                     "curation.py feedback --recommendation-id <id> --signal <signal> --words <their words>"]}


def feedback(root=None, words="", signal="", recommendation_id=None, hypothesis_id=None, kind=None, sources=(),
             changes=None):
    """Append one reaction in the person's own words; profile changes stay the author's decision."""
    token = signal.strip().casefold().replace("-", "_").replace(" ", "_") if isinstance(signal, str) else ""
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", token):
        raise WorkflowError("signal must be a short label such as useful, not_for_me, already_knew or want_more")
    if token in NOT_FEEDBACK:
        raise WorkflowError("a delivery, suggestion or assistant view is not the person's feedback: " + token)
    if not _text(words):
        raise WorkflowError("feedback needs the person's actual words")
    if kind is not None and kind not in FEEDBACK_KINDS:
        raise WorkflowError("kind must be one of: " + ", ".join(FEEDBACK_KINDS))
    changes = [] if changes is None else changes
    if (not isinstance(changes, list)
            or any(not isinstance(change, dict) or set(change) != CHANGE_FIELDS or not _text(change.get("path"))
                   or not _text(change.get("reason")) for change in changes)):
        raise WorkflowError("profile changes must be an array of objects with path, before, after, reason and source_provenance")
    root_path = IO["_root"](_resolve(root)["root"])
    now = _now()
    with _lock(root_path):
        unused, history = _ledger(root_path, RECOMMENDATIONS)
        current, events = _ledger(root_path, FEEDBACK)
        event = {"id": "feedback-" + _stamp(), "recommendation_id": recommendation_id, "recorded_at": now,
                 "signal": token, "user_words": words.strip()}
        if recommendation_id is not None:
            target = next((item for item in history if item.get("id") == recommendation_id), None)
            if target is None:
                raise WorkflowError("unknown recommendation id: " + str(recommendation_id))
            event.update({key: target[key] for key in ("batch_id", "selection_channel") if target.get(key)})
            hypothesis_id = hypothesis_id or target.get("hypothesis_id")
        if hypothesis_id:
            event["hypothesis_id"] = hypothesis_id
        if kind:
            event["feedback_kind"] = kind
        # Without an original message locator, keep unlocated reactions in one
        # source group rather than inventing independent corroboration per event.
        event["source_provenance"] = list(sources) or [{"id": "unlocated-current-conversation",
                                                       "kind": "current_conversation", "recorded_at": now}]
        event["profile_changes"] = changes
        repeated = next((item for item in events if all(item.get(key) == event.get(key) for key in
                                                        ("recommendation_id", "hypothesis_id", "signal", "user_words"))), None)
        if repeated is not None:
            return {"schema_version": 1, "command": "feedback", "status": "already_recorded",
                    "id": repeated.get("id"), "changed": False}
        _append(root_path, FEEDBACK, current, [event])
    return {"schema_version": 1, "command": "feedback", "status": "recorded", "id": event["id"], "changed": True,
            "next": ["Scope any profile change to what the words support (references/feedback.md).",
                     "curation.py hypotheses maintenance-plan --root <root> --event feedback",
                     "Refresh the curator's brief if its sources changed."]}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="trurl", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start", help="one call: root, context, the retained plan and research briefs")
    begin.add_argument("--root", help="curation root; defaults to the resolved location")
    begin.add_argument("--request", default="")
    begin.add_argument("--context", choices=("on_demand", "weekly"), default="on_demand")
    begin.add_argument("--mode", choices=MODES, default="auto")
    begin.add_argument("--scope", choices=("auto", "broad", "focused"), default="auto")
    begin.add_argument("--seed", type=int, help="weight-variation seed")
    begin.add_argument("--discovery-seed", type=int, help="separate seed for the research briefs")
    begin.add_argument("--fixed", action="store_true", help="use the profile baseline unchanged")
    begin.add_argument("--repeat-count", type=int, default=0, help="prior consecutive broad on-demand requests")
    begin.add_argument("--count", type=int, default=5, help="number of research briefs")
    begin.add_argument("--out", help="new private working folder for this request; defaults to a fresh temporary folder")
    log = commands.add_parser("record", help="append delivered picks and their batch trace to the ledgers")
    log.add_argument("--workdir", help="the start command's working folder, holding plan.json and selection.json")
    log.add_argument("--root")
    log.add_argument("--batch-id")
    log.add_argument("--plan")
    log.add_argument("--selection", help="the select command's saved JSON output")
    log.add_argument("--exploration")
    log.add_argument("--candidates", help="researched candidates, to keep their verification in the trace")
    log.add_argument("--deliver", action="append", default=[], metavar="CANDIDATE_ID",
                     help="record only these selected items; repeat per item (default: every selected item)")
    log.add_argument("--protocol", choices=PROTOCOLS, help="how candidates were generated")
    reaction = commands.add_parser("feedback", help="append one reaction in the person's own words")
    reaction.add_argument("--root", help="curation root; defaults to the resolved location")
    reaction.add_argument("--words", required=True, help="the person's actual words")
    reaction.add_argument("--signal", required=True, help="useful, not_for_me, already_knew, want_more, want_less, enjoyed ...")
    reaction.add_argument("--recommendation-id", help="omit for a general preference")
    reaction.add_argument("--hypothesis-id")
    reaction.add_argument("--kind", choices=FEEDBACK_KINDS)
    reaction.add_argument("--source", action="append", default=[], help="profile source id; repeat as needed")
    reaction.add_argument("--changes", help="JSON array of profile changes already applied for this feedback")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.root, args.request, args.context, args.mode, args.scope, args.seed, args.fixed,
                           args.repeat_count, args.count, args.discovery_seed, args.out)
        elif args.command == "record":
            result = record(args.workdir, args.root, args.batch_id, args.plan, args.selection, args.exploration,
                            args.candidates, args.deliver, args.protocol)
        else:
            result = feedback(args.root, args.words, args.signal, args.recommendation_id, args.hypothesis_id,
                              args.kind, args.source, _read_json(args.changes, "changes") if args.changes else None)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        parser.exit(2, "trurl: " + str(error) + "\n")


if __name__ == "__main__":
    sys.exit(main())
