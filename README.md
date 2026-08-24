# HealthBench-Psych

An expert-adjudicated **mental-health subset of [HealthBench](https://arxiv.org/abs/2505.08775)**
(OpenAI's open benchmark of 5,000 physician-rubric-graded health conversations), together with a
faithful evaluation harness and released results for 20 language models under a three-judge
panel. Maintained by [MindBench.ai](https://mindbench.ai).

**Released datasets**

| Subset | n | Definition |
|---|---|---|
| `healthbench-psych-v1` | 610 | Mental-health-relevant HealthBench conversations, selected by LLM screening and two rounds of blinded review by three clinical mental-health experts (≥2/3 majority; concealed known-exclude controls in every round) |
| `healthbench-psych-hard-v1` | 119 | Intersection of v1 with OpenAI's HealthBench-Hard release |

Subset files contain HealthBench `prompt_id` lists plus construction provenance and a content
hash; the conversations themselves ship with HealthBench (see *Reproducing*, below). The
released run data (responses and grades) is hosted on the
[Hugging Face dataset](https://huggingface.co/datasets/mindbench-ai/healthbench-psych);
`eval/fetch_runs.py` rebuilds the local store from it.

## Repository layout

| Path | Contents |
|---|---|
| `eval/` | The evaluation harness: entry points (`generate.py`, `grade.py`, `grade_sync.py`, `aggregate.py`, `run_sweep.sh`), shared libraries (`lib/`), provider batch backends (`backends/`), the vendored HealthBench grader (`vendor/`), subset definitions (`subsets/`), and the run store (`runs/`; populated by `fetch_runs.py`) |
| `eval/runs/responses/` | One response per (model, conversation): 20 models × 610, full text, refusals retained with their API stop reason. Hosted on Hugging Face; rebuilt by `eval/fetch_runs.py` |
| `eval/runs/grades/` | Per-rubric-criterion verdicts and per-conversation scores for every (model, conversation, judge); judge free-text explanations omitted for size. Hosted on Hugging Face; rebuilt by `eval/fetch_runs.py` |
| `analysis/` | `visualization/`: figure generation from the released data; `statistics/`: the paper's quantitative analyses (runs key-less) |
| `provenance/` | How the dataset was built: screening and recovery rubrics (`rubrics/`), full-corpus screening outputs (`screening/`), the blinded review instruments plus de-identified expert ratings (`review/`), and the HealthBench-Hard parity run backing the harness-validation result (`harness-validation/`) |

## Quickstart: analyze the released results (no API keys needed)

```bash
git clone https://github.com/mindbench-ai/healthbench-psych.git && cd healthbench-psych
python3 eval/fetch_runs.py                                     # one-time ~45 MB download
python3 eval/aggregate.py --subset healthbench-psych-v1        # 20-model × 3-judge matrix,
python3 eval/aggregate.py --subset healthbench-psych-hard-v1   # agreement, severity stats
pip install matplotlib
python3 analysis/visualization/make_panel_fig.py --subset healthbench-psych-v1 --orient landscape
```

## Reproducing or extending the evaluation

Model generation and grading require the HealthBench corpus (not redistributed here) and
provider API keys:

```bash
curl -o source/hb_oss.jsonl \
  https://openaipublic.blob.core.windows.net/simple-evals/healthbench/2025-05-07-06-14-12_oss_eval.jsonl
export OPENAI_API_KEY=... ANTHROPIC_API_KEY=... GOOGLE_API_KEY=...   # per provider
bash eval/run_sweep.sh gen   healthbench-psych-v1     # candidate responses (per-provider processes)
bash eval/run_sweep.sh grade healthbench-psych-v1     # judge panel (batch APIs)
```

Everything is prompt-keyed and idempotent: re-runs resume, and grading a new model or judge
touches only the missing cells. Grading reuses the HealthBench grader verbatim (template, system
message, token limits) with one documented deviation: judges run at temperature 0 rather than
0.5, for deterministic verdicts. Costs are bounded by `--max-cost` flags; the full 20-model,
3-judge run cost ≈ $560 in mid-2026.

## Platform export

`platform/export_platform_artifacts.py` converts the grades store (populated by `eval/fetch_runs.py`) into the
versioned artifacts the [MindBench platform](https://mindbench.ai) ingests: one
`mindbench-results.v1` payload per candidate model, carrying the three-judge panel mean on
`healthbench-psych-v1`, the hard-subset panel mean, and the per-judge scores behind both.
No API keys are needed; everything is recomputed from the fetched `eval/runs/grades/`.

```bash
python3 platform/export_platform_artifacts.py     # -> platform/out/healthbench-psych--<model>.json
                                                  #    (20 files + export-manifest.json, gitignored)
```

Each payload is validated against `platform/schemas/mindbench-results.v1.schema.json`
before it is written. That file is a vendored, byte-identical copy of the authoritative
schema in `mindbench-platform/packages/artifact-schemas/schemas/`. The platform's copy is
authoritative; to sync, re-copy the file verbatim. `export-manifest.json` records
`generated_at`, the producing repo + commit, and the sha256 of every payload.

## Dataset construction (summary)

The subset was built with a screen–review–recover loop: an LLM screen over all 5,000
conversations under a released rubric; blinded review by three licensed clinicians with concealed
known-exclude controls interleaved (the control-inclusion rate measures the screen's miss rate
and triggers recall rounds); and a clinician-informed recovery screen over the excluded pool.
The loop terminated when controls indicated the included set was comprehensive. All rubrics,
screening outputs, instruments, and de-identified ratings are in `provenance/`; the accompanying
paper documents the procedure and its validation.

## Use of AI assistance

Following ACL guidance on generative tools: this study and codebase were designed, scoped, and
organized by the MindBench team; Claude Code (Anthropic) was used to assist in constructing much
of the implementation, and all code was reviewed by the engineering team. LLMs are also part of
the dataset methodology: the screening and recovery passes were executed by Claude models under
the released rubrics, orchestrated through Claude Code as a fan-out harness, as documented in
`provenance/` and the paper. That harness layer adds proprietary system prompts outside our
control, one reason the screen is treated strictly as a pre-filter: all inclusion decisions were
finalized by the clinician review process, never the screen alone.

## Attribution and citation

HealthBench is by OpenAI ([paper](https://arxiv.org/abs/2505.08775)); `eval/vendor/healthbench_eval.py`
is reproduced from [openai/simple-evals](https://github.com/openai/simple-evals) (MIT) and the
grading logic in this harness is verbatim from it. If you use HealthBench-Psych, please cite
both HealthBench and:

```bibtex
[CITATION: to be added on publication]
```

## License

MIT (see `LICENSE`). Vendored and redistributed HealthBench materials remain under OpenAI's
MIT terms; see `THIRD-PARTY-NOTICES.md`.
