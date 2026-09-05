#!/usr/bin/env python3
"""Rebuild eval/runs/responses/ and eval/runs/grades/ from the released dataset.

The released run data (one response per model x conversation; one grade record
per model x judge x conversation) is hosted on the Hugging Face dataset
mindbench-ai/healthbench-psych rather than in this repository. This script
downloads the two run configs and rewrites the per-file store the harness and
analysis code read. One-time download, ~45 MB; everything afterwards is local.

    python3 eval/fetch_runs.py                  # fetch from Hugging Face (main)
    python3 eval/fetch_runs.py --revision v1.0.0  # fetch a tagged release
    python3 eval/fetch_runs.py --source DIR     # rebuild from a local dataset build
    python3 eval/fetch_runs.py --force          # overwrite an existing store

Stdlib only, like the rest of eval/. Reconstruction is exact: field values,
key order, and per-file row order match the store the dataset was built from
(keys that were absent in the store are null in the dataset and are omitted
again here).
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = "https://huggingface.co/datasets/mindbench-ai/healthbench-psych"
RUNS = Path(__file__).resolve().parent / "runs"


def fetch(source, name, revision):
    rel = f"data/{name}/train.jsonl"
    if source:
        return (Path(source) / rel).read_text(encoding="utf-8")
    url = f"{REPO}/resolve/{revision}/{rel}"
    print(f"  downloading {url}")
    with urllib.request.urlopen(url) as r:
        return r.read().decode("utf-8")


def write_group(rows_by_file, out_dir, n_field):
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname in sorted(rows_by_file):
        with (out_dir / f"{fname}.jsonl").open("w", encoding="utf-8") as fh:
            for rec in rows_by_file[fname]:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  {out_dir.name}: {len(rows_by_file)} files, {n_field} records")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="local dataset directory instead of Hugging Face")
    ap.add_argument("--revision", default="main",
                    help="HF revision to fetch: a tag such as v1.0.0, a branch, or a "
                         "commit sha (default: main). Release tags on HF mirror the "
                         "GitHub tags, so --revision vX.Y.Z pins the run data to the "
                         "same release as the checked-out code.")
    ap.add_argument("--force", action="store_true", help="overwrite an existing store")
    a = ap.parse_args()

    for d in (RUNS / "responses", RUNS / "grades"):
        if d.exists() and any(d.iterdir()) and not a.force:
            sys.exit(f"{d} already populated; pass --force to overwrite")

    # responses: dataset rows carry the store fields plus model / is_refusal.
    resp = {}
    n = 0
    for line in fetch(a.source, "responses", a.revision).splitlines():
        r = json.loads(line)
        rec = {"prompt_id": r["prompt_id"], "response_text": r["response_text"]}
        # 1.1.0+ payloads carry finish_reason (and stop_reason as a deprecated
        # alias); a v1.0.0 payload carries stop_reason only. Store one name.
        fr = r.get("finish_reason", r.get("stop_reason"))
        if fr is not None:
            rec["finish_reason"] = fr
        if r.get("correction") is not None:
            rec["correction"] = r["correction"]
        resp.setdefault(r["model"], []).append(rec)
        n += 1
    write_group(resp, RUNS / "responses", n)

    # grades: criteria_met booleans expand back into the store's grades list.
    grades = {}
    n = 0
    for line in fetch(a.source, "grades", a.revision).splitlines():
        r = json.loads(line)
        rec = {"prompt_id": r["prompt_id"], "score": r["score"],
               "grades": [{"criteria_met": b} for b in r["criteria_met"]]}
        grades.setdefault(f'{r["model"]}__{r["judge"]}', []).append(rec)
        n += 1
    write_group(grades, RUNS / "grades", n)


if __name__ == "__main__":
    main()
