# Taste hypotheses

Use this workflow proactively after onboarding, when meaningful personal evidence changes, and before broad curation. The host forms and interprets hypotheses. The helper determines when review is due, checks saved evidence and records whether the review was completed.

## Check and complete maintenance

After retaining the request's scoring plan, check for required profile or broad-discovery maintenance before candidate research and save the returned review in the private workspace. `curation.py start` runs this check and saves a due review as `maintenance-review.json` in its working folder; the command below runs it alone.

```sh
python3 <skill-directory>/scripts/curation.py hypotheses maintenance-plan --root <curation-root> --plan <request-plan.json>
```

Immediately after saving original interests, use `--event onboarding` instead of `--plan`; after meaningful sourced feedback, use `--event feedback`. Check and complete that profile-update review within the same invocation before the first or next picks. There is no interest-count threshold: one eligible original anchor can trigger the first review. A profile without a substantive original anchor has nothing to infer from yet.

Profile updates and request breadth are separate. A focused request still checks initial or changed original evidence; unchanged focused requests do not refill a sparse hypothesis pool. Wildcard planning stays independent and skips broad maintenance, but does not complete a separate onboarding or feedback event for the agent. One requested pick can be broad, and a due review never changes the requested count, subject or seeds.

The helper triggers the first review, an invalid completion record, changed original interests or their provenance, meaningful sourced user feedback, changed hypotheses, or a pool with fewer than two untried testing hypotheses after a delivered probe. It remembers the evidence reviewed. An unchanged sparse pool, including a decision that no useful proposal exists, does not repeatedly trigger generation. Ordinary delivery and consumption are not feedback; delivered `hypothesis_id` values only identify opportunities already used.

When `review_due` is true, use its compact anchor suggestions as pointers to the originals. Assess a few plausible explanations and create at most one new hypothesis. Revise existing explanations or their evidence when needed. Existing hypotheses do not excuse skipping changed evidence. Explain each original interest's contribution, a competing explanation and the kind of work that could distinguish them. Check rejected or retired proposals before reusing an idea. Save a useful proposal through the workflow below; do not invent a preference merely to satisfy a quota.

Record one outcome against the saved review:

```sh
python3 <skill-directory>/scripts/curation.py hypotheses maintenance-complete --root <curation-root> --review <private-review.json> --outcome saved --hypothesis-id <saved-id> --reason "A specific connection grounded in the reviewed interests."
```

Use `saved` to identify one actual new or revised persisted hypothesis. A review may create at most one new hypothesis; reconciling evidence or retiring an older explanation may also revise existing records. Use `reviewed` with current testing hypothesis IDs when the existing pool remains useful, or `no_proposal` with a short concrete reason when no defensible proposal emerges. These alternatives complete the review without manufacturing new interests. Keep the completion rationale concise; the original anchors and hypothesis records hold the detailed reasoning.

The helper rejects a stale review if relevant original evidence changed while it was being considered. An invalid completion record requires a fresh review and is replaced only when that review is completed. Reread that evidence and obtain a fresh review. It writes the latest completion record to private `model/hypothesis-maintenance.json`, separately from the profile so bookkeeping alone does not invalidate the curator's brief. It verifies source freshness and saved changes, not the truth or quality of the host's interpretation.

Before delivery, check the record against the same request plan:

```sh
python3 <skill-directory>/scripts/curation.py hypotheses maintenance-check --root <curation-root> --plan <request-plan.json>
```

The check exits unsuccessfully when an eligible review is pending. Always pass `--root <curation-root>` to `explore` and `select`. Newly generated non-wildcard plans require it, including focused plans, so omitting the root cannot skip a pending profile review. Those commands check maintenance before eligible research and selection. Retain their compact checked result in the batch trace, including a reused current completion. If a helper or persistent storage is unavailable, record a pending review and the concrete limitation, then follow the manual-selection fallback with that method limit disclosed. Do not label it completed.

Maintenance runs within the current invocation, including an existing authorized scheduled run. It creates no new schedule, requests no additional sources, and requires no separate model call. The helper emits at most two compact anchor suggestions when review is due. The host creates at most one new hypothesis per review, the existing cap of eight testing hypotheses remains, and exploration uses the existing adjacent allowance.

## Propose a direction

Start from what the person actually stated or from supported observations in their profile. Consider a few plausible explanations for the appeal, including themes and style. A creator preference can support several competing possibilities. A named work or the person's explanation can distinguish them.

For broad discovery, assess a few pairs of original interests and, when defensible, propose one concrete shared question, place, method or quality. Explain each interest's contribution; two useful connections can suffice without forcing a third. A shared country or other broad label alone is weak support. Keep competing explanations open, and check rejected or retired proposals before recreating one. Temporary requests and interests derived from other hypotheses cannot supply new hypothesis origins.

Keep proposals in the optional `taste_hypotheses` array in `model/profile.json`. Each has an `id`, `topic`, `anchor_ids`, `reason`, `status` and `evidence`. Use `testing` with empty evidence for a new proposal. The helper records the source fingerprints and derives later status.

Use actual original interest IDs. Keep hypothetical examples and reference-only mentions out of the model. Verify proposed content relationships during research. A source establishing a relationship supplies no evidence that the person enjoys its destination.

Capture a snapshot before writing the draft.

```sh
python3 <skill-directory>/scripts/curation.py hypotheses snapshot --root <curation-root>
```

Keep its `schema_version` and `sources`, and edit its `taste_hypotheses` list. Preserve existing records and evidence. Save the draft in the private workspace and apply it with the helper.

```sh
python3 <skill-directory>/scripts/curation.py hypotheses save --root <curation-root> --draft <private-draft.json>
```

If sources have changed, read them and take a new snapshot before revising the draft. The helper writes the profile atomically and preserves unrelated fields. A changed profile invalidates an earlier curator’s brief; recheck and refresh it before using its prose for selection. Remove temporary drafts after saving.

## Explore through useful picks

On a broad request, `explore` can use one existing adjacent research slot for an active hypothesis. It prefers active hypotheses that have not yet had a delivered probe, then uses its seed to vary the choice. It keeps the primary `interest_evidence` and may add one compact `supporting_interest`. The nested `taste_hypothesis` contains an excerpt, up to two selected anchor IDs, the total anchor count and checked evidence-summary flags; it omits raw feedback and hashes. Read the original records by ID, including omitted origins or rationale, before assessing fit. More anchors do not raise preference confidence.

With no active hypothesis, rooted discovery respects the completed maintenance outcome and keeps the original single-interest direction. Legacy or low-level discovery without a checked receipt may instead carry `hypothesis_action="propose"` and two eligible original interests; this is a research prompt, not a saved preference or a completed review. Do not restart an unchanged no-proposal decision. If genuinely new personal evidence emerges during research, obtain a current review before saving a new proposal. Retain an actual original anchor in `personal_connection` and carry the saved `hypothesis_id` through candidates and delivered records. No extra brief or recommendation is added.

Choose a worthwhile work under the usual source, relevance and request constraints. The selector caps hypothesis picks at one per selection. If no suitable work qualifies, use another eligible candidate. Focused requests keep their requested subject, and wildcard requests use independent discovery.

Keep the hypothesis and selection evidence in the private trace. Present the pick and its short description using the [delivery rules](../SKILL.md#present-the-picks). Learn from feedback the person volunteers or a feedback workflow they request.

## Learn from reactions

Record the user's actual words in `model/feedback.jsonl` first, with source provenance, date and target. Add a reference to that event in the relevant hypothesis's `evidence` list. Each reference contains `feedback_id`, `effect`, `scope` and a `reason` explaining the host's interpretation.

| Evidence | Treatment |
| --- | --- |
| Enjoyment of a particular work | Use `effect="support"`, `scope="work"` and a feedback signal such as `enjoyed`, `liked`, `loved` or `experienced_enjoyment`. Keep the event linked to the delivered recommendation. |
| Explicit confirmation of the proposed interest | Use `effect="confirm"`, `scope="hypothesis"` and feedback signal `confirmed_interest`. The person's words must support that broader scope. |
| Explicit rejection of the proposed interest | Use `effect="contradict"`, `scope="hypothesis"` and feedback signal `rejected_interest`. |
| Dislike of one work | Record it against the work. If it challenges the proposed explanation, use `effect="contradict"` and `scope="work"` with the actual recommendation ID and reason. Broader rejection needs broader wording. |
| Willingness to try, familiarity, completion or silence | Keep the actual event meaning. These supply no enjoyment support for promotion. |

One enjoyed work leaves the inference tentative. Two independently sourced enjoyment responses about distinct works can produce a supported interest with `kind="inferred"`. This threshold is an engineering default. Conflicting work reactions keep the explanation tentative until clarified. Explicit confirmation produces `kind="explicit"`. The helper deduplicates work and source evidence and reserves managed interest IDs beginning `hypothesis:`.

Preserve alternatives while the appeal remains ambiguous. Retire a proposal when a narrower interpretation fits better and use a new ID for the revised topic or origin, retaining the earlier evidence and reason. Keep temporary moods and current tasks scoped to their request.

Enjoying a work that connects several themes does not confirm every interpretation. Distinguish enjoyment of the subject, historical change, a cultural setting or storytelling when volunteered feedback supports that distinction; do not infer it from delivery or silence.

## Reconcile and correct

Before using the curator's brief, reconcile current hypothesis evidence.

```sh
python3 <skill-directory>/scripts/curation.py hypotheses refresh --root <curation-root>
```

Changed or missing evidence makes dependent inferences stale and removes their managed interests from active discovery. Review the corrected source before rebuilding a proposal. The profile change invalidates an older brief through its existing freshness checks. Explicitly retired and rejected hypotheses stay out of discovery.

The original anchors and raw feedback remain available for inspection. The helper checks record structure, fingerprints and eligible signals. The host must assess whether the user's words support the claimed topic, quality and scope.

## Atlas and brief

The curator's brief can summarise supported patterns and clearly tentative possibilities. Its summaries never count as additional evidence.

The Taste Atlas does not change hypothesis evidence or preferences; exporting synchronises separate content-graph anchor mappings. It shows exploratory possibilities separately and can reveal their original anchor and reason. Recommendations use the underlying profile, feedback and sourced connections.
