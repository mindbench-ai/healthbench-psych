"""Run one (candidate x judge) HealthBench evaluation over a frozen subset.

Grading is HealthBench-exact (see hb_grade.py). This driver only orchestrates:
generate a candidate response per prompt, grade it with the judge model, write
per-response scores + a full run manifest, and append the run to the ledger so
we never duplicate a (subset, candidate, judge) cell.

Model access is a plug-in seam. A *Sampler* is any object with:
    .id      : str                      # pinned model id, e.g. "gpt-5-2025-xx"
    .params  : dict                     # decoding params actually used (logged)
    def __call__(messages_or_prompt): ...
A candidate sampler is called with a HealthBench message list and returns the
assistant response text. A judge sampler is called with a single grader-prompt
string and returns the model's raw text. Implement these per provider in
samplers.py (your API keys live there, in the env). This file makes no model
calls itself.

CLI:  python eval/run_eval.py --subset clear_includes_tight --candidate <id> --judge <id>
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import subprocess

from lib import hb_grade

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBSETS = os.path.join(ROOT, "eval", "subsets")
RUNS = os.path.join(ROOT, "eval", "runs")
LEDGER = os.path.join(RUNS, "ledger.csv")
SOURCE = os.path.join(ROOT, "source", "hb_oss.jsonl")
GRADER_FILE = os.path.join(ROOT, "eval", "vendor", "healthbench_eval.py")


def _sha(path, n=12):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:n]


def _git_commit():
    try:
        return subprocess.check_output(
            ["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def load_subset(name):
    meta = json.load(open(os.path.join(SUBSETS, f"{name}.json")))
    return meta, set(meta["prompt_ids"])


def load_examples(prompt_ids):
    ex = {}
    for line in open(SOURCE):
        d = json.loads(line)
        if d["prompt_id"] in prompt_ids:
            ex[d["prompt_id"]] = d
    missing = prompt_ids - set(ex)
    if missing:
        raise SystemExit(f"{len(missing)} subset prompt_ids not found in source")
    return ex


def ledger_rows():
    if not os.path.exists(LEDGER):
        return []
    return list(csv.DictReader(open(LEDGER)))


def already_done(subset_hash, candidate_id, judge_id):
    for r in ledger_rows():
        if (
            r["subset_sha"] == subset_hash
            and r["candidate_id"] == candidate_id
            and r["judge_id"] == judge_id
            and r["status"] == "SUCCESS"
        ):
            return r
    return None


def append_ledger(row):
    new = not os.path.exists(LEDGER)
    fields = [
        "run_id", "timestamp", "subset", "subset_sha", "candidate_id",
        "judge_id", "n_prompts", "status", "results_path", "manifest_path", "git",
    ]
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def run(subset_name, candidate, judge, now_iso, force=False):
    meta, prompt_ids = load_subset(subset_name)
    subset_sha = meta["prompt_id_sha256"][:12]
    dup = already_done(subset_sha, candidate.id, judge.id)
    if dup and not force:
        print(f"SKIP (already in ledger as {dup['run_id']}): "
              f"{subset_name} x {candidate.id} x {judge.id}. Use --force to rerun.")
        return dup["run_id"]

    examples = load_examples(prompt_ids)

    # Candidate responses: generate ONCE per (candidate, subset) and reuse across
    # judges, so every judge grades identical responses (isolates the judge effect).
    resp_dir = os.path.join(RUNS, "responses")
    os.makedirs(resp_dir, exist_ok=True)
    resp_file = os.path.join(resp_dir, f"{candidate.id}_{subset_sha}.jsonl".replace("/", "-"))
    if os.path.exists(resp_file):
        responses = {json.loads(l)["prompt_id"]: json.loads(l)["response_text"]
                     for l in open(resp_file)}
        resp_source = "cached"
    else:
        responses = {}
        with open(resp_file, "w") as rf:
            for pid in sorted(prompt_ids):
                responses[pid] = candidate(examples[pid]["prompt"])
                rf.write(json.dumps({"prompt_id": pid, "candidate_id": candidate.id,
                                     "response_text": responses[pid]}, ensure_ascii=False) + "\n")
        resp_source = "generated"

    run_id = f"{subset_sha}_{candidate.id}_{judge.id}".replace("/", "-")
    out_dir = os.path.join(RUNS, run_id)
    os.makedirs(out_dir, exist_ok=True)
    results_path = os.path.join(out_dir, "results.jsonl")

    n = 0
    with open(results_path, "w") as out:
        for pid in sorted(prompt_ids):
            ex = examples[pid]
            response_text = responses[pid]
            rubric_items = [hb_grade.RubricItem.from_dict(r) for r in ex["rubrics"]]
            score, grades = hb_grade.grade_response(
                ex["prompt"], response_text, rubric_items, judge
            )
            out.write(json.dumps({
                "prompt_id": pid,
                "candidate_id": candidate.id,
                "judge_id": judge.id,
                "score": score,
                "response_text": response_text,
                "grades": grades,
            }, ensure_ascii=False) + "\n")
            n += 1

    manifest = {
        "run_id": run_id,
        "timestamp": now_iso,
        "git_commit": _git_commit(),
        "subset": {"name": subset_name, "sha": subset_sha, "n": meta["n"]},
        "candidate": {"id": candidate.id, "params": getattr(candidate, "params", {}),
                      "responses_file": os.path.relpath(resp_file, ROOT), "responses_source": resp_source},
        "judge": {"id": judge.id, "params": getattr(judge, "params", {})},
        "grader": {"file": "eval/vendor/healthbench_eval.py", "sha": _sha(GRADER_FILE),
                   "reused_by": "eval/hb_grade.py (verbatim)"},
        "source_corpus": {"file": "source/hb_oss.jsonl", "sha": _sha(SOURCE)},
        "n_prompts_scored": n,
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    json.dump(manifest, open(manifest_path, "w"), indent=2)

    append_ledger({
        "run_id": run_id, "timestamp": now_iso, "subset": subset_name,
        "subset_sha": subset_sha, "candidate_id": candidate.id, "judge_id": judge.id,
        "n_prompts": n, "status": "SUCCESS",
        "results_path": os.path.relpath(results_path, ROOT),
        "manifest_path": os.path.relpath(manifest_path, ROOT), "git": _git_commit(),
    })
    print(f"DONE {run_id}: {n} prompts scored -> {results_path}")
    return run_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True, help="subset name under eval/subsets/")
    ap.add_argument("--candidate", required=True, help="candidate model id (key in samplers.REGISTRY)")
    ap.add_argument("--judge", required=True, help="judge model id (key in samplers.REGISTRY)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--now", default=None, help="ISO timestamp override (else uses run time)")
    args = ap.parse_args()

    from lib import samplers  # devs implement REGISTRY: id -> Sampler instance
    candidate = samplers.REGISTRY[args.candidate]
    judge = samplers.REGISTRY[args.judge]
    now_iso = args.now or datetime.datetime.now(datetime.timezone.utc).isoformat()
    run(args.subset, candidate, judge, now_iso, force=args.force)


if __name__ == "__main__":
    main()
