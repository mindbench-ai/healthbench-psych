"""Statistical helpers for HealthBench-Psych analyses.

Self-contained (stdlib only). Every function here backs a number reported in the paper;
see healthbench_psych_v1_analysis.py for the paper analyses.
"""
import itertools
import random
import statistics as st


def clip01(x):
    return max(0.0, min(1.0, x))


def bootstrap_ci(values, n_boot=1000, seed=0, alpha=0.05):
    """Percentile bootstrap CI for the clipped mean (HealthBench's bootstrap recipe:
    resample the per-conversation scores with replacement)."""
    rng = random.Random(seed)
    n = len(values)
    boots = sorted(clip01(st.mean(rng.choices(values, k=n))) for _ in range(n_boot))
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot) - 1]
    return clip01(st.mean(values)), lo, hi


def paired_diff_ci(scores_a, scores_b, n_boot=1000, seed=0, alpha=0.05):
    """Bootstrap CI for mean(a-b) over the SAME conversations (paired: both models'
    scores come from one resample, preserving their correlation). scores_* are dicts
    keyed by conversation id."""
    common = sorted(set(scores_a) & set(scores_b))
    diffs = [scores_a[p] - scores_b[p] for p in common]
    rng = random.Random(seed)
    boots = sorted(st.mean(rng.choices(diffs, k=len(diffs))) for _ in range(n_boot))
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot) - 1]
    return st.mean(diffs), lo, hi


def kendall_tau(a, b):
    """Kendall tau (tau-a) between two equal-length score vectors."""
    n = len(a)
    con = dis = 0
    for i, j in itertools.combinations(range(n), 2):
        s = (a[i] - a[j]) * (b[i] - b[j])
        con += s > 0
        dis += s < 0
    return (con - dis) / (n * (n - 1) / 2)


def gwet_ac1_pairwise(labels_a, labels_b, positive="Y"):
    """Gwet's AC1 for two raters, binary labels, over aligned item lists."""
    n = len(labels_a)
    pa = sum(x == y for x, y in zip(labels_a, labels_b)) / n
    piy = sum((x == positive) + (y == positive) for x, y in zip(labels_a, labels_b)) / (2 * n)
    pe = 2 * piy * (1 - piy)
    return (pa - pe) / (1 - pe)


def mean_pairwise_ac1(ratings_by_rater, items):
    """Mean of pairwise AC1 over all rater pairs; ratings_by_rater: {rater: {item: 'Y'/'N'}}."""
    raters = sorted(ratings_by_rater)
    vals = []
    for a, b in itertools.combinations(raters, 2):
        la = [ratings_by_rater[a][i] for i in items]
        lb = [ratings_by_rater[b][i] for i in items]
        vals.append(gwet_ac1_pairwise(la, lb))
    return st.mean(vals), vals


def judge_severity(cell, candidates, judges):
    """cell: {(cand, judge): mean}. Returns (grand_mean, {judge: severity})."""
    grand = st.mean(cell[(c, j)] for c in candidates for j in judges)
    sev = {j: st.mean(cell[(c, j)] for c in candidates) - grand for j in judges}
    return grand, sev


def self_preference(cell, judges, severity):
    """Raw and severity-corrected self-preference for judges that are also candidates."""
    out = {}
    for m in judges:
        others = [j for j in judges if j != m]
        raw = cell[(m, m)] - st.mean(cell[(m, j)] for j in others)
        corr = (cell[(m, m)] - severity[m]) - st.mean(cell[(m, j)] - severity[j] for j in others)
        out[m] = (raw, corr)
    return out
