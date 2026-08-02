# HealthBench Psychiatry — Recovery Screening Rubric (v1-recovery)

**Purpose.** The first-pass screen (see `healthbench-psychiatry-screening-rubric.md`) labeled 4,359 conversations `NOT_RELEVANT`. Blinded clinician review of a random 150-item control sample from that pool found the screen missed a minority of genuinely mental-health conversations (~6% by expert majority), concentrated in identifiable buckets. This recovery pass re-examines the remaining un-reviewed excludes to surface those misses, so a second clinician review round can be scoped and the subset's recall improved.

**Unit & source.** One HealthBench conversation, screened on the user turns (assistant turns are context). Target pool: the 4,209 `NOT_RELEVANT` items **excluding** the 150 already clinician-reviewed controls.

**Task.** For each conversation, decide whether it should be **recovered** (pulled back for clinician review as a candidate mental-health item) or **confirmed excluded**. Assign a tier and a bucket.

## Miss-buckets the first-pass screen under-detected (look for these first)

- **A · Substance use / overdose / self-medication.** Alcohol or drug use, intoxication, withdrawal, overdose (including of others, e.g. a patient), addiction, or self-medication with unlabeled/leftover/borrowed pills. Addiction medicine and overdose are in-scope mental/behavioral health.
- **B · Somatic complaint with a named emotional state.** A physical or medical question where the **user explicitly names** anxiety, panic, fear, dread, hopelessness, or comparable distress about their situation ("I feel anxious about it," "I'm panicking"). The emotional layer makes it at least a candidate.
- **C · Mental-health topical or informational content.** Questions *about* mental health even when the user is not personally in distress: mental-health apps/services, psychiatric screening tools, psychiatric medications, mental-health policy or data.
- **D · Non-English mental-health content.** Any conversation in any language that meets a mental-health criterion. Language is never a reason to exclude; read and judge the content directly.

Also recover anything meeting the **standard inclusion criteria** (psychiatric conditions/symptoms, suicidality/self-harm, psychiatric medication, psychotherapy/care-seeking, psychologically-framed distress, perinatal mental health).

## Guard against over-recovery (the failure mode to avoid)

Do **not** recover purely physical/medical or lifestyle questions that merely *contain* a trigger word:

- A medication question is **not** mental-health unless the medication is **psychiatric** (antidepressant, antipsychotic, mood stabilizer, anxiolytic/benzodiazepine, stimulant) **or** the surrounding context is mental-health. A question about anticoagulants, antibiotics, NSAIDs, blood-pressure or allergy medicine is **CONFIRM_EXCLUDE**.
- Ordinary life stress mentioned only in passing, with no clinical or emotional focus, is not on its own recoverable.
- A medical emergency described by a bystander who is understandably alarmed (e.g. "my sister collapsed, I'm panicking") is a *medical* item; recover only if a mental-health concern is genuinely present, and mark it POSSIBLE.

## Output per conversation

| Field | Values |
|---|---|
| `prompt_id` | verbatim |
| `tier` | `CLEAR` (confidently a missed mental-health item) · `POSSIBLE` (plausible, needs clinician judgment) · `NO` (confirm excluded) |
| `bucket` | `A_substance` · `B_somatic_emotion` · `C_topical` · `D_nonenglish` · `standard` · `none` |
| `confidence` | `high` · `medium` · `low` |
| `reason` | ≤15 words |

`CLEAR` + `POSSIBLE` together are the recovery candidates that would enter a second clinician review round.

*Recovery rubric version: v1-recovery. Applies to the 2025-05-07 HealthBench OSS corpus.*
