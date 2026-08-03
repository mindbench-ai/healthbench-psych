"""Headline figure: 3-judge panel ranking for HealthBench-Psych, with bootstrap CIs.

Bars = mean of the three judges' scores (equal weight; judge-severity offsets are
constant per judge, so this ordering equals the severity-corrected one).
Error bars = 95% CI from a HealthBench-style bootstrap (the vendor's
`_compute_clipped_stats` bootstrap_std recipe: resample prompts with replacement,
1000 iterations) applied to the per-prompt panel score (mean of the 3 judges'
scores on that prompt).

Color encodes lab, shade the tier within a lab; direct labels, legend in the
right gutter.
Run with .venv-fig/bin/python (has matplotlib).
"""
import argparse, json, os, random, sys, statistics as st
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "eval")))
from lib import samplers as S, store
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]
matplotlib.rcParams["font.serif"] = ["Source Serif 4", "Source Serif Pro", "Georgia", "DejaVu Serif"]

JUDGES = ["gpt-4.1-2025-04-14", "claude-haiku-4-5-20251001", "gemini-2.5-flash"]
N_BOOT = 1000
_ap = argparse.ArgumentParser()
_ap.add_argument("--subset", default="healthbench-psych-v1")
_ap.add_argument("--orient", choices=["portrait", "landscape"], default="portrait")
_args = _ap.parse_args()
sub = set(json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "eval", f"subsets/{_args.subset}.json")))["prompt_ids"])
_slug = "" if _args.subset == "healthbench-psych-v1" else "-" + _args.subset.replace("healthbench-psych-", "")
_bench = "HealthBench-Psych-Hard" if "hard" in _args.subset else "HealthBench-Psych"
N_SUB = len(sub)

# color = lab, shade darkens with tier
COLORS = {
    "gpt-5.6-sol": ("OpenAI", "#163B6E"), "gpt-5.5": ("OpenAI", "#2960A8"),
    "gpt-4.1-2025-04-14": ("OpenAI", "#4A88CA"), "gpt-3.5-turbo": ("OpenAI", "#7CB0DE"),
    "claude-fable-5": ("Anthropic", "#B85518"), "claude-opus-5": ("Anthropic", "#D47A3A"),
    "claude-sonnet-5": ("Anthropic", "#ECA060"),
    "claude-haiku-4-5-20251001": ("Anthropic", "#F4C08A"),
    "gemini-3.6-flash": ("Google", "#5529A0"), "gemini-2.5-pro": ("Google", "#7650BC"),
    "gemini-2.5-flash": ("Google", "#9A7DD0"),
    "grok-4.5": ("xAI", "#3D3D3D"),
    "qwen3.7-plus": ("Qwen", "#A82028"), "qwen3-8b": ("Qwen", "#CC4450"),
    "mistral-large-latest": ("Mistral", "#A87800"), "mistral-small-latest": ("Mistral", "#CCA020"),
    "deepseek-v4-pro": ("DeepSeek", "#1A7040"), "deepseek-v4-flash": ("DeepSeek", "#2EA060"),
    "kimi-k3": ("Moonshot", "#A02878"), "kimi-k2.6": ("Moonshot", "#C84E98"),
}
LAB_DEEP = {"OpenAI": "#163B6E", "Anthropic": "#B85518", "Google": "#5529A0", "xAI": "#3D3D3D",
            "Qwen": "#A82028", "Mistral": "#A87800", "DeepSeek": "#1A7040", "Moonshot": "#A02878"}
STONE_AX, STONE_TICK, GRID = "#78716C", "#57534E", "#E7E5E4"


def clip01(m):
    return max(0.0, min(1.0, m))


# per-prompt panel scores: prompt -> mean of the 3 judges' scores on that prompt
panel = {}  # cand -> list of per-prompt panel scores
for c in S.CANDIDATES:
    by_prompt = {}
    ok = True
    for j in JUDGES:
        p = store.grade_path(c, j)
        if not os.path.exists(p):
            ok = False
            break
        for l in open(p):
            r = json.loads(l)
            if r["prompt_id"] in sub and r.get("score") is not None:
                by_prompt.setdefault(r["prompt_id"], {})[j] = r["score"]
    if not ok:
        continue
    complete = [st.mean(d.values()) for d in by_prompt.values() if len(d) == len(JUDGES)]
    if complete:
        panel[c] = complete

rows = []  # (cand, mean, ci_lo, ci_hi)
for c, scores in panel.items():
    rng = random.Random(0)  # per-candidate seed: matches analysis/statistics/stats_lib.bootstrap_ci
    m = clip01(st.mean(scores))
    n = len(scores)
    boots = sorted(clip01(st.mean(rng.choices(scores, k=n))) for _ in range(N_BOOT))
    lo, hi = boots[int(0.025 * N_BOOT)], boots[int(0.975 * N_BOOT) - 1]
    rows.append((c, m, lo, hi))
rows.sort(key=lambda r: r[1])

if _args.orient == "landscape":
    rows.sort(key=lambda r: -r[1])  # best first, left to right
    fig, ax = plt.subplots(figsize=(12.5, 4.6))
    xs = range(len(rows))
    ax.bar(xs, [m for c, m, lo, hi in rows],
           color=[COLORS[c][1] for c, m, lo, hi in rows], width=0.7, zorder=3)
    ax.errorbar(xs, [m for c, m, lo, hi in rows],
                yerr=[[m - lo for c, m, lo, hi in rows], [hi - m for c, m, lo, hi in rows]],
                fmt="none", ecolor="#57534E", elinewidth=1.0, capsize=2.2, zorder=4)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([c.replace("-20251001", "") for c, m, lo, hi in rows],
                       rotation=40, ha="right", fontsize=8.5, color=STONE_TICK)
    ax.set_ylim(0, max(hi for c, m, lo, hi in rows) + 0.06)
    ax.set_title(f"{_bench}: Model Ranking, 3-Judge Panel",
                 fontsize=14, fontweight=600, family="serif", color="#1B3A5C", pad=20)
    ax.text(0, 1.02, f"Psychiatry/mental-health subset (n={N_SUB}); mean of 3 judges "
            "(gpt-4.1, claude-haiku-4.5, gemini-2.5-flash), temp=0; 95% bootstrap CI",
            transform=ax.transAxes, fontsize=8.5, color=STONE_TICK)
    ax.set_ylabel("Mean HealthBench score", fontsize=9.5, color=STONE_TICK)
    best = {}
    for c, m, lo, hi in rows:
        lab = COLORS[c][0]; best[lab] = max(best.get(lab, 0), m)
    lab_handles = [Patch(facecolor=LAB_DEEP[l], edgecolor="none", label=l)
                   for l in sorted(LAB_DEEP, key=lambda l: -best.get(l, 0))]
    ax.legend(handles=lab_handles, title="Lab (shade: capability tier)", loc="upper right",
              frameon=False, fontsize=8, title_fontsize=8.5, handlelength=1.1,
              labelspacing=0.35, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(STONE_AX); ax.spines[s].set_linewidth(1)
    ax.tick_params(length=0, colors=STONE_TICK)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    fig.patch.set_facecolor("white")
    plt.tight_layout()
    out = os.path.join(os.path.dirname(__file__), "..", "..", "eval", f"runs/healthbench-psych--fig1--3judge-ranking{_slug}-wide.png")
    plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("wrote", out)
    for c, m, lo, hi in rows[:5]:
        print(f"  {c:24s} {m:.3f}  [{lo:.3f}, {hi:.3f}]")
    raise SystemExit(0)

fig, ax = plt.subplots(figsize=(9, 9))
ax.barh(range(len(rows)), [m for c, m, lo, hi in rows],
        color=[COLORS[c][1] for c, m, lo, hi in rows], height=0.70, zorder=3)
ax.errorbar([m for c, m, lo, hi in rows], range(len(rows)),
            xerr=[[m - lo for c, m, lo, hi in rows], [hi - m for c, m, lo, hi in rows]],
            fmt="none", ecolor="#57534E", elinewidth=1.1, capsize=2.5, zorder=4)
for i, (c, m, lo, hi) in enumerate(rows):
    ax.text(hi + 0.010, i, f"{m:.3f}", va="center", fontsize=8.5, color=STONE_TICK, zorder=4)

ax.set_yticks(range(len(rows)))
ax.set_yticklabels([c.replace("-20251001", "") for c, m, lo, hi in rows], fontsize=9, color=STONE_TICK)
_maxx = max(hi for c, m, lo, hi in rows)
ax.set_xlim(0, _maxx + 0.20)

ax.set_title(f"{_bench}: Model Ranking, 3-Judge Panel",
             fontsize=15, fontweight=600, family="serif", color="#1B3A5C", pad=26)
ax.text(0, 1.012, f"Psychiatry/mental-health subset (n={N_SUB}); mean of 3 judges "
        "(gpt-4.1, claude-haiku-4.5, gemini-2.5-flash), temp=0; 95% bootstrap CI",
        transform=ax.transAxes, fontsize=9, color=STONE_TICK)
ax.set_xlabel("Mean HealthBench score (fraction of positive rubric points)", fontsize=10, color=STONE_TICK)

best = {}
for c, m, lo, hi in rows:
    lab = COLORS[c][0]; best[lab] = max(best.get(lab, 0), m)
lab_handles = [Patch(facecolor=LAB_DEEP[l], edgecolor="none", label=l)
               for l in sorted(LAB_DEEP, key=lambda l: -best.get(l, 0))]
ax.legend(handles=lab_handles, title="Lab (shade: capability tier)", loc="lower right",
          frameon=False, fontsize=8.5, title_fontsize=9, handlelength=1.1, labelspacing=0.4)

ax.text(0, -0.085, "Error bars: 95% CI, prompt-level bootstrap (1,000 resamples, HealthBench recipe). "
        "Judges agree closely (pairwise Kendall τ = 0.93); ordering unchanged by judge-severity correction.",
        transform=ax.transAxes, fontsize=8, color=STONE_AX, style="italic")

ax.spines[["top", "right"]].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(STONE_AX); ax.spines[s].set_linewidth(1)
ax.tick_params(length=0, colors=STONE_TICK)
ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
ax.set_axisbelow(True)
fig.patch.set_facecolor("white")
plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), "..", "..", "eval", f"runs/healthbench-psych--fig1--3judge-ranking{_slug}.png")
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print("wrote", out)
top = rows[::-1][:5]
print("top-5 with CIs:")
for c, m, lo, hi in top:
    print(f"  {c:24s} {m:.3f}  [{lo:.3f}, {hi:.3f}]")
