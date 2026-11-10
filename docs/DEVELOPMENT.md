# Develop and validate Trurl

This repository is the source for the standalone skill and its complete synthetic test suite. Personal curation state belongs in a private root; `model/` directories at any depth are ignored. Never attach a real profile, feedback ledger or raw agent trace to an issue or pull request.

Use Python 3.9 or later and Git. The helpers use the Python standard library; no package installation is required.

```sh
python3 -m unittest discover -s tests -v
python3 trurl.py demo --format table --seed 42
python3 trurl.py graph-check --graph examples/graph.example.json
```

GitHub Actions runs the complete suite on Python 3.9 and 3.13 using Ubuntu 24.04, exercises the synthetic discovery examples, builds the release, and checks isolated skill bundles for Codex, Claude Code and Pi. A macOS job repeats the suite and the bundle checks on Python 3.13. Windows is untested. The test runner is pinned because Python 3.9 builds are unavailable on Ubuntu 26.04. The workflow needs no provider credentials and performs no model calls, personal installations or scheduling.

## Check the publication boundary

`release-files.json` explicitly lists every published source, test and resource. Add new public files to that manifest and stage them before checking the Git index:

```sh
python3 scripts/package_release.py --check
python3 scripts/package_release.py --output /path/to/fresh/release
```

The check rejects tracked files outside the allowlist and declared files missing from Git. Packaging rejects private state paths, path escapes and symlinks. Tests also require every test module and skill resource to be included, preventing an incomplete distribution from silently losing validation or installed helpers. The packager does not require Git unless `--check` is used.

Review the resulting archive before any release. Building an archive does not upload it or change repository visibility.

## Check installed helpers

Use a fresh evidence directory:

```sh
python3 scripts/host_smoke.py --agent all --output /path/to/fresh/evidence
python3 scripts/check_host_evidence.py --evidence /path/to/fresh/evidence
```

These checks install into temporary homes and execute each copied helper outside the repository. Reports must match the current skill and validator fingerprints; stale evidence is rejected. See the [host results](HOST_TEST_RESULTS.md) and [host guide](HOSTS.md) for the scope of these checks. Authenticated agent execution and whole-workflow recommendation quality require separate evidence described in the [evaluation guide](EVALUATION.md).
