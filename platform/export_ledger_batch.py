#!/usr/bin/env python3
"""Export a HealthBench-Psych release as generation-batch.v1 BATCHES for the
platform's generation ledger.

Sibling of `export_platform_artifacts.py`, and the other direction of the same
seam: that script ships AGGREGATES (`mindbench-results.v1`, one panel mean per
candidate model). This one ships the PER-CALL EVIDENCE those means were
computed from -- every candidate response, every rubric-item verdict -- as rows
in the ledger.

RELEASES ARE SEPARATE BATCHES. `versioning.md` (the release plan, in the dev
checkout) keys the benchmark's identity to `prompt_id_sha256`, the hash of the
subset's prompt-id list, and fixes v1.0.0 by its tag:
610 prompts, 20 candidate models, a 3-judge panel. The three new models of the
additive 1.x line are a DIFFERENT release and ship as their own batch, so a
reader of the ledger can ask for the frozen state and get exactly the state the
manuscript reports.

    --release v1.0.0   the frozen state: the 20 published models, byte-faithful
                       to the thin store under eval/runs/
    --release v1.1.0   the additive line: gemini-3.8-flash and claude-fable-5-1,
                       from the ledger-shaped store in the dev checkout

v1.0.0 IS A PHOTOGRAPH, NOT A REPAIR. None of the pending fixes in the release
ladder is applied here:

  * the 222,890 trailing whitespace characters on one `gemini-2.5-flash`
    response are exported as stored (that fix is release 1.1.1, not yet made);
  * no length-adjusted score is computed or carried (release 1.3.0);
  * `stop_reason` is sparse -- populated on 2,306 of the 12,200 published rows
    -- and stays sparse (release 1.0.1 documents the gap, it does not fill it);
  * the unenforced 8,192-token cap is not asserted on rows that never recorded
    a parameter.

The round-2 control item (`140c95dc...`) is not here: the
subset is exactly 610 ids, and admitting the control is the 2.0.0 boundary.

ABSENT IS NOT NULL. The 20 published models were run through a THIN store --
`{prompt_id, response_text, [stop_reason]}` -- which never recorded model
parameters, token usage, latency, cost or a provider response id. Those fields
are therefore OMITTED from a v1.0.0 row rather than written as null: the row
contract distinguishes a field nobody sought from a value that came back empty,
and versioning.md asks for exactly that distinction. `finish_reason` is the one
field the store DOES declare (store.py's own docstring lists it as the optional
third field), so it is carried as null where the store has no value and as the
recorded value where it does. The v1.1.0 rows carry every field their
ledger-shaped source holds.

OUTPUT -- a NEW directory per run key; nothing else under platform/out/ is
touched. Generations and grades are separate run keys, so they are separate
manifests (a generation-batch.v1 manifest names exactly one run_key):

    platform/out/ledger/healthbench-psych/v1.0.0/generations/
        manifest.json  generations.jsonl
    platform/out/ledger/healthbench-psych/v1.0.0/grades/
        manifest.json  assessments.jsonl
    platform/out/ledger/healthbench-psych/v1.1.0/{generations,grades}/...

Register the INSTRUMENT first (platform/export_ledger_instrument.py, then
scripts/import/instrument.ts --promote): every verdict here names
`external-evals/rubric_item@v1.0.0`, and the platform refuses a batch that
names an instrument it does not hold.

Then ingest generations BEFORE grades: a verdict names the generation it
judged, and the two live in different runs, so each assessment carries
`subject.run_key` pointing back at the generations run.

    npx tsx server/scripts/import/generation-batch.ts \\
        <dir>/manifest.json --producer mindbench-ai/healthbench-psych

WHAT MAPS TO WHAT (the platform's seam note,
mindbench-platform/docs/spokes/ledger-ingest-healthbench-external-evals.md,
is the contract):

  responses/<model>.jsonl row    -> one `target` generation, key <model>/<prompt_id>
  grades/<cand>__<judge>.jsonl
    row.grades[i]                -> one assessment, key <cand>/<prompt_id>/<i>/<judge>

PROMPTS ARE NOT OURS TO SHIP. HealthBench is OpenAI's corpus. Every generation
row carries `prompt_ref: hb:<prompt_id>` and NO prompt text -- a pointer into
the corpus, which is what prompt_ref is for. Rubric CRITERION TEXT is likewise
never exported HERE; a verdict carries the item's KEY and its points, which are
what the row contract asks it to carry. The criterion's text, ordinal and TAGS
are instrument facts, not verdict facts, and live on the instrument version
export_ledger_instrument.py registers -- stated once there, not on 464,000
rows. (That instrument keeps the text inline under `visibility: restricted`,
which is the platform's egress gate; it is still never published.)

ROW HYGIENE. A verdict row's `extra` carries only facts true of that ONE
verdict. Run-level facts (release, grader template, producer commits, harness
versions, dataset checksums) belong on the manifest; instrument-level facts (a
criterion's tags, its text, its points beyond `item_points`) belong on the
instrument version. Ignoring this cost 312 bytes of `extra` on every one of
this benchmark's 464,000 verdict rows, of an average 786.

RUBRIC ITEMS HAVE NO STABLE KEY. hb_oss.jsonl stores them as a positional
array, so `item_key` is minted from the position: `hb:<prompt_id>#<i>`. The
grade store's `grades[]` is positional against the same array; this exporter
verifies the two lengths agree for every row it exports and refuses otherwise,
because a silently misaligned verdict is worse than no verdict.

THE INSTRUMENT IS NAMED, NOT DESCRIBED. `platform/export_ledger_instrument.py`
registers the v1.0.0 rubric as an `instrument.v1` under
`external-evals/rubric_item@v1.0.0` -- the eval is conceptually the external
OpenAI HealthBench one, the 610-prompt subset is ours -- so every verdict now
states that triple plus its `item_key`, and `instrumentRefs.instrumentFor`
resolves it to a real `instrument_version_id` on the row. That triple used to
travel once in the manifest's `protocol` as a free-text `instrument_ref`,
because naming an instrument the platform did not hold would have refused the
whole batch; the instrument exists now, so the row names it and the manifest
does not repeat it. The criterion's ORDINAL, TEXT and TAGS are instrument-level
facts and live there only -- the row keeps `item_key` (identity) and
`item_points` (copied at write time so a score recomputes without a join).
Register the instrument BEFORE ingesting a grades batch.

TIMESTAMPS. The thin store records no per-row timestamp. The spend ledger
(`eval/runs/spend.jsonl`) does record, per model and per judge, when each pass
ran, and the subset file names the 14 prompts that round 2 added -- so a row's
time is attributed at the resolution the evidence actually supports:

  generated_at  v1.0.0: the model's FIRST `generate` spend entry for a round-1
                prompt, its LAST for one of the 14 round-2 prompts.
                v1.1.0: the ledger row's own `generated_at`, per row, exact.
  assessed_at   the judge's last `grade` spend entry in the pass that graded
                that prompt (round 1, round 2, or the 2026-09 pass for the new
                models). Per (judge, pass) -- the spend ledger names the judge,
                never the candidate, so no finer split is available.

DETERMINISTIC AND IDEMPOTENT: rows are emitted in a fixed order (model, then
prompt id in subset order; for verdicts, candidate, prompt, rubric position,
judge), every row's key order is fixed in code, JSON is written compactly, and
every input is a file on disk -- so a re-run writes byte-identical parts and the
platform dedupes the manifest on content hash instead of superseding a run with
itself.

Usage:
  python3 platform/export_ledger_batch.py --release v1.0.0 [--dry-run]
  python3 platform/export_ledger_batch.py --release v1.1.0 [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

RELEASE_ROOT = Path(__file__).resolve().parent.parent
DEV_ROOT = RELEASE_ROOT.parent / "healthbench-psych-dev"

sys.path.insert(0, str(RELEASE_ROOT / "eval"))
from lib import samplers as S  # noqa: E402

PRODUCER_REPO = "mindbench-ai/healthbench-psych"

# The registered instrument every verdict below is cast against, written by
# platform/export_ledger_instrument.py and resolved by the platform into an
# `instrument_version_id` on each row. The triple must match that exporter's
# exactly: `instrumentRefs.instrumentFor` REFUSES a named instrument the
# platform does not hold, so a typo here refuses the whole batch rather than
# quietly writing unattached verdicts.
INSTRUMENT_PROJECT_SLUG = "external-evals"
INSTRUMENT_KIND = "rubric_item"
INSTRUMENT_VERSION = "v1.0.0"

SUBSET_NAME = "healthbench-psych-v1"
SUBSET_FILE = RELEASE_ROOT / "eval" / "subsets" / f"{SUBSET_NAME}.json"
HB_SOURCE = RELEASE_ROOT / "source" / "hb_oss.jsonl"
RESP_DIR = RELEASE_ROOT / "eval" / "runs" / "responses"
GRADE_DIR = RELEASE_ROOT / "eval" / "runs" / "grades"
SPEND_LOG = RELEASE_ROOT / "eval" / "runs" / "spend.jsonl"
LEDGER_DIR = DEV_ROOT / "generation-ledger"
OUT_ROOT = RELEASE_ROOT / "platform" / "out" / "ledger"

# The ledger keeps these rows at the tier the run data already sits at: real
# model output on mental-health conversations, against a corpus we may point at
# but not redistribute.
DATA_TIER = "restricted"
CELL_KEY = SUBSET_NAME

# The panel, named by the harness itself rather than restated here.
JUDGES = sorted(S.JUDGES)

# The grader, as eval/lib/hb_grade.py records its own provenance: GRADER_TEMPLATE
# copied verbatim from the vendored copy of openai/simple-evals.
GRADER_TEMPLATE_ID = "healthbench-GRADER_TEMPLATE@b763d8c1f53ecd16"
GRADER_NOTE = (
    "HealthBench GRADER_TEMPLATE reproduced verbatim from openai/simple-evals "
    "(eval/vendor/healthbench_eval.py, vendored 2026-07-28, sha256 prefix "
    "b763d8c1f53ecd16), with one documented deviation: judges run at "
    "temperature 0 rather than 0.5, for deterministic verdicts."
)

# The frozen release's 20 candidates ARE the harness's registry -- there is no
# second list to drift from it. The 1.x models are not in it (they were run
# through generate_ledger.py in the dev checkout), which is why they are named
# here.
PUBLISHED_MODELS = sorted(S.REGISTRY)
NEW_MODELS = ["claude-fable-5-1", "gemini-3.8-flash", "gpt-6-astra"]

RELEASES = {
    "v1.0.0": {
        "models": PUBLISHED_MODELS,
        "source": "thin",
        "note": "v1.0.0, the state the preprint describes: 610 prompts, 20 candidate models, 3-judge panel",
    },
    "v1.1.0": {
        "models": NEW_MODELS,
        "source": "ledger",
        "note": "additive 1.x line: three new candidate models on the unchanged v1.0.0 subset",
    },
}

# Round 1 graded before round 2 existed; the 2026-09 pass graded the new models.
# A grade spend entry names the judge and the wall-clock, never the candidate,
# so a pass is identified by its window.
GRADE_PASSES = {
    "round1": ("2026-07-30", "2026-07-31T12:00"),
    "round2": ("2026-07-31T12:00", "2026-08-01"),
    "new-models": ("2026-09-01", "2026-10-01"),
}


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------

def git_commit(root: Path) -> str | None:
    """The checkout's HEAD, or None. Same never-raises posture as
    export_platform_artifacts.py's: a checkout without git is a missing
    provenance field, not a failed export."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None


def load_subset() -> dict:
    """The subset file, with its own hash re-derived and checked.

    The identity check that matters happens later, over the ids actually
    exported; this one catches a subset file whose recorded hash no longer
    describes its own id list."""
    meta = json.loads(SUBSET_FILE.read_text(encoding="utf-8"))
    recomputed = prompt_id_sha256(meta["prompt_ids"])
    if recomputed != meta["prompt_id_sha256"]:
        raise SystemExit(
            f"{SUBSET_FILE.name}: recorded prompt_id_sha256 "
            f"{meta['prompt_id_sha256'][:16]}... does not describe its own "
            f"prompt_ids ({recomputed[:16]}...) -- the subset file is inconsistent"
        )
    return meta


def prompt_id_sha256(prompt_ids) -> str:
    """The benchmark's identity, as versioning.md defines it: sha256 over the
    JSON of the SORTED prompt-id list. Recomputed here from the ids being
    exported so an export whose membership drifted cannot claim the frozen
    hash."""
    return hashlib.sha256(json.dumps(sorted(prompt_ids)).encode("utf-8")).hexdigest()


def load_rubrics(prompt_ids: set[str]) -> dict[str, list[dict]]:
    """prompt_id -> the corpus's positional rubric array, for the subset only.

    Criterion TEXT is read but never exported by THIS script: a verdict needs
    the item's key and its points, and the text lives on the instrument version
    (platform/export_ledger_instrument.py) where it is stated once."""
    if not HB_SOURCE.exists():
        raise SystemExit(
            f"{HB_SOURCE} is missing -- rubric points come from the HealthBench "
            f"corpus; see the README's 'Reproducing' section for the download"
        )
    rubrics: dict[str, list[dict]] = {}
    with HB_SOURCE.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["prompt_id"] in prompt_ids:
                rubrics[row["prompt_id"]] = row["rubrics"]
    missing = prompt_ids - set(rubrics)
    if missing:
        raise SystemExit(
            f"{len(missing)} of the subset's prompts have no rubric in "
            f"{HB_SOURCE.name} -- refusing to export verdicts whose items are unknown"
        )
    return rubrics


def spend_times() -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], str]]:
    """When each pass ran, from the harness's own append-only spend ledger.

    Returns (generation window per model, last grade entry per (judge, pass)).
    This is the only per-run wall-clock the published store leaves behind."""
    gen: dict[str, list[str]] = {}
    grade: dict[tuple[str, str], list[str]] = {}
    with SPEND_LOG.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            ts, who = rec["ts"], rec.get("who")
            if not who:
                continue
            if rec.get("phase") == "generate":
                gen.setdefault(who, []).append(ts)
            elif rec.get("phase") == "grade":
                for name, (lo, hi) in GRADE_PASSES.items():
                    if lo <= ts < hi:
                        grade.setdefault((who, name), []).append(ts)
    return (
        {m: (min(v), max(v)) for m, v in gen.items()},
        {k: max(v) for k, v in grade.items()},
    )


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def model_ref(label: str) -> dict:
    """A generation.v1 `model` block for a published candidate, from the
    harness's own registry -- the repo's single source of model identity.
    `api_model_id` is the string the sampler actually sends, which for every
    entry in this registry is the label itself; nothing is invented for a model
    the registry does not know, because every published model is in it."""
    sampler = S.REGISTRY[label]
    return {
        "label": label,
        "api_model_id": getattr(sampler, "id", label),
        "provider": S.provider_of(label),
    }


def status_of(stop_reason: str | None, text: str) -> str:
    """The row contract requires a status; the thin store records none. This
    derives one from what the store DOES hold, and from nothing else.

    All 13 empty responses in the published run carry `stop_reason: refusal`,
    so refusal alone accounts for them -- an empty body is never guessed at."""
    reason = (stop_reason or "").lower()
    if reason == "refusal":
        return "refusal"
    if reason in ("length", "max_tokens"):
        return "truncated"
    if not text.strip():
        return "empty"
    return "success"


def thin_generations(models, subset, rubric_ids, gen_window, dev_commit, hash_hex, stats):
    """The 20 published models, from `eval/runs/responses/<model>.jsonl`."""
    round2 = set(subset["round2_added_prompt_ids"])
    order = {pid: i for i, pid in enumerate(subset["prompt_ids"])}
    rows = []
    for label in models:
        path = RESP_DIR / f"{label}.jsonl"
        if not path.exists():
            raise SystemExit(f"{path} is missing -- run `python3 eval/fetch_runs.py` first")
        store = {}
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                store[rec["prompt_id"]] = rec
        extra_ids = set(store) - rubric_ids
        if extra_ids:
            raise SystemExit(
                f"{label}: {len(extra_ids)} stored prompt_id(s) are not in "
                f"{SUBSET_NAME} -- wrong provenance, refusing to export"
            )
        if set(store) != rubric_ids:
            raise SystemExit(
                f"{label}: {len(store)}/{len(rubric_ids)} prompts in the store -- "
                f"the frozen release is complete by definition, refusing a partial export"
            )
        for pid in sorted(store, key=order.__getitem__):
            rec = store[pid]
            text = rec["response_text"]
            in_round2 = pid in round2
            first, last = gen_window[label]
            meta = {
                "release": "v1.0.0",
                "subset": SUBSET_NAME,
                "prompt_id_sha256": hash_hex,
                "spoke_dev_commit": dev_commit,
                "source": f"eval/runs/responses/{label}.jsonl",
                "round": 2 if in_round2 else 1,
                "generated_at_basis": (
                    "eval/runs/spend.jsonl: the model's "
                    + ("last" if in_round2 else "first")
                    + " generate entry"
                ),
            }
            # A store row carrying a `correction` says a value in it was
            # backfilled after the fact; that is provenance about the row and
            # travels with it rather than being dropped.
            if rec.get("correction") is not None:
                meta["correction"] = rec["correction"]
            stats["status_" + status_of(rec.get("finish_reason", rec.get("stop_reason")), text)] += 1
            if rec.get("finish_reason", rec.get("stop_reason")) is not None:
                stats["finish_reason_present"] += 1
            rows.append({
                "key": f"{label}/{pid}",
                "purpose": "target",
                "status": status_of(rec.get("finish_reason", rec.get("stop_reason")), text),
                "cell_key": CELL_KEY,
                # The stimulus is OpenAI's: point at it, never ship it.
                "prompt_ref": f"hb:{pid}",
                "model": model_ref(label),
                # Declared by the store, sparse in it: carried where present,
                # null where the provider returned none. Not repaired.
                "finish_reason": rec.get("finish_reason", rec.get("stop_reason")),
                "generated_at": last if in_round2 else first,
                "data_tier": DATA_TIER,
                "response_text": text,
                "surface_meta": meta,
            })
            # params, usage, latency_ms, api_cost, provider_response_id and
            # system_fingerprint are ABSENT above, not null: this store never
            # sought them.
    return rows


def ledger_generations(models, subset, rubric_ids, dev_commit, hash_hex, stats):
    """The 1.x models, from `generation-ledger/gen-<model>.jsonl` in the dev
    checkout -- a full call record per row, exported with every field it has."""
    order = {pid: i for i, pid in enumerate(subset["prompt_ids"])}
    rows = []
    for label in models:
        path = LEDGER_DIR / f"gen-{label}.jsonl"
        if not path.exists():
            raise SystemExit(f"{path} is missing -- nothing to export for {label}")
        store = {}
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                store[rec["prompt_ref"].split(":", 1)[1]] = rec
        if set(store) - rubric_ids:
            raise SystemExit(
                f"{label}: prompt_refs outside {SUBSET_NAME} -- wrong provenance, "
                f"refusing to export"
            )
        if set(store) != rubric_ids:
            raise SystemExit(
                f"{label}: incomplete run ({len(store)}/{len(rubric_ids)} prompts) -- "
                f"refusing a partial export"
            )
        for pid in sorted(store, key=order.__getitem__):
            r = store[pid]
            stats["status_" + r["status"]] += 1
            params = {
                "temperature": r.get("temperature"),
                "top_p": r.get("top_p"),
                "max_tokens": r.get("max_tokens"),
                "seed": r.get("seed"),
                "reasoning_level": r.get("reasoning_level"),
                "requested": r.get("sampling_requested"),
                "reported": r.get("sampling_reported"),
                "extra": r.get("params_extra"),
            }
            # The contract's stop_sequences is an array of strings with no null
            # member; a run that set none says so by not having the field.
            if r.get("stop_sequences"):
                params["stop_sequences"] = r["stop_sequences"]
            rows.append({
                "key": f"{label}/{pid}",
                "purpose": r["purpose"],
                "status": r["status"],
                "cell_key": CELL_KEY,
                "prompt_ref": r["prompt_ref"],
                "prompt_sha256": r.get("prompt_sha256"),
                "system_prompt_sha256": r.get("system_prompt_sha256"),
                "model": {
                    "label": r["model_label"],
                    "api_model_id": r["requested_api_model_id"],
                    "provider": r.get("provider_slug"),
                    "served_model": r.get("served_model"),
                    "declared_provider": r.get("declared_provider"),
                },
                "params": params,
                "finish_reason": r.get("finish_reason"),
                "error_type": r.get("error_type"),
                "error_message": r.get("error_message"),
                "usage": {
                    "input_tokens": r.get("input_tokens"),
                    "output_tokens": r.get("output_tokens"),
                    "cached_tokens": r.get("cached_tokens"),
                    "reasoning_tokens": r.get("reasoning_tokens"),
                },
                "latency_ms": r.get("latency_ms"),
                "api_cost": r.get("api_cost"),
                "provider_response_id": r.get("provider_response_id"),
                "system_fingerprint": r.get("system_fingerprint"),
                "attempt": r.get("attempt", 1),
                "replicate": r.get("replicate", 0),
                "generated_at": r["generated_at"],
                "data_tier": DATA_TIER,
                "response_text": r.get("response_text") or "",
                "surface_meta": {
                    "release": "v1.1.0",
                    "subset": SUBSET_NAME,
                    "prompt_id_sha256": hash_hex,
                    "spoke_dev_commit": dev_commit,
                    "source": f"generation-ledger/gen-{label}.jsonl",
                    # The producer's own run key for the generation pass, which
                    # the seam note asks to preserve; this batch regroups the
                    # rows under a release-scoped key, so the original travels.
                    "producer_run_key": r.get("run_key"),
                    "generated_at_basis": "the ledger row's own generated_at",
                },
            })
    return rows


def assessments_for(models, subset, rubrics, gen_run_key, grade_times,
                    pass_of, stats, warnings):
    """One assessment per (candidate, prompt, rubric position, judge).

    `grades[]` is positional against the corpus's `rubrics[]`; the two lengths
    are checked for every row, because a verdict recorded against the wrong
    rubric item is a silent data error and the ledger is where it would become
    permanent."""
    order = {pid: i for i, pid in enumerate(subset["prompt_ids"])}
    subset_ids = set(subset["prompt_ids"])
    rows = []
    for candidate in models:
        for judge in JUDGES:
            path = GRADE_DIR / f"{candidate}__{judge}.jsonl"
            if not path.exists():
                warnings.append(f"{candidate} has no grades from {judge} (no {path.name})")
                continue
            graded = {}
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec["prompt_id"] not in subset_ids:
                        continue
                    graded[rec["prompt_id"]] = rec
            if len(graded) != len(subset_ids):
                warnings.append(
                    f"{candidate}__{judge}: {len(graded)}/{len(subset_ids)} prompts graded "
                    f"-- exporting the verdicts that exist, none invented"
                )
            stats[f"grade_file_{candidate}__{judge}"] = len(graded)
            for pid in sorted(graded, key=order.__getitem__):
                rec = graded[pid]
                items = rubrics[pid]
                verdicts = rec["grades"]
                if len(verdicts) != len(items):
                    raise SystemExit(
                        f"{path.name} / {pid}: {len(verdicts)} verdicts against "
                        f"{len(items)} rubric items -- positional alignment is broken, "
                        f"refusing to export"
                    )
                at = grade_times[(judge, pass_of(pid))]
                for i, (verdict, item) in enumerate(zip(verdicts, items)):
                    rows.append({
                        "key": f"{candidate}/{pid}/{i}/{judge}",
                        "subject": {
                            "type": "generation",
                            "key": f"{candidate}/{pid}",
                            # Generations and grades are separate runs, so the
                            # subject is named across runs explicitly.
                            "run_key": gen_run_key,
                        },
                        "assessor": {
                            "kind": "model",
                            "model": {
                                "label": judge,
                                "api_model_id": judge,
                                "provider": S.provider_of(judge),
                            },
                            # No generation_key: the judge calls themselves were
                            # never stored, only the verdicts they produced.
                        },
                        # The registered instrument, named: the platform
                        # resolves this triple to an instrument_version_id and
                        # the row stops being a verdict against nothing.
                        # `item_ordinal` is NOT here -- the ordinal is a fact
                        # about the criterion, and the instrument states it
                        # once instead of 464,000 times. `item_points` stays:
                        # the ledger copies it at write time so a score
                        # recomputes without joining the catalogue.
                        "instrument": {
                            "project_slug": INSTRUMENT_PROJECT_SLUG,
                            "kind": INSTRUMENT_KIND,
                            "version": INSTRUMENT_VERSION,
                            "item_key": f"hb:{pid}#{i}",
                            "item_points": item["points"],
                        },
                        "value": {"bool": bool(verdict["criteria_met"])},
                        "assessed_at": at,
                        "data_tier": DATA_TIER,
                        # Stripped upstream for size, and stated as absent
                        # rather than left to be inferred from a missing key.
                        "rationale_text": None,
                        # ROW HYGIENE: `extra` carries only facts true of THIS
                        # ONE VERDICT. Run-level facts (release, grader
                        # template, spoke commit, judge panel) are on the
                        # manifest; instrument-level facts (the criterion's
                        # tags, its text, its points beyond `item_points`)
                        # belong on the instrument version. The score below is
                        # the conversation-level HealthBench score this verdict
                        # contributed to -- per subject, small, and it stays.
                        "extra": {"score": rec.get("score")},
                    })
                    stats["verdicts"] += 1
    return rows


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def jsonl_line(row: dict) -> str:
    """One row, compactly and deterministically. Key order is the insertion
    order the builders above use, which is fixed in code, so the bytes only
    change when the data does."""
    return json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_part(path: Path, kind: str, rows: list[dict]) -> dict:
    """Write one JSONL part and return the manifest entry the platform will
    re-verify. Byte length and sha256 are taken from the bytes actually
    written, never from a separate re-encoding of the rows."""
    body = "".join(jsonl_line(row) for row in rows).encode("utf-8")
    path.write_bytes(body)
    return {
        "path": path.name,
        "kind": kind,
        "rows": len(rows),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def write_batch(out: Path, run_key: str, kind: str, rows: list[dict],
                commit: str | None, protocol: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    part = write_part(out / f"{kind}.jsonl", kind, rows)
    manifest = {
        "schema_version": 1,
        "run_key": run_key,
        "producer_commit": commit,
        "experiment": SUBSET_NAME,
        # generation-batch.v1 has no `extra` and forbids unknown keys, so the
        # benchmark's identity hash and the protocol deviations travel in this
        # string -- the one free-text field the contract gives a producer.
        "protocol": protocol,
        "bodies": "inline",
        "parts": [part],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return out / "manifest.json"


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", required=True, choices=sorted(RELEASES),
                    help="which release to export as its own batch")
    ap.add_argument("--dry-run", action="store_true", help="count everything, write nothing")
    args = ap.parse_args()

    spec = RELEASES[args.release]
    subset = load_subset()
    subset_ids = set(subset["prompt_ids"])
    rubrics = load_rubrics(subset_ids)
    gen_window, grade_times = spend_times()
    commit = git_commit(RELEASE_ROOT)
    dev_commit = git_commit(DEV_ROOT)
    stats: Counter = Counter()
    warnings: list[str] = []

    print(f"healthbench-psych {args.release}: {spec['note']}")
    print(f"  subset {SUBSET_NAME}: n={len(subset_ids)}, "
          f"prompt_id_sha256 {subset['prompt_id_sha256'][:12]}...")
    print(f"  models ({len(spec['models'])}): {', '.join(spec['models'])}")

    if spec["source"] == "thin":
        generations = thin_generations(spec["models"], subset, subset_ids,
                                       gen_window, dev_commit,
                                       subset["prompt_id_sha256"], stats)
        pass_of = lambda pid: "round2" if pid in set(subset["round2_added_prompt_ids"]) else "round1"  # noqa: E731
    else:
        generations = ledger_generations(spec["models"], subset, subset_ids,
                                         dev_commit, subset["prompt_id_sha256"], stats)
        pass_of = lambda pid: "new-models"  # noqa: E731

    # The identity check versioning.md asks for, over the ids ACTUALLY exported
    # rather than over the file that claims them. A membership change is a major
    # version event; an export that quietly shipped one would be the worst place
    # to discover it.
    exported_ids = {row["key"].split("/", 1)[1] for row in generations}
    recomputed = prompt_id_sha256(exported_ids)
    if recomputed != subset["prompt_id_sha256"]:
        raise SystemExit(
            f"prompt_id_sha256 of the exported ids ({recomputed[:16]}...) does not "
            f"match {SUBSET_FILE.name} ({subset['prompt_id_sha256'][:16]}...) -- "
            f"the exported membership is not {SUBSET_NAME}, refusing to write"
        )
    print(f"  prompt_id_sha256 recomputed over {len(exported_ids)} exported ids: matches")

    gen_run_key = f"healthbench-psych/{args.release}/generations"
    grade_run_key = f"healthbench-psych/{args.release}/grades"
    assessments = assessments_for(spec["models"], subset, rubrics, gen_run_key,
                                  grade_times, pass_of, stats, warnings)

    # The run-level facts, stated ONCE per batch rather than on every verdict:
    # generation-batch.v1 has no manifest `extra` and forbids unknown keys, so
    # `protocol` -- the one free-text field the contract gives a producer -- is
    # where the release, the benchmark identity hash, the grader template, the
    # judge panel and the spoke commit live. Per BATCH, not per row.
    #
    # `instrument_ref` is NOT here any more. It was a free-text stand-in for an
    # instrument the platform did not hold; now that
    # export_ledger_instrument.py has registered it, every verdict names the
    # real triple and the platform resolves it to an instrument_version_id.
    # Restating it here would be the same fact in two places, one of which
    # nothing checks.
    protocol = (
        f"{SUBSET_NAME} n={len(subset_ids)} "
        f"prompt_id_sha256={subset['prompt_id_sha256']}; "
        f"release {args.release} ({spec['note']}); "
        f"spoke_dev_commit={dev_commit}; "
        f"grader_template={GRADER_TEMPLATE_ID}; "
        f"judge panel: {', '.join(JUDGES)}; {GRADER_NOTE}"
    )

    status_counts = {k[len("status_"):]: v for k, v in sorted(stats.items())
                     if k.startswith("status_")}
    print(f"  generations: {len(generations)} "
          f"({', '.join(f'{v} {k}' for k, v in status_counts.items())})")
    if spec["source"] == "thin":
        print(f"    finish_reason present on {stats['finish_reason_present']} of "
              f"{len(generations)} rows; null on the rest (carried, not repaired)")
        print("    params / usage / latency / cost: ABSENT -- the thin store never sought them")
    print(f"  assessments: {len(assessments)} verdicts over "
          f"{sum(1 for k in stats if k.startswith('grade_file_'))} grade files")
    for w in warnings:
        print(f"  ! {w}")
    if args.dry_run:
        print("  dry run -- nothing written")
        return

    gen_manifest = write_batch(OUT_ROOT / "healthbench-psych" / args.release / "generations",
                               gen_run_key, "generations", generations, commit, protocol)
    print(f"  wrote {gen_manifest.parent}")
    if assessments:
        grade_manifest = write_batch(OUT_ROOT / "healthbench-psych" / args.release / "grades",
                                     grade_run_key, "assessments", assessments, commit, protocol)
        print(f"  wrote {grade_manifest.parent}")
    else:
        grade_manifest = None
        print("  no grades for this release -- generations batch only")

    print("  ingest (generations FIRST -- the verdicts name them across runs):")
    print(f"    npx tsx scripts/import/generation-batch.ts {gen_manifest} --producer {PRODUCER_REPO}")
    if grade_manifest:
        print(f"    npx tsx scripts/import/generation-batch.ts {grade_manifest} --producer {PRODUCER_REPO}")


if __name__ == "__main__":
    main()
