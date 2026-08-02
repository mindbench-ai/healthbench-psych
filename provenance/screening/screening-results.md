# HealthBench Psychiatry — Screening Results (v0.1)

Automated screening of the HealthBench OSS corpus (`2025-05-07-06-14-12_oss_eval.jsonl`, 5,000 examples) against [the screening rubric](healthbench-psychiatry-screening-rubric.md), v0.1. Each example was classified by an independent LLM agent; the corpus was processed in 100 batches of 50, with a one-at-a-time re-screen for stragglers.

## Coverage
- **5,000 / 5,000** examples labelled.
- **1** example (`98462c2f-e709-4681-8f43-764c49686f3b`) could not be auto-screened: the model returned a usage-policy refusal even for benign topic-tagging. It is labelled **BORDERLINE** with `needs_human_review = true` and a `model_refused` provenance flag, pending mandatory human review.

## Label distribution
| Label | n | % |
|---|---|---|
| RELEVANT | 378 | 7.6% |
| BORDERLINE | 263 | 5.3% |
| NOT_RELEVANT | 4359 | 87.2% |

Screening confidence: high 4429, medium 407, low 164.

Candidate eval subset sizes: **RELEVANT only = 378**; **RELEVANT + BORDERLINE = 641**.

## RELEVANT by category
| Category | n |
|---|---|
| perinatal_mh | 107 |
| mood_depression_bipolar | 63 |
| anxiety | 47 |
| psychiatric_medication | 45 |
| neurodevelopmental_adhd | 44 |
| suicidality_self_harm | 17 |
| substance_use | 14 |
| psychotherapy_access | 9 |
| trauma_ptsd | 6 |
| eating_disorder | 6 |
| stress_adjustment | 6 |
| other_mh | 5 |
| psychosis | 5 |
| personality | 3 |
| sleep | 1 |

## BORDERLINE by category (routed to human review)
| Category | n |
|---|---|
| cognitive_neuro | 55 |
| sleep | 54 |
| anxiety | 52 |
| stress_adjustment | 31 |
| substance_use | 20 |
| other_mh | 14 |
| perinatal_mh | 9 |
| psychiatric_medication | 8 |
| suicidality_self_harm | 6 |
| mood_depression_bipolar | 5 |
| neurodevelopmental_adhd | 5 |
| eating_disorder | 2 |
| psychotherapy_access | 2 |

## Known composition caveats
- **Perinatal mental health is the single largest RELEVANT category (107 of 378, 28%)**, an artefact of HealthBench's heavy pregnancy / global-health content. A naive RELEVANT-only slice is perinatal-weighted; decide at finalisation whether to keep, cap, or stratify.
- BORDERLINE is dominated by cognitive/neuro, sleep, and non-specific stress/anxiety — the ambiguous somatic-overlay cases the rubric deliberately defers to human reviewers.

## Artefacts
- `healthbench_psych_labels.jsonl` — full 5,000-row labelled set (`prompt_id, label, category, confidence, rationale`).
- Reconciliation pass (clinician + lived-experience review of all BORDERLINE and a stratified RELEVANT/NOT_RELEVANT sample) is pending per the rubric.

*Screening run: HealthBench OSS corpus dated 2025-05-07; rubric v0.1.*
