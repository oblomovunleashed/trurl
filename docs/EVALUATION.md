# Evaluate the complete curation workflow

The Python tests check planner and release behavior. The [public scenarios](../evals/scenarios.json) test what a research-capable host actually does with the skill. A successful weighting calculation alone does not establish recommendation quality.

## Cross-host installation and integration

Run `python3 scripts/host_smoke.py --agent all --output /path/to/fresh/evidence` to install isolated copies for Codex, Claude Code and Pi and execute their bundled helpers outside the repository. This is a packaging/runtime check; CI repeats it for each host target without provider credentials. It does not launch an agent or establish native discovery.

Optionally run the same command with `--live` to exercise an actual authenticated host CLI. This is not required to make the skill available and does not require the creator to use every supported host. Each live case uses synthetic state and an isolated configuration, invokes the host's native skill name, and checks native tool traces for loading the installed skill and executing its helpers. Missing CLI, login, permission, or provider access must remain visible as blocked/failed live evidence, with a nonzero exit status. Packaging success does not change that live outcome. Use [the host guide](HOSTS.md) for prerequisites, invocation, and evidence locations.

Keep host version, test scope, bundle fingerprint, fixture hashes, native tool evidence, exit outcome, and unchanged-model checks with a run. Repeat the relevant checks after skill changes; an older result cannot validate a newer bundle. The default evidence check accepts current packaging/helper results for all three supported hosts for distribution. Its optional `--require-live` mode checks the stronger authenticated-integration claim. These narrow live checks establish loading and helper execution only. The whole-workflow scenarios below separately assess source access, onboarding, attribution, selection, feedback, and scheduling.

For Pi, distinguish metadata discovery from loading the full skill through `/skill:trurl` or a native read. Test its actual file and execution tools; do not assume a research backend, personal memory service or scheduler is installed. A passing helper run does not establish those capabilities. Record any extensions or MCP connections used in a broader behavioral case.

## Run a case

1. Create an isolated workspace and initialize an anonymous model with `python3 trurl.py init --root /path/to/isolated-workspace`.
2. Apply the scenario's synthetic setup. Use empty ledgers unless the case supplies history. Never copy a real person's model into an evaluation artifact.
3. Give the host the installed skill, the isolated curation root, and the exact prompt. Keep real scheduling and external messaging disabled for evaluation. For a no-delivery case, intercept tool calls so stopping before research can be observed.
4. Record the host/model, date, code revision, accessible tools, prompt, initial state, weighting inputs and seed, final response, tool activity, and state changes.
5. Judge each stated check as pass, fail, or unobservable. A grader needs the response and relevant state/tool evidence, not a claim by the agent that it followed the instructions.

For a comparison, repeat the same realistic prompt with the same starting profile and research access, once with the skill and once without it. Randomize presentation order for a human reviewer where practical. Keep factual constraints separate from subjective judgments about appeal, depth, relevance, and surprise. A small comparison is a development aid, not a population-level benchmark.

## Inspect the outcome

Judge in this order:

1. **Identity and evidence:** real title, creator, direct source, and support for factual claims.
2. **Requested constraints:** medium, count, duration, language, exclusions, and fixed-weight instructions.
3. **Memory:** duplicate avoidance, accurate recommendation history, and appropriate feedback scope.
4. **Personalization:** reasons supported by actual user evidence; unknown familiarity stays uncertain.
5. **Discovery:** worthwhile variety and a discernible change under deliberate surprise.

Record quality judgments in the reviewer's own words. Do not treat a click, completion, absent reply, or a high numerical score as proof of enjoyment. Include failures and inaccessible sources when sharing evaluation results.

## Code checks

```sh
python3 -m unittest discover -s tests -v
python3 trurl.py demo --format table --seed 42
```

The scenario pack is a reusable protocol. It is not an automatic benchmark runner, and no whole-workflow pass rate is claimed by publishing it. Contributions are most useful when they include the anonymous fixture, exact prompt, observed result, and a specific failed check.

## Check the curator's brief

Use a synthetic profile and feedback. Capture source hashes before composing a brief, save it with `scripts/brief.py`, then add a correction to the raw feedback and verify that `check` rejects the old summary. A fresh replacement must preserve unaffected explicit and tentative interests, source IDs, unknown knowledge and item-level first-impression scope. Include one unusual explicit interest among many recent tentative ones. A request-only change belongs in the retained batch plan rather than the enduring brief.

Check missing/empty and legacy profiles, invalid/missing sources, changed source files between snapshot and save, two competing writers, and explicit invalidation. A forgetting case must remove affected cached prose and dependent copies rather than only changing a timestamp. Verify that save/check never change the profile, ledgers, seed draws, weights, source choices or delivery settings. The copied helper is exercised in each isolated host availability check; this is not proof of authenticated host compliance.

For a human comparison, give both arms the same raw evidence, planner outputs, media constraints and research ceilings; add only the derived brief to the treatment. Freeze the first-round outputs before applying the same genuine correction to both. Keep the normal skill's latest-correction rule in the control. Report stochastic and source-access differences, editorial scores, partial ratings and any post-reveal feedback honestly. Do not infer better variety from more fine-grained topic labels or a recommendation-quality multiplier from a single preferred set.

## Check category-and-anchor onboarding

Run the onboarding scenarios with synthetic inputs and intercepted source tools. Check that a short category-plus-anchor answer reaches a useful selection without extra quiz steps, while a richer answer retains all relevant anchors and their scope. Memory use needs the person's affirmative source choice or an existing explicit authorization. Declined or unanswered offers must not trigger memory retrieval or profile imports; allowed memory that is unavailable must not trigger a substitute chat search. Verify separately whether source access happened and whether its evidence was interpreted accurately.

The skill guides a host conversation; the initializer only creates blank state. Unit tests verify fresh defaults, source-choice separation, and installation behavior. They do not establish that every host follows the onboarding instructions. In a real usability comparison, record completion, effort and waiting time, comfort with source use, the first selection's relevance, and later explicit enjoyment separately from initial willingness to try. No onboarding success rate is claimed by adding these cases.

## Check connected surprise

Also run the graph/open cases in the public scenario pack. Use fictional content facts and isolated personal evidence. Check that a newly stated interest can start independently, missing graph coverage falls back to direct anchored research, and illustrative examples stay outside the personal model. Graph paths must retain source edges and direction without becoming direct facts or preference updates. Retracted/hypothesis edges and ambiguous entity mappings must not become usable explanations.

For open mode, verify explicit authorization, preserved baseline weights, unknown relevance handled without a fabricated bridge, and source/value gates before variety. Use high-scoring familiar candidates to check that a broad explicit open request still includes one qualified independent pick, or reports its unfilled slot if no open candidate qualifies. Standing permission alone must not force one, and focused requests or current opt-outs suppress the reservation. Compare seed replay, minor-anchor coverage and hub concentration. A structurally valid JSON graph is not evidence that its claims are true. Runtime tests and scenario definitions do not establish improved recommendations; use prospective optional feedback and matched-budget comparisons as described in [the research review](GRAPH_RESEARCH.md).

Test the `connected_surprise_v1` policy on synthetic candidate pools before a live comparison. Include a very novel but low-relevance item, missing or generic connection evidence, enough connected candidates to fill a set, and several adjacent candidates competing for the same allowance. For a four-item request, at most one adjacent item can be selected. A shortfall is correct when the pool cannot meet the checks. Verify that an empty profile plus bare “surprise me” produces insufficient context, and that an explicitly requested wildcard remains separate from automatic rotation.

Inspect the meaning of each connection as well as its JSON shape. A vague analogy, fabricated interest, or a score inflated to pass the threshold is a failure even if the selector accepts the record. Compare Trurl, connected surprise, and an ordinary LLM at matched budgets on fresh inputs, with presentation order hidden where practical. Keep earlier experiments frozen and record the policy/code revision: the revised mode must earn its own preference and useful-diversity evidence.

For cross-theme discovery, compare one-interest briefs with the paired-interest brief at the same research budget and final count. Check that both origins are eligible personal evidence, omitted context is consulted, weak connections stay tentative and feedback does not confirm every possible explanation. Measure the serialized context added by one supporting interest and by graph convergence; long feedback histories must not be copied into the compact hypothesis summary. Graph fixtures should include a shared destination, aliases of one anchor, shared hubs/sources and disjoint interests. Verify the two-alternate cap, bounded search, unchanged primary/open draws and absence of scoring or preference updates. These checks establish the mechanism, not improved enjoyment.

## Test diversity mechanisms separately

Use the [research comparison protocol](SCIENTIFIC_BASIS.md#evaluation-that-can-distinguish-the-mechanisms) to compare direct generation, a five-item list, VS-style proposals, and varied externally seeded research briefs at matched budgets. Keep the final selection size and verification/selection procedure constant when comparing generation. Test selection heuristics separately on the same fixed candidate pool.

Measure actual unique works, creator/topic coverage, repeated works, and missing labels. Across several batches for one profile, assess breadth and concentration. Across different synthetic profiles under the same constraints, assess work overlap separately. Neither reduced overlap nor higher entropy establishes better recommendations; review verified usefulness, constraint compliance, and voluntary explicit feedback as well. Self-reported generation probabilities must not be used as enjoyment predictions or user-preference evidence.
