# Harness validation (HealthBench-Hard parity run)

GPT-4.1 (`gpt-4.1-2025-04-14`) evaluated on the complete 1,000-conversation
HealthBench-Hard subset under this harness, generation and grading at temperature 0.5
to match the reference implementation. Clipped mean 0.157 vs the published 0.16.
`results.jsonl` holds per-conversation scores, model responses, and per-rubric verdicts
(judge explanations omitted, as in the main release); `manifest.json` pins the model
snapshots, parameters, grader-template hash, and corpus/subset hashes. Recomputed by
`analysis/statistics/healthbench_psych_v1_analysis.py`. Reproducing from scratch
requires the HealthBench corpus (see the repository README).
