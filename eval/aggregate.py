"""Aggregate a subset's candidate x judge runs into the reported metrics.

The reported per-cell score is HealthBench's: the mean of per-prompt overall
scores, CLIPPED to [0,1] (their `_compute_clipped_stats`: np.clip(mean,0,1)).
Also computes between-judge rank correlation (Kendall tau) and self-preference
(a model's score under itself vs. under the other judges).

Usage:  python eval/aggregate.py --subset clear_includes_tight
"""
import argparse
import csv
import glob
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "eval", "runs")
SUBSETS = os.path.join(ROOT, "eval", "subsets")


def clipped_mean(scores):
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    m = sum(scores) / len(scores)
    return max(0.0, min(1.0, m))  # HealthBench clips the mean to [0,1]


def kendall_tau(a, b):
    """tau between two equal-length rank/score vectors, no scipy."""
    n = len(a)
    if n < 2:
        return float("nan")
    con = dis = 0
    for i, j in itertools.combinations(range(n), 2):
        s = (a[i] - a[j]) * (b[i] - b[j])
        con += s > 0
        dis += s < 0
    denom = n * (n - 1) / 2
    return (con - dis) / denom if denom else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", required=True)
    args = ap.parse_args()
    meta = json.load(open(os.path.join(SUBSETS, f"{args.subset}.json")))
    sha12 = meta["prompt_id_sha256"][:12]
    subset_pids = set(meta["prompt_ids"])

    # Read the prompt-keyed grades store; keep only this subset's prompts, so
    # round-1 and round-2 grades coexist and any subset is scored by filtering.
    cell = {}  # (candidate, judge) -> clipped mean over subset prompts
    n = {}
    models = set()
    for path in sorted(glob.glob(os.path.join(store.GRADE_DIR, "*__*.jsonl"))):
        cand, judge = os.path.basename(path)[:-6].split("__")
        scores = [r["score"] for r in (json.loads(l) for l in open(path))
                  if r["prompt_id"] in subset_pids and r.get("score") is not None]
        if scores:
            cell[(cand, judge)] = clipped_mean(scores)
            n[(cand, judge)] = len(scores)
            models.add(cand); models.add(judge)
    models = sorted(models)
    if not cell:
        raise SystemExit(f"no grades in store for subset {args.subset}")
    judges = [j for j in models if any(cell.get((c, j)) is not None for c in models)]
    cands = [c for c in models if any(cell.get((c, j)) is not None for j in models)]

    # matrix (rows = candidates, columns = judges only)
    print(f"subset={args.subset} (sha {sha12})   n_prompts={max(n.values())}")
    print("\n=== candidate x judge  (HealthBench clipped-mean score) ===")
    print("cand\\judge".ljust(26) + "".join(f"{j[:18]:>20}" for j in judges))
    for c in cands:
        cells = [cell.get((c, j)) for j in judges]
        print(c[:26].ljust(26) + "".join(
            ("      n/a" if v is None else f"{v:8.3f}").rjust(20) for v in cells))

    # between-judge rank correlation over the candidates both judges scored
    print("\n=== between-judge agreement (Kendall tau over candidate scores) ===")
    for ja, jb in itertools.combinations(judges, 2):
        pairs = [(cell[(c, ja)], cell[(c, jb)]) for c in cands
                 if cell.get((c, ja)) is not None and cell.get((c, jb)) is not None]
        if len(pairs) < 2:
            print(f"  {ja[:16]} vs {jb[:16]}: n/a (<2 shared candidates)")
        else:
            va = [p[0] for p in pairs]; vb = [p[1] for p in pairs]
            print(f"  {ja[:16]} vs {jb[:16]}: tau={kendall_tau(va, vb):+.3f} (n={len(pairs)})")

    # Judge severity: overall leniency/strictness, measured on the candidates every
    # judge scored (so severities are comparable). This is the judge main effect in
    # an additive candidate+judge model; the raw self-minus-cross self-preference
    # confounds it, so we subtract it to get the corrected effect.
    complete = [c for c in cands
                if all(cell.get((c, j)) is not None for j in judges)]
    severity = {}
    if complete and judges:
        grand = sum(cell[(c, j)] for c in complete for j in judges) / (len(complete) * len(judges))
        for j in judges:
            severity[j] = sum(cell[(c, j)] for c in complete) / len(complete) - grand
        print(f"\n=== judge severity (over {len(complete)} candidates graded by all "
              f"{len(judges)} judges; grand mean={grand:.3f}) ===")
        for j in judges:
            tag = "strict" if severity[j] < -0.02 else ("lenient" if severity[j] > 0.02 else "")
            print(f"  {j[:24].ljust(24)} mean={severity[j] + grand:.3f}  "
                  f"severity={severity[j]:+.3f}  {tag}")
    else:
        print("\n=== judge severity: n/a (no candidate graded by all judges) ===")

    def corrected(c, j):
        v = cell.get((c, j))
        return None if v is None else v - severity.get(j, 0.0)

    # Self-preference: a model's score under its own judge vs. under the others.
    # Report raw AND severity-corrected — the corrected value is the one to trust.
    print("\n=== self-preference: raw vs. severity-corrected "
          "(judge=m minus mean judge!=m) ===")
    for m in models:
        self_raw = cell.get((m, m))
        others_raw = [cell.get((m, j)) for j in judges if j != m and cell.get((m, j)) is not None]
        if self_raw is None or not others_raw:
            continue
        raw = self_raw - sum(others_raw) / len(others_raw)
        others_c = [corrected(m, j) for j in judges if j != m and corrected(m, j) is not None]
        cdelta = corrected(m, m) - sum(others_c) / len(others_c)
        print(f"  {m[:24].ljust(24)}: raw={raw:+.3f}   severity_corrected={cdelta:+.3f}")

    # error/anomaly transparency for this subset (durable log at store.ERROR_LOG)
    errs = []
    if os.path.exists(store.ERROR_LOG):
        errs = [e for e in (json.loads(l) for l in open(store.ERROR_LOG))
                if e.get("prompt_id") in subset_pids]
    print("\n=== errors/anomalies (this subset) ===")
    if not errs:
        print("  none")
    else:
        from collections import Counter
        for (ph, k), c in Counter((e.get("phase"), e.get("kind")) for e in errs).most_common():
            print(f"  {ph}/{k}: {c}")
        emp = Counter(e.get("candidate") for e in errs if e.get("kind") == "empty_response")
        if emp:
            print("  empty_response by candidate: " + ", ".join(f"{c}:{n}" for c, n in emp.most_common()))

    out = os.path.join(RUNS, f"matrix_{args.subset}.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate", "judge", "clipped_mean_score", "n_prompts"])
        for c in models:
            for j in models:
                if (c, j) in cell:
                    w.writerow([c, j, f"{cell[(c, j)]:.6f}", n[(c, j)]])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
