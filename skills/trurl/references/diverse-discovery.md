# Broaden the pool, then select the collection

Changing scoring weights cannot recover a work that never enters the candidate pool. The discovery helper makes separate, replayable plans for exploration and selection. These are engineering heuristics informed by research, not a validated cure for recommendation homogenization.

## Before candidate generation

`curation.py start` does these steps for a rooted request: it makes the plan once, checks hypothesis maintenance and returns the briefs below. To run them separately, create the usual weight plan exactly once. Check [hypothesis maintenance](taste-hypotheses.md#check-and-complete-maintenance) with that plan and complete any due review before candidate research. Then call the bundled helper using the retained plan and the current profile:

```sh
python3 scripts/diversity.py explore --root /path/to/curation --plan /path/to/weight-plan.json --profile /path/to/curation/model/profile.json --history /path/to/curation/model/recommendations.jsonl --seed 1701 --count 5
```

Resolve paths relative to the installed skill. The pure discovery helper is read-only. Rooted `explore` first synchronises private interest mappings and isolated anchor nodes, then uses the local graph automatically unless a separate graph is supplied. For a normal run, omit a fixed seed to obtain actual external randomness and retain the returned seed. Keep this seed separate from weight variation. The supplied registry is a small, editable editorial pool, not an unbiased representation of every field of knowledge.

For broad discovery, use different approaches and source families rather than five rephrasings of one popular query. Connected surprise starts from explicit or evidenced tentative interests, or a concrete current-request detail. Preserve each anchor's actual kind, confidence, knowledge uncertainty, and provenance. Its briefs develop the anchored subject and a limited neighboring exploration; they do not draw unrelated catalog fields. If bare surprise has no usable context, the plan reports insufficient context so the host can obtain one interest or goal rather than invent fit. Focused requests remain inside their subject and constraints.

With [taste hypotheses](taste-hypotheses.md), `explore` checks feedback and recommendation evidence and can place one active hypothesis in an existing adjacent slot on a broad request, carrying a primary interest and at most one compact supporting interest. It prefers active hypotheses without a delivered probe. With no active hypothesis, rooted discovery keeps the ordinary anchored direction after the completed review; it does not repeat an unchanged no-proposal decision. Read original context by ID; a compact excerpt or a sampled pair does not establish fit. With `--root`, the CLI checks the current completion record and requires profile and ledger paths from that same root. It reads those ledgers by default. New broad, non-wildcard plans require the root; retain the returned `hypothesis_maintenance` result with the batch trace. Python callers supply both ledgers to validate supported interests. Retain the saved `hypothesis_id` on candidates, use lane `adjacent`, and ground `personal_connection` in an original anchor. The selector allows at most one hypothesis pick, with the normal connected-fit checks. Focused requests and wildcard mode use their existing discovery behavior.

Other modes may permit distant fields. A fully unrelated `wildcard` needs explicit user intent and is never chosen automatically. Different subject matter, obscurity, or unsettling content is not itself a reason to recommend something.

The explicit `open` mode permits a bounded independent component without inventing a personal link. A standing scoped opt-in can also authorize a personal plan's supplied distant mix. Missing permission leaves ordinary known modes connected; legacy supplied plans without a mode retain their caller's mix for compatibility. In all cases follow the retained plan and current request rather than silently changing the exploration amount.

Exact label exclusions do not guarantee semantic distance. Check the drawn field against known interests; if it is actually adjacent, relabel it or record an explicit rejection and redraw reason. Do not silently claim it was distant.

## Use a sourced graph frontier

When a content graph is available, add `--graph /path/to/model/graph.json` to `explore`, or inspect its routes with:

```sh
python3 scripts/curation.py graph-check --graph /path/to/model/graph.json
python3 scripts/curation.py frontier --graph /path/to/model/graph.json --profile /path/to/model/profile.json --seed 1701 --count 5
```

Read [knowledge graph and interest discovery](knowledge-graph.md) before maintaining graph facts or using optional `--allow-open --open-count 1`. Keep content relationships separate from personal evidence. Retain short, verified paths; a two-link relation is a route to investigate, not a direct fact or a transferred preference. A missing or invalid graph must not erase existing interests or create a reason to invent connections. Focused requests remain inside their exact scope even when a graph is supplied.

An optional compact `converging_route` shows another interest reaching the same destination. Inspect both origins and paths for a useful shared question; shared hubs or sources are not independent support and receive no relevance bonus. Primary routes and exploration quotas stay unchanged.

Category-stratified open draws give neglected areas an opportunity without selecting only high-degree graph hubs. The recorded eligible pool is incomplete; it is not every field the person could enjoy. The helper does not browse, verify remote claims, or learn preferences from its own routes.

## Elicit alternatives, not five favorites

Use a small pool, normally five meaningfully different directions, when the request and budget permit it. A distribution-style elicitation can ask:

> Propose five substantively different possible selections satisfying this request, including less obvious but credible options. For each, give its distinct direction, a source to investigate, and a brief reason it is worth checking. If using verbalized sampling, attach an estimate of how likely the generator would be to propose that option; label the estimate uncalibrated.

This is an adaptation of Verbalized Sampling, not a claim that our recommendation quality doubles. Generation likelihood, factual confidence, subjective quality, popularity, and the person's probability of enjoyment are different quantities. The selection helper ignores likelihood annotations. Never add them to the personal model as preference evidence.

Research the alternatives through distinct appropriate sources: original creators or publishers, journals, libraries or museums, practitioners, and official distributors or festivals as relevant. Several independent calls can still return the same favorite. Deduplicate actual work identities, retain how each work was found, and expand the pool if all routes converge. An unfamiliar item still needs a concrete reason to be worthwhile.

String Seed of Thought is an optional generation experiment for a host that can test it. Do not replace an available tool RNG with an imagined coin flip or present an LLM-generated string as statistically certified randomness. External RNG controls actual field draws and tie-breaking; it does not make the model's catalog complete.

## Verify before selecting

The host must check each candidate's work identity, direct sources, factual claims, and explicit constraints. Store `constraints_passed`, `credibility_passed`, verification evidence, and all six subjective priority scores. These supplied checks are not remote verification performed by the Python helper. An incomplete candidate is not silently promoted to verified status.

After verifying the pool, complete the [graph update](knowledge-graph.md#save-verified-relationships-after-research) against that exact candidate file and the batch ID. Save a bounded delta of supported content relationships or a reasoned `no_supported_changes` outcome. Reuse a current unchanged completion. This post-research check applies to new plans in every mode; it is separate from the pre-research hypothesis check.

```sh
python3 scripts/diversity.py select --root /path/to/curation --batch-id <batch-id> --plan /path/to/weight-plan.json --candidates /path/to/candidates.json --history /path/to/curation/model/recommendations.jsonl --count 5 --seed 1702
```

The selector checks the current graph completion against its actual candidate input and returns the compact `graph_update` result for the batch trace. It excludes prior work identities and candidates failing its supplied gates. It uses the retained weights, then considers creator/topic repetition and lane coverage. The minimum weighted score is subjective, not an enjoyment probability. Pure entertainment remains valid without an educational justification.

Connected surprise has additional checks that novelty cannot override: relevance at least 3/5; no distant items; and at most floor(requested count × 0.25) adjacent items, with one allowed for small collections. Every candidate also needs:

```json
{
  "personal_connection": {
    "basis": "tentative_interest",
    "anchor": "interest-record-id",
    "explanation": "A specific mechanism, question, narrative form, or aesthetic connection to that actual interest."
  }
}
```

Allowed bases are `explicit_interest`, `tentative_interest`, `current_request`, and `first_impression_feedback`. Use an actual interest ID, request detail, or feedback reference as the anchor. The host must verify the substance: the schema alone cannot establish a meaningful connection. Relevance is an editorial judgment, not a calibrated prediction. If only unrelated or poorly matched candidates survive, report a shortfall. Do not pad the collection or score a weak bridge generously just to fill it.

Format or randomness instructions alone do not establish a personal anchor. A subject or concrete goal can: “a film about memory” supplies a topic; “one film under 90 minutes” supplies only constraints. The `focused` lane is valid only for a retained focused plan, and must not be used to relabel adjacent candidates in a broad selection.

For broad-open selection, familiar and adjacent candidates retain those connection and relevance checks. A distant open candidate instead needs `personal_fit_status="unknown"`, a concrete `value_rationale`, and the same verification, credibility, and request gates. Only this case can use `scores.relevance=null`; the helper computes a clearly marked value score using the other five weights and ignores any supplied numeric relevance for an open item. No remaining weight mass means no valid value score. At four items, at most one may be independent and at most one adjacent. Explicit broad `open` reserves one qualified independent item; retain `required_open_items`, `selected_open_items`, and `open_shortfall` from selection. If none qualifies, do not pad its slot with familiar material. Focused plans and current opt-outs suppress unrelated candidates and the reservation. Standing-authorized personal plans with a distant allocation retain the same open eligibility policy but do not require an open item. Report a shortfall rather than adding an unsupported personal reason or weakening source checks.

Compare candidates together instead of repeatedly choosing the most obvious single item and treating those choices as new user preferences. If the user requested one creator, pass the documented repeat override; if they requested a focused or fixed selection, preserve that instruction. Report a shortfall rather than relaxing credibility or constraints to fill a diversity quota. Never optimize obscurity or difference at the expense of the actual request.

## Audit what was delivered

```sh
python3 scripts/diversity.py audit --items /path/to/this-batch.json --previous /path/to/model/recommendations.jsonl
```

Retain work-repeat rate, creator concentration, topic coverage, and missing-label counts over comparable windows. Use consistent labels and report incomplete metadata. These are descriptive properties of an observed collection, not measurements of psychological identity or enjoyment.

Keep within-person breadth separate from between-person similarity. For the latter, compare work overlap across several explicit synthetic profiles under the same constraints and source access. Identical recommendations can be appropriate, and reduced overlap alone does not establish improvement. Evaluate verified usefulness and constraint compliance alongside diversity.

Log the exact discovery plan, candidate pool provenance, checked graph completion, selection result, and delivered-item audit in the batch record. Keep the earlier frontier unchanged when later research adds graph facts. Keep internal candidates out of the delivered-recommendation ledger. Preserve the personal baseline and its full range of evidenced interests; the engine's own selections, probability annotations, and absent replies never teach it that those selections were liked.
