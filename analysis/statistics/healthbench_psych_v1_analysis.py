#!/usr/bin/env python3
"""HealthBench-Psych v1: the paper's quantitative analyses.

Computes the statistics reported in the paper from the released data: subset
construction and loop termination (§3.1), the model leaderboard with bootstrap CIs and
paired-difference comparisons (§3.3), judge agreement, severity, and self-preference
(§3.4), and the refusal census with its sensitivity analysis (§3.5).

Runs from the repository root with no API keys:
    python3 analysis/statistics/healthbench_psych_v1_analysis.py

Also recomputes the HealthBench-Hard harness-parity score (§3.2) from the released
per-conversation results in provenance/harness-validation/ (reproducing that run from
scratch requires the HealthBench corpus, which this repository does not redistribute).
"""
import csv
import glob
import json
import os
import statistics as st
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats_lib as SL  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUBSET = "healthbench-psych-v1"
JUDGES = ["gpt-4.1-2025-04-14", "claude-haiku-4-5-20251001", "gemini-2.5-flash"]


def load_reviews(rnd):
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "provenance/review/results", rnd, "*.json"))):
        d = json.load(open(f))
        out[d["reviewer"]] = {x["prompt_id"]: x for x in d["ratings"]}
    return out


def majority(reviews, p):
    return sum(1 for rv in reviews.values() if rv[p]["is_mental_health"] == "Y") >= 2


def panel_scores(cand, ids):
    """Per-conversation panel score: mean of the three judges' HealthBench scores."""
    by = {}
    for j in JUDGES:
        for line in open(os.path.join(ROOT, "eval/runs/grades", f"{cand}__{j}.jsonl")):
            r = json.loads(line)
            if r["prompt_id"] in ids and r.get("score") is not None:
                by.setdefault(r["prompt_id"], []).append(r["score"])
    return {p: st.mean(v) for p, v in by.items() if len(v) == len(JUDGES)}


def subset_construction(ids, r2new, key, r1, r2, key2):
    print("\n== Subset construction and loop termination (§3.1) ==\n")
    lab = Counter(r["screening_label"] for r in key.values())
    total = sum(lab.values())
    print("Screen label distribution:")
    for name in ("RELEVANT", "BORDERLINE", "NOT_RELEVANT"):
        print(f"  {name:13s} {lab[name]:5d}  ({100 * lab[name] / total:.1f}%)")
    rel_cats = Counter(r["screening_category"] for r in key.values() if r["screening_label"] == "RELEVANT")
    top_cat, top_n = rel_cats.most_common(1)[0]
    print(f"Largest RELEVANT screen category: {top_cat} ({top_n}/{lab['RELEVANT']})")

    print("\nReview rounds:")
    print(f"  {'round':7s} {'rated':>6s} {'controls':>9s} {'ctrl incl.':>11s} {'rate':>6s} {'included':>9s} {'AC1':>6s}")
    r1_ids = sorted(set.intersection(*(set(v) for v in r1.values())))
    ctrl1 = [p for p in r1_ids if key[p]["screening_label"] == "NOT_RELEVANT"]
    inc_ctrl1 = sum(1 for p in ctrl1 if majority(r1, p))
    inc1 = sum(1 for p in r1_ids if majority(r1, p))
    rel1 = {rater: {p: r1[rater][p]["is_mental_health"] for p in r1_ids} for rater in r1}
    ac1_1, _ = SL.mean_pairwise_ac1(rel1, r1_ids)
    print(f"  {'1':7s} {len(r1_ids):6d} {len(ctrl1):9d} {inc_ctrl1:11d} "
          f"{100 * inc_ctrl1 / len(ctrl1):5.1f}% {inc1:9d} {ac1_1:6.2f}")

    cand2 = [p for p, r in key2.items() if r["kind"] == "candidate"]
    ctrl2 = [p for p, r in key2.items() if r["kind"] == "control"]
    inc2 = [p for p in cand2 if majority(r2, p)]
    inc_ctrl2 = sum(1 for p in ctrl2 if majority(r2, p))
    rel2 = {rater: {p: r2[rater][p]["is_mental_health"] for p in key2} for rater in r2}
    ac1_2, pairs2 = SL.mean_pairwise_ac1(rel2, sorted(key2))
    print(f"  {'2':7s} {len(key2):6d} {len(ctrl2):9d} {inc_ctrl2:11d} "
          f"{100 * inc_ctrl2 / len(ctrl2):5.1f}% {len(inc2):9d} {ac1_2:6.2f}")
    print(f"  round-2 pairwise AC1 range: {min(pairs2):.2f}–{max(pairs2):.2f}")
    tiers = Counter(key2[p]["recovery_tier"] for p in cand2)
    inc_clear = sum(1 for p in inc2 if key2[p]["recovery_tier"] == "CLEAR")
    print(f"  recovery pool: {lab['NOT_RELEVANT'] - len(ctrl1)} conversations -> "
          f"{len(cand2)} candidates (CLEAR {tiers['CLEAR']}, POSSIBLE {tiers['POSSIBLE']}); "
          f"included {len(inc2)} (CLEAR {inc_clear}, POSSIBLE {len(inc2) - inc_clear})")
    print(f"\nReleased subset: n = {len(ids)}  ({100 * len(ids) / total:.1f}% of corpus)")

    cats = Counter()
    for p in ids:
        src = r2 if p in r2new else r1
        votes = Counter(v[p]["category"] for v in src.values()
                        if p in v and v[p]["is_mental_health"] == "Y")
        top = votes.most_common(1)
        cats[top[0][0] if top and top[0][1] >= 2 else "(no category majority)"] += 1
    print("\nModal clinician category decomposition:")
    for cat, n in cats.most_common():
        print(f"  {cat:26s} {n:4d}  ({100 * n / len(ids):.1f}%)")


def harness_validation():
    print("\n== Harness validation (§3.2) ==\n")
    path = os.path.join(ROOT, "provenance/harness-validation/results.jsonl")
    scores = [json.loads(l)["score"] for l in open(path) if json.loads(l).get("score") is not None]
    m = SL.clip01(st.mean(scores))
    print(f"  GPT-4.1 on HealthBench-Hard (n={len(scores)}): clipped mean = {m:.3f}  "
          f"(published reference: 0.16; delta = {m - 0.16:+.3f})")


def leaderboard(panels):
    print("\n== Model leaderboard (§3.3) ==\n")
    rows = []
    for c, scores in panels.items():
        m, lo, hi = SL.bootstrap_ci(list(scores.values()))
        rows.append((c, m, lo, hi))
    rows.sort(key=lambda r: -r[1])
    print(f"  {'model':28s} {'mean':>6s}  {'95% CI':>16s}")
    for c, m, lo, hi in rows:
        print(f"  {c:28s} {m:6.3f}  [{lo:.3f}, {hi:.3f}]")

    print("\nPaired conversation-level comparisons, all pairs within the frontier cluster:")
    import itertools, random
    top5 = [c for c, *_ in rows[:5]]
    pvals = []
    for a, b in itertools.combinations(top5, 2):
        d, lo, hi = SL.paired_diff_ci(panels[a], panels[b])
        common = sorted(set(panels[a]) & set(panels[b]))
        diffs = [panels[a][p] - panels[b][p] for p in common]
        rng = random.Random(0)
        le = sum(1 for _ in range(10000) if st.mean(rng.choices(diffs, k=len(diffs))) <= 0)
        p = max(2 * min(le, 10000 - le) / 10000, 2 / 10000)
        pvals.append(((a, b), p))
        sep = "tie" if lo <= 0 <= hi else "separated (uncorrected)"
        print(f"  {a:14s} vs {b:14s}  Δ = {d:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  p = {p:.4f}  ({sep})")
    ordered = sorted(pvals, key=lambda x: x[1])
    surviving = []
    for i, (pair, p) in enumerate(ordered):
        if p < 0.05 / (10 - i):
            surviving.append(pair)
        else:
            break
    print(f"  Holm–Bonferroni (10 tests, alpha 0.05): smallest p = {ordered[0][1]:.4f} vs "
          f"threshold 0.0050 -> {len(surviving)} pair(s) survive correction")
    return rows


def lineage_regressions(panels):
    print("\n== Newest release vs immediate predecessor, per lineage (Discussion) ==\n")
    for newer, older in [("claude-fable-5", "claude-opus-5"),
                         ("gpt-5.6-sol", "gpt-5.5"),
                         ("kimi-k3", "kimi-k2.6")]:
        d, lo, hi = SL.paired_diff_ci(panels[newer], panels[older])
        print(f"  {newer:14s} - {older:14s}  Δ = {d:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")


def frontier_hard(rows):
    print("\n== Frontier comparisons on HealthBench-Psych-Hard (§3.3 / Figure 2) ==\n")
    import itertools
    hard = os.path.join(ROOT, "eval/subsets", "healthbench-psych-hard-v1.json")
    ids = set(json.load(open(hard))["prompt_ids"])
    top5 = [c for c, *_ in rows[:5]]
    pan = {c: panel_scores(c, ids) for c in top5}
    any_sep = False
    for a, b in itertools.combinations(top5, 2):
        d, lo, hi = SL.paired_diff_ci(pan[a], pan[b])
        if not (lo <= 0 <= hi):
            any_sep = True
            print(f"  separated: {a} vs {b}  Δ = {d:+.4f}  [{lo:+.4f}, {hi:+.4f}]")
    if not any_sep:
        print(f"  all 10 paired frontier comparisons cross zero at n={len(ids)}: "
              "the cluster is statistically indistinguishable on the hard subset")


def judge_analyses(panels, ids):
    print("\n== Judge agreement, severity, and self-preference (§3.4) ==\n")
    import itertools, random
    candidates = sorted(panels)
    pids = sorted(ids)
    # per-(candidate, judge) score vectors aligned on the sorted conversation list
    vec = {}
    for c in candidates:
        for j in JUDGES:
            scs = {}
            for l in open(os.path.join(ROOT, "eval/runs/grades", f"{c}__{j}.jsonl")):
                r = json.loads(l)
                if r["prompt_id"] in ids and r.get("score") is not None:
                    scs[r["prompt_id"]] = r["score"]
            vec[(c, j)] = [scs[p] for p in pids if p in scs]
    n = min(len(v) for v in vec.values())

    def stats_from(idx):
        cell = {(c, j): SL.clip01(sum(vec[(c, j)][i] for i in idx) / len(idx))
                for c in candidates for j in JUDGES}
        taus = {pair: SL.kendall_tau([cell[(c, pair[0])] for c in candidates],
                                     [cell[(c, pair[1])] for c in candidates])
                for pair in itertools.combinations(JUDGES, 2)}
        grand, sev = SL.judge_severity(cell, candidates, JUDGES)
        sp = SL.self_preference(cell, JUDGES, sev)
        return taus, grand, sev, sp

    point = stats_from(list(range(n)))
    rng = random.Random(0)
    boots = [stats_from([rng.randrange(n) for _ in range(n)]) for _ in range(1000)]

    def ci(get):
        vals = sorted(get(b) for b in boots)
        return vals[25], vals[974]

    print("Between-judge rank agreement (Kendall tau, 95% conversation-level bootstrap CI):")
    for pair in itertools.combinations(JUDGES, 2):
        lo, hi = ci(lambda b, p=pair: b[0][p])
        a, b_ = pair[0].split("-2025")[0], pair[1].split("-2025")[0]
        print(f"  {a:20s} vs {b_:20s} tau = {point[0][pair]:.3f}  [{lo:.3f}, {hi:.3f}]")
    lo, hi = ci(lambda b: b[1])
    print(f"\nJudge severity (grand mean {point[1]:.3f} [{lo:.3f}, {hi:.3f}]):")
    for j in JUDGES:
        lo, hi = ci(lambda b, j=j: b[2][j])
        print(f"  {j:28s} {point[2][j]:+.3f}  [{lo:+.3f}, {hi:+.3f}]")
    print("\nSelf-preference, raw -> severity-corrected (95% CI; two-sided bootstrap p vs zero for corrected):")
    for j in JUDGES:
        rlo, rhi = ci(lambda b, j=j: b[3][j][0])
        clo, chi = ci(lambda b, j=j: b[3][j][1])
        cboots = [b[3][j][1] for b in boots]
        le = sum(1 for v in cboots if v <= 0)
        p = max(2 * min(le, 1000 - le) / 1000, 2 / 1000)
        print(f"  {j:28s} {point[3][j][0]:+.3f} [{rlo:+.3f}, {rhi:+.3f}] -> "
              f"{point[3][j][1]:+.3f} [{clo:+.3f}, {chi:+.3f}]  p = {p:.2f}")


def refusal_analyses(panels, ids):
    print("\n== Refusals (§3.5) ==\n")
    refused = {}
    for c in panels:
        path = os.path.join(ROOT, "eval/runs/responses", f"{c}.jsonl")
        empty = {json.loads(l)["prompt_id"] for l in open(path)
                 if json.loads(l)["prompt_id"] in ids and not (json.loads(l)["response_text"] or "").strip()}
        if empty:
            refused[c] = empty
    if not refused:
        print("  none")
        return
    for c, refs in sorted(refused.items()):
        m_all = SL.clip01(st.mean(panels[c].values()))
        rs = sorted(panels[c][p] for p in refs if p in panels[c])
        print(f"  {c}: refused-conversation panel scores mean {st.mean(rs):+.3f}, "
              f"range [{rs[0]:+.3f}, {rs[-1]:+.3f}], {sum(1 for x in rs if x > 0)} of {len(rs)} positive")
        kept = [v for p, v in panels[c].items() if p not in refs]
        print(f"  {c}: {len(refs)}/{len(ids)} refusals ({100 * len(refs) / len(ids):.1f}%)  "
              f"mean {m_all:.3f} -> {SL.clip01(st.mean(kept)):.3f} excluding refusals")
    pairs = list(refused)
    if len(pairs) == 2:
        overlap = len(refused[pairs[0]] & refused[pairs[1]])
        print(f"  overlap between {pairs[0]} and {pairs[1]} refusal sets: {overlap} conversations")


def main():
    sub = json.load(open(os.path.join(ROOT, "eval/subsets", f"{SUBSET}.json")))
    ids = set(sub["prompt_ids"])
    r2new = set(sub.get("round2_added_prompt_ids", []))
    key = {r["prompt_id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "provenance/screening/screening-key.csv")))}
    key2 = {r["prompt_id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "provenance/screening/recovery-screening-key.csv")))}
    r1, r2 = load_reviews("round1"), load_reviews("round2")
    candidates = sorted({os.path.basename(p).split("__")[0]
                         for p in glob.glob(os.path.join(ROOT, "eval/runs/grades", "*__*.jsonl"))})
    panels = {c: panel_scores(c, ids) for c in candidates}

    subset_construction(ids, r2new, key, r1, r2, key2)
    harness_validation()
    rows = leaderboard(panels)
    lineage_regressions(panels)
    frontier_hard(rows)
    judge_analyses(panels, ids)
    refusal_analyses(panels, ids)


if __name__ == "__main__":
    main()
