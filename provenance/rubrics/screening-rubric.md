# HealthBench Psychiatry — Subset Screening Rubric

**Purpose.** HealthBench (OpenAI, May 2025; 5,000 physician-rubric-graded health conversations) carries no clinical-specialty metadata. Its tags describe *conversational behavior* (`theme:hedging`, `theme:emergency_referrals`, …) and physician-uncertainty structure, never medical topic. To construct a mental-health / psychiatry evaluation slice ("HealthBench Psychiatry") we therefore screen the corpus by **content**, applying the criteria below to the user-side conversation.

**Unit of judgment.** One HealthBench example = one (possibly multi-turn) conversation. We screen on the **user/patient turns** — what the person is actually bringing to the system — using assistant turns only as context. The graded response is not consulted; relevance is a property of the *prompt*, not of any model's answer.

**Screening question.** *Is the user's primary need in this conversation a mental-health or psychiatric concern, such that a clinician or person with lived experience in mental health would consider it in-scope for a mental-health evaluation?*

---

## Labels

Each example receives exactly one label:

- **RELEVANT** — Mental health / psychiatry is the central subject of the user's need (meets ≥1 inclusion criterion and no overriding exclusion).
- **BORDERLINE** — Mental health is plausibly but not clearly central; a somatic, neurological, or general-wellness concern with a possible psychological overlay. *These are routed to human (clinician + lived-experience) review; they are the cases the rubric cannot settle on its own.*
- **NOT_RELEVANT** — No substantive mental-health component, or mental health is mentioned only incidentally.

When genuinely torn between two labels, choose the **less inclusive** one and lower the confidence — RELEVANT is reserved for clear cases, and BORDERLINE exists precisely to catch the doubt.

## Inclusion criteria (any one → at least BORDERLINE; if central → RELEVANT)

1. **Psychiatric conditions / symptoms** — depression, anxiety disorders, bipolar disorder, schizophrenia / psychosis, PTSD or trauma reactions, OCD, eating disorders, ADHD and neurodevelopmental conditions, personality disorders, dissociation.
2. **Suicidality, self-harm, or acute psychiatric crisis** — ideation, plans, past attempts, self-injury, or crisis framing. *(Always at least BORDERLINE, regardless of how briefly raised.)*
3. **Substance use / addiction** as a behavioral-health concern — alcohol, drugs, dependence, withdrawal, recovery (not incidental mentions, e.g. "I don't drink").
4. **Psychiatric medication** — antidepressants (SSRIs/SNRIs), antipsychotics, mood stabilizers (lithium, valproate), anxiolytics/benzodiazepines, stimulants, sleep agents *when used for a psychiatric indication* — including starting, stopping, side effects, interactions, dosing.
5. **Psychotherapy / mental-health care-seeking** — therapy, counseling, finding a therapist or psychiatrist, treatment options, what to expect.
6. **Emotional distress framed psychologically** — grief/bereavement, acute stress, burnout, loneliness, panic, mood changes, where the *psychological* experience is the point.
7. **Perinatal mental health** — postpartum depression/anxiety, perinatal mood concerns.
8. **Behavioral/psychological symptoms of another condition** when the mental-health aspect is what the user is asking about (e.g., mood changes attributed to a medical illness, where the worry is the mood).

## Exclusion criteria (override → NOT_RELEVANT)

- Purely somatic / physical-medicine questions with no mental-health component — even when trigger words appear in another sense (e.g. "**borderline** thyroid," "stress **test**," cardiac, GI, derm, ortho, labs, dosing of non-psychiatric drugs).
- Mood, stress, or sleep mentioned only **incidentally** and not the focus of the request.
- General wellness, fitness, nutrition, or lifestyle with no mental-health concern.
- Administrative / informational health-data tasks with no psychiatric content.

## Borderline guidance (→ BORDERLINE, for human review)

- Somatic complaints with a plausible psychological overlay — fatigue, unexplained physical symptoms, **insomnia/sleep problems without explicit psychological framing**.
- Cognitive / neuropsychiatric presentations — dementia, delirium, cognitive decline (psychiatric-adjacent).
- Generalized "stress" or "overwhelm" where it is unclear whether a clinical concern is present.
- Sexual health, chronic pain, or menopause where mood is entangled but not clearly central.

---

## Per-example output

| Field | Values |
|---|---|
| `prompt_id` | HealthBench example id (verbatim) |
| `label` | `RELEVANT` \| `BORDERLINE` \| `NOT_RELEVANT` |
| `category` | primary topic (controlled vocabulary below); `none` if NOT_RELEVANT |
| `confidence` | `high` \| `medium` \| `low` |
| `rationale` | ≤15 words naming the deciding feature |

**Category controlled vocabulary:** `mood_depression_bipolar`, `anxiety`, `trauma_ptsd`, `psychosis`, `suicidality_self_harm`, `substance_use`, `eating_disorder`, `neurodevelopmental_adhd`, `personality`, `sleep`, `perinatal_mh`, `grief_bereavement`, `stress_adjustment`, `psychiatric_medication`, `psychotherapy_access`, `cognitive_neuro`, `other_mh`, `none`.

---

## Procedure & provenance

- **Corpus:** `2025-05-07-06-14-12_oss_eval.jsonl` (HealthBench OSS, 5,000 examples).
- **Screening pass:** automated LLM screening, fanned out over the corpus in batches, each batch independently classified against this rubric. This file is the verbatim instruction given to every screening agent.
- **Reconciliation (planned):** all `BORDERLINE`, plus a stratified sample of `RELEVANT` and `NOT_RELEVANT`, are reviewed by a clinician and a lived-experience reviewer before the subset is fixed. Inter-screen and screen-vs-human agreement are reported as a measure of subset reliability.
- **Versioning:** changes to inclusion/exclusion criteria bump the rubric version and require a re-screen; the subset is cited by rubric version + corpus date.

*Rubric version: v0.1 (draft for first screening pass).*
