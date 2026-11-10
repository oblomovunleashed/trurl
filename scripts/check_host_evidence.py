#!/usr/bin/env python3
"""Check supported-host package availability for this exact skill bundle.

This checks locally recorded test evidence, not cryptographic attestation or
recommendation quality. Default readiness requires isolated packaging and helper
checks for Codex, Claude Code and Pi; it does not require their CLIs, credentials or logins.
Use --require-live to require authenticated native integration evidence instead.
"""
import argparse
import importlib.util
import json
from pathlib import Path


def smoke_module():
    spec = importlib.util.spec_from_file_location("host_smoke_gate", Path(__file__).with_name("host_smoke.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def review(root, evidence_paths, require_live=False):
    smoke = smoke_module()
    required_scope = "authenticated_host" if require_live else "packaging_only"
    scope = ("Authenticated native skill loading and helper execution; recommendation quality needs separate evaluation."
             if require_live else
             "Codex, Claude Code and Pi package availability and isolated helper checks. Packaging-only passes establish neither native discovery nor authenticated host behavior.")
    folder = Path(root) / "skills/trurl"
    required = [folder / name for name in ("SKILL.md", "scripts/curation.py", "scripts/diversity.py", "scripts/graph.py", "references/domains.json")]
    if (not folder.is_dir() or folder.is_symlink()
            or any(not p.is_file() or p.is_symlink() for p in required)
            or any(p.is_symlink() for p in folder.rglob("*"))):
        result = {"schema_version": 1, "ready_to_publish": False, "bundle_sha256": None,
                  "required_scope": required_scope, "scope": scope,
                  "passed_hosts": {}, "missing_host_passes": list(smoke.AGENTS),
                  "observations": {}, "errors": ["Current skill bundle is missing, incomplete, or linked."]}
        if require_live:
            result["missing_live_passes"] = list(smoke.AGENTS)
        return result
    fingerprint = smoke.bundle_fingerprint(folder)
    validator_fingerprint = smoke.digest(Path(smoke.__file__))
    accepted, observations, errors = {}, {agent: [] for agent in smoke.AGENTS}, []
    for supplied in evidence_paths:
        path = Path(supplied)
        if path.is_dir():
            path = path / "summary.json"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            results = report["results"]
            if not isinstance(results, list):
                raise ValueError("results must be an array")
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(str(path) + ": " + str(error))
            continue
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("agent"), str) or result["agent"] not in observations:
                errors.append(str(path) + ": invalid or unknown host result")
                continue
            host = result["agent"]
            validation = result.get("validation", {})
            checks = validation.get("checks", {}) if isinstance(validation, dict) else {}
            checks = checks if isinstance(checks, dict) else {}
            current = (
                result.get("evidence_protocol") == smoke.EVIDENCE_PROTOCOL
                and result.get("validator_sha256") == validator_fingerprint
                and result.get("bundle_sha256") == fingerprint
                and result.get("synthetic_inputs_only") is True
            )
            live_pass = (
                current and report.get("mode") == "live" and result.get("mode") == "live"
                and result.get("evidence_level") == "authenticated_host"
                and result.get("status") == "passed" and result.get("live_status") == "passed"
                and type(result.get("returncode")) is int and result["returncode"] == 0
                and not result.get("timed_out", False)
                and isinstance(result.get("host_version"), str) and bool(result["host_version"].strip())
                and isinstance(validation, dict) and validation.get("passed") is True
                and validation.get("inputs_unchanged") is True and validation.get("errors") == []
                and checks.get("installed_skill_read_in_tool_trace") is True
                and checks.get("installed_helpers_in_tool_trace") == ["frontier", "graph-check", "weights"]
                and type(checks.get("native_tool_events")) is int and checks["native_tool_events"] > 0
                and (host != "pi" or checks.get("native_run_completed") is True)
            )
            packaging_pass = (
                current and report.get("mode") == "packaging_only" and result.get("mode") == "packaging_only"
                and result.get("evidence_level") == "packaging_only"
                and result.get("status") == "packaging_passed" and result.get("packaging_status") == "passed"
            )
            accepted_scope = "authenticated_host" if live_pass else "packaging_only" if packaging_pass and not require_live else None
            observations[host].append({"status": result.get("status"),
                                       "evidence_level": result.get("evidence_level"),
                                       "current_bundle": result.get("bundle_sha256") == fingerprint,
                                       "accepted_scope": accepted_scope,
                                       "reason": result.get("reason")})
            if accepted_scope and (host not in accepted or accepted_scope == "authenticated_host"):
                accepted[host] = {"evidence": str(path), "accepted_scope": accepted_scope}
                if accepted_scope == "authenticated_host":
                    accepted[host]["host_version"] = result["host_version"]
    missing = [host for host in smoke.AGENTS if host not in accepted]
    result = {"schema_version": 1, "ready_to_publish": not missing and not errors,
              "bundle_sha256": fingerprint, "required_scope": required_scope,
              "passed_hosts": accepted, "missing_host_passes": missing,
              "observations": observations, "errors": errors, "scope": scope}
    if require_live:
        result["missing_live_passes"] = missing
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--evidence", type=Path, action="append", required=True,
                        help="host_smoke summary.json or evidence directory; repeat to combine hosts")
    parser.add_argument("--require-live", action="store_true",
                        help="optionally require authenticated native integration passes for every supported host")
    args = parser.parse_args()
    result = review(args.root, args.evidence, require_live=args.require_live)
    print(json.dumps(result, indent=2))
    return 0 if result["ready_to_publish"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
