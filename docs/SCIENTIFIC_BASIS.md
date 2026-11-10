# Research behind the diversity workflow

Reviewed on **3 November 2026**. The papers below motivate engineering choices; they do not validate Trurl or establish that it improves enjoyment, identity, or long-term breadth of interests. The implementation is an experiment that can be evaluated.

## What the papers establish

| Source reviewed | Finding and important boundary |
| --- | --- |
| [Verbalized Sampling — Jiayi Zhang and colleagues](https://arxiv.org/html/2510.01171v4), original 2025; v4 July 2026 | Asking for several responses and associated probabilities increased diversity in the tested tasks; reported creative-writing gains were approximately 1.6–2.1×. This is not a recommendation-quality multiplier. Verbalized probabilities describe model output likelihoods imperfectly; they are not calibrated probabilities that a person will enjoy an item. |
| [String Seed of Thought — Kou Misaki and Takuya Akiba](https://arxiv.org/html/2510.21150v3), original October 2025; v3 February 2026; [Sakana article](https://pub.sakana.ai/ssot/) April 2026 | The method has the model produce a string and derive its answer from that string. It improved probability following and diversity in tested settings. Internal strings outperformed external-randomness baselines overall in the DeepSeek-R1 NoveltyBench comparison, but not in Product Recommendations; tool failures complicate interpretation. Neither method is established as universally better for recommendations. A prompt perturbation is not a statistical sampling guarantee. |
| [Forcing Diffuse Distributions — Yiming Zhang and colleagues](https://arxiv.org/html/2404.10859v2), v2 August 2024 | Distribution-matching fine-tuning increased coverage and entropy in three open instruction-tuned models, with some task generalization. This changes model parameters, unlike our request-scoped scoring weights. The method assumes valid target sequences or a representative sample; the authors limit direct applicability to unrestricted open-ended generation. It motivates measuring candidate coverage, not claiming that a skill prompt implements the training intervention. |
| [Large Language Models Are Bad Dice Players — Minda Zhao and colleagues](https://arxiv.org/html/2601.05414v3), v3 April 2026 | Across eleven models and fifteen specified distributions, ten models passed none of the distribution tests under 1,000 stateless requests per condition. These are distribution-fidelity failures under independent requests, not proof of statistically dependent outputs. The findings are empirical, not an impossibility theorem. Code-based sampling is appropriate when a specified distribution matters. |
| [Instruction-Tuned Language Models Cannot Sample from Distributions They Can Describe — Chaemin Jang and colleagues](https://arxiv.org/html/2607.25292v3), v3 October 2026 | Matched comparisons in three 7–8B model families found instruction tuning worsened mean sampling fidelity; base models also failed some targets. Distribution description and prompt perturbations improved tested survey estimates, but cannot introduce options absent from the model's prior. These results do not establish that repeated calls, higher temperature, or a recommendation persona recover a desired recommendation distribution. |
| [The Basic B*** Effect — Sandra C. Matz and colleagues](https://arxiv.org/pdf/2509.02910v2), v2 August 2026 | Study 1 counterfactually reselected among historical Facebook choices from 1,000 users; it did not observe long-term agent exposure. Study 2 involved 348 participants and 12,097 choices. Its full results distinguish dimensions: personalized agents could increase interpersonal distinctiveness relative to human choices while reducing psychological diversity; topical diversity was unchanged. Generic agents were less distinctive but more diverse in that comparison. The abstract compresses these patterns; a universal claim that both outcomes always decline is unwarranted. |

## Engineering choices to test

The central distinction is between **producing a candidate pool** and **choosing from that pool**. Randomizing weights cannot recover an option that the generator never proposes.

1. **Broaden generation before ranking.** The `explore` stage prepares different proposal briefs before the host researches candidates. Connected surprise varies approaches around evidenced interests or a concrete current goal, with limited adjacent exploration. Modes that allow distant exploration also draw from an explicit domain registry with external randomness. This is inspired by distributional elicitation and prompt perturbation, rather than a claim that it exactly reproduces either paper's protocol. A registry itself is a design choice with incomplete coverage.
2. **Use tools for the draws.** Keep the existing seeded weighting plans and use code for domain, brief, and selection randomness. Record the eligible pool, seed, and relevant inputs. A reproducible draw is conditional on those inputs and the implementation; it does not make generated candidates independent or guarantee identical web results.
3. **Separate quality from exploration.** The `select` stage applies verification and explicit user constraints before combining the batch's weighted scores with creator/topic diversity heuristics and history deduplication. Connected surprise additionally requires relevance at least 3/5 and a concrete personal connection; novelty cannot compensate for failing either check. Credibility, duration, language, exclusions, and fixed-weight instructions do not become random variables. Heuristic diversity penalties are not a trained model of enjoyment.
4. **Keep proposal annotations provisional.** Optional model likelihood annotations are uncalibrated elicitation aids. They are not used as enjoyment probabilities, evidence of a person's preferences, or a substitute for source verification. Generating five near-duplicates does not meet the purpose of producing different proposals.
5. **Audit realized outputs.** The `audit` stage reports coverage, concentration, and repeats. These describe the labeled works in the supplied data. Topic/creator concentration is not a measurement of psychological identity, and its decline is not automatically beneficial.

The model should preserve explicitly stated unusual interests rather than smoothing them toward a generic profile. A person can choose familiar material, request surprise, reject an experiment, or keep fixed weights. A generated recommendation, completion, or absent reply does not itself teach the taste model. Avoid inferring sensitive identity traits to optimize distinctiveness.

Fine-tuning the underlying language model is outside the current skill's scope. If a future deployment owns its generator and has suitable training targets, distribution-matching methods can be evaluated separately.

The [graph and exploration research review](GRAPH_RESEARCH.md) covers the additional sourced-content graph, explicit open exploration, and gradual evidence-based learning. Graph paths retrieve possible connections; they do not propagate preferences or expertise. Exposure remains separate from personal evidence. Those additions use local bounded heuristics and do not implement a trained graph recommender or contextual bandit.

The `connected_surprise_v1` policy is an experimental skill revision. Its 75/25 established-interest/adjacent research mix and minimum-fit checks are engineering defaults, not findings from these papers or validated optimal values. The former surprise preset that prioritized distant exploration is now an explicitly requested `wildcard` mode and is excluded from automatic rotation. Executing the policy does not establish that people prefer its recommendations; that requires a fresh comparison.

## Evaluation that can distinguish the mechanisms

Compare four candidate-generation conditions using the same anonymous profiles, constraints, host/model, research access, and approximately matched research/token budgets:

| Condition | Candidate generation |
| --- | --- |
| Direct | Ask for the requested final selection directly. |
| List-five | Ask for five candidate proposals, then apply the same verification and selection procedure. |
| VS-style | Elicit five distinct proposals with model likelihood annotations, then use the same verification and selection procedure. Label this adaptation rather than an exact replication. |
| Seeded varied generation | Use five varied briefs, anchored or registry-based according to the retained mode, then the same verification and selection procedure. |

Use the same final selection size. Record actual calls, token use where available, research effort, seeds, accessible sources, and failures. Keep the quality floor and selection procedure constant when testing generation; test selection heuristics separately on a shared candidate pool. Several seeds and prompts are needed to characterize repeated behavior.

Report factual identity/link verification, constraint compliance, and duplicate rates before subjective judgments. Then review relevance, depth, surprise, and useful variety, preferably with randomized presentation order and human feedback. Track two different outcomes:

- **Within a person over batches:** work/creator/topic coverage, concentration, repeated items, and whether discoveries earn explicit positive feedback.
- **Across different profiles:** overlap in candidate pools and final selections, while checking that genuine shared interests still receive good recommendations.

These are operational proxies, not replicas of the Basic B*** Effect's psychological measures. Synthetic profiles cannot establish effects on real people's identities. Higher entropy alone is not the objective: an irrelevant, unreliable, or unwanted selection can be diverse and still be poor.

Use isolated synthetic fixtures and observable checks when comparing behavior. No “2× enjoyment,” calibrated probability, or cure for homogenization is claimed by this implementation.

## Derived understanding and freshness

Hindsight's distinction between [evidence-grounded observations](https://hindsight.vectorize.io/developer/observations), persistent answers to selected questions in [mental models](https://hindsight.vectorize.io/developer/mental-models), and [retrieval followed by interpretation](https://hindsight.vectorize.io/developer/reflect) informed the curator's brief. Its documented stale-observation checks motivate verifying a derived understanding against changed evidence.

Trurl applies these principles through a short private summary, explicit source references and local freshness checks. The underlying profile and raw feedback remain authoritative. The request plan and randomized research directions are separate artifacts; a maintained taste summary does not change scoring weights or grant source access. No Hindsight dependency, service, training process or automatic conversation ingestion is required.

This is an engineering design choice, not evidence that memory benchmark performance transfers to recommendation enjoyment. Compare human appeal, useful variety, novelty and response to correction at matched research ceilings. Separate willingness to try from experienced enjoyment, treat unrated entries as missing, retain blinding/reveal timing and avoid comparing raw topic counts across inconsistent labels. See the [brief workflow](../skills/trurl/references/curators-brief.md).
