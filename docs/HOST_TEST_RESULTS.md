# Trurl installation and helper results

Checked **11 November 2026** on macOS with Python 3.13.0, using synthetic models and isolated temporary homes. No personal installations or private taste records were used.

| Target | Standalone skill installation and copied helpers |
| --- | --- |
| Codex | Passed |
| Claude Code | Passed |
| Pi | Passed |

The current skill-bundle SHA256 is `18168fd4a5beec77fa292ce9e4f51f77aa5ff64d1c6e3cb99c14f0926ce45abf`. The evidence checker accepted current reports for all three targets at the `packaging_only` level. These checks initialize synthetic state, execute installed planning/graph helpers outside the repository, and save/check a sparse curator's brief without changing preference evidence.

The complete source suite passed **484 tests**. New regressions cover 28 interests followed by one recommendation, focused profile-review completion and reuse, source/feedback corrections, preserved scope and seeds, and the unrooted CLI bypass. It includes graph update/completion validation, malformed hypothesis-record recovery, Atlas URL identity and ambiguity, compact context freshness and history-size checks, installed context execution, root discovery, release boundary checks and host-evidence validation. The skill validator also passed. Python 3.9 grammar checks pass; the CI matrix runs the actual suite on Python 3.9 and 3.13.

## Scope

These are installation and helper results. No authenticated host CLI/model session was launched for this revision. Packaging success does not establish native skill discovery, personal memory or research access, scheduling, recommendation quality or identical behavior across hosts. The Python helpers require no provider credentials; the host supplies any research and scheduling capabilities separately.

The reports include the current bundle and validator fingerprints. Old evidence cannot validate a changed bundle. Keep raw execution traces private; publish only synthetic fixtures and concise scope-qualified results.

## Reproduce

From this repository, use a fresh evidence directory:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/host_smoke.py --agent all --output /path/to/fresh/evidence
python3 scripts/check_host_evidence.py --evidence /path/to/fresh/evidence
```

GitHub Actions repeats the full suite and isolated helper checks without authentication. See [development checks](DEVELOPMENT.md), [host setup](HOSTS.md) and [whole-workflow evaluation](EVALUATION.md). Use `--require-live` only when reviewing separately collected authenticated integration evidence.
