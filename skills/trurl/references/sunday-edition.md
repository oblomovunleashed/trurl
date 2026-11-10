# Sunday edition

The Sunday edition is one verified pick in each chosen format, presented as a designed issue with a linked text version. Request an issue any time. On hosts with scheduling, first-time profile setup includes Sunday delivery unless the person opts out after seeing the proposed slot. Use the [weekly delivery rules](weekly-delivery.md) to check activation or turn delivery off.

## Select the issue

1. Use the categories in the request, or the profile’s enabled categories if the request leaves them open. Keep the chosen order. Trurl’s six standard categories are books, podcasts, films, YouTube videos, lectures and scientific papers. Assign each work to one category in the candidate pool. A lecture hosted on YouTube can fill either relevant category, with its canonical work appearing once across the edition.
2. Check the curator’s brief, the current profile, past recommendations and feedback as usual. Make one [request plan](adaptive-weights.md) before research. Use the `weekly` planning context for an active scheduled run and `on_demand` for a requested issue; `curation.py start --context weekly` makes the plan and stops a scheduled run while delivery is disabled. Apply medium, time, language and other explicit limits within each category. Check [hypothesis maintenance](taste-hypotheses.md#check-and-complete-maintenance) against that plan and complete any due review before research; an unchanged current completion record can be reused.
3. Research more than one lead per category where the budget allows. Verify the work, creator, direct link and any details printed in the issue. Score each qualifying candidate under the retained plan. Complete the [graph update](knowledge-graph.md#save-verified-relationships-after-research) for this candidate pool and batch ID, saving supported relationships or a reasoned no-change outcome. Run the shared selector with one `--category` argument for each chosen medium. It selects at most one eligible work per category, applies the lane limits across the whole issue, and reports unfilled categories in `missing_categories`.
4. Follow the [skill's delivery rules](../SKILL.md#present-the-picks). Give each work a one-line description and include useful verified details such as a running time or publication year.

```sh
python3 <skill-directory>/scripts/curation.py select --root /path/to/curation --batch-id <batch-id> --plan /path/to/plan.json \
  --candidates /path/to/candidates.json --history /path/to/curation/model/recommendations.jsonl \
  --category book --category podcast --category film \
  --category youtube_video --category lecture --category scientific_paper
```

## Render and deliver

Create a UTF-8 JSON file with the selected public-facing fields.

| Field | Value |
| --- | --- |
| `edition_date` | The issue’s Sunday in ISO `YYYY-MM-DD` form. Use the person’s local date for a scheduled issue. |
| `categories` | A list of distinct medium IDs in display order. Standard IDs are `book`, `podcast`, `film`, `youtube_video`, `lecture` and `scientific_paper`. |
| `picks` | An array of selected works. Each has `medium`, `title`, `creator` and a direct `canonical_url`. Include optional `description` and `detail` strings for a short description and verified metadata. Omit the pick for a category left open. |

From an installed skill, run the renderer from its own folder or pass its full path. Choose a separate output directory per issue.

```sh
python3 <skill-directory>/scripts/curation.py sunday render --input /path/to/issue.json --output-dir /path/to/edition
```

From the repository, use `python3 trurl.py sunday render` with the same arguments. Deliver the designed `sunday-edition.svg` with `sunday-edition.md`, which carries the direct links and any empty category. The renderer works from the issue input. The host supplies research, source verification and any active schedule. After delivery, `curation.py record --workdir <working-folder>` logs the delivered items, the retained plan and the checked graph completion in the private ledgers. For a public example, share only the approved issue’s picks, descriptions and links. Keep the profile, brief, history and scoring trace in the private workspace.
