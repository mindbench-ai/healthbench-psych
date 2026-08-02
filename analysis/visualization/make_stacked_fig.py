"""Paper figure: HealthBench-Psych and HealthBench-Psych-Hard as stacked panels.

Two landscape bar panels, one per subset, sharing a normalized y-axis and a single model
order (sorted by the FULL-set panel mean) so each model's bars align vertically across
panels. Bars = 3-judge mean; whiskers = 95% conversation-level bootstrap CI.

Run with .venv-fig/bin/python. Output: eval/runs/healthbench-psych--fig1--stacked-v1-hard.png
"""
import json, os, random, sys, statistics as st
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
SUBSETS = [("healthbench-psych-v1", "HealthBench-Psych (n = 610)"),
           ("healthbench-psych-hard-v1", "HealthBench-Psych-Hard (n = 119)")]
N_BOOT = 1000

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


def panel_stats(subset):
    """cand -> (mean, lo, hi) over the subset's per-prompt 3-judge panel scores."""
    ids = set(json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "eval", "subsets", f"{subset}.json")))["prompt_ids"])
    out = {}
    for c in S.CANDIDATES:
        rng = random.Random(0)  # per-candidate seed: matches stats_lib.bootstrap_ci
        by_prompt = {}
        for j in JUDGES:
            for l in open(store.grade_path(c, j)):
                r = json.loads(l)
                if r["prompt_id"] in ids and r.get("score") is not None:
                    by_prompt.setdefault(r["prompt_id"], []).append(r["score"])
        scores = [st.mean(v) for v in by_prompt.values() if len(v) == len(JUDGES)]
        if not scores:
            continue
        m = clip01(st.mean(scores))
        boots = sorted(clip01(st.mean(rng.choices(scores, k=len(scores)))) for _ in range(N_BOOT))
        out[c] = (m, boots[int(0.025 * N_BOOT)], boots[int(0.975 * N_BOOT) - 1])
    return out


stats = {sub: panel_stats(sub) for sub, _ in SUBSETS}
order = sorted(stats[SUBSETS[0][0]], key=lambda c: -stats[SUBSETS[0][0]][c][0])  # full-set order, both panels
ymax = max(hi for d in stats.values() for _, _, hi in d.values()) + 0.05

fig, axes = plt.subplots(2, 1, figsize=(12.5, 7.6), sharex=True)
for ax, (sub, label) in zip(axes, SUBSETS):
    d = stats[sub]
    xs = range(len(order))
    ax.bar(xs, [d[c][0] for c in order], color=[COLORS[c][1] for c in order], width=0.7, zorder=3)
    ax.errorbar(xs, [d[c][0] for c in order],
                yerr=[[d[c][0] - d[c][1] for c in order], [d[c][2] - d[c][0] for c in order]],
                fmt="none", ecolor="#57534E", elinewidth=1.0, capsize=2.2, zorder=4)
    ax.set_ylim(0, ymax)
    ax.set_ylabel("Mean HealthBench score", fontsize=9.5, color=STONE_TICK)
    ax.set_title(label, loc="left", fontsize=10.5, fontweight="bold", color="#1B3A5C", pad=6)
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(STONE_AX); ax.spines[sp].set_linewidth(1)
    ax.tick_params(length=0, colors=STONE_TICK)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

axes[1].set_xticks(range(len(order)))
axes[1].set_xticklabels([c.replace("-20251001", "") for c in order],
                        rotation=40, ha="right", fontsize=8.5, color=STONE_TICK)

best = {c: stats[SUBSETS[0][0]][c][0] for c in order}
lab_best = {}
for c, m in best.items():
    lab = COLORS[c][0]; lab_best[lab] = max(lab_best.get(lab, 0), m)
handles = [Patch(facecolor=LAB_DEEP[l], edgecolor="none", label=l)
           for l in sorted(LAB_DEEP, key=lambda l: -lab_best.get(l, 0))]
axes[0].legend(handles=handles, title="Lab (shade: capability tier)", loc="upper right",
               frameon=False, fontsize=8, title_fontsize=8.5, handlelength=1.1,
               labelspacing=0.35, ncol=2)

fig.patch.set_facecolor("white")
plt.tight_layout(rect=(0, 0, 1, 0.925))
_x0 = axes[0].get_position().x0  # left edge of the axes: one anchor for every text layer
fig.text(_x0, 0.985, "HealthBench-Psych and HealthBench-Psych-Hard: Model Ranking, 3-Judge Panel",
         ha="left", va="top", fontsize=14, fontweight=600, family="serif", color="#1B3A5C")
fig.text(_x0, 0.945, "Bars: mean of 3 judges (gpt-4.1, claude-haiku-4.5, gemini-2.5-flash), temp = 0; "
         "whiskers: 95% bootstrap CI; models ordered by full-set score in both panels",
         ha="left", va="top", fontsize=8.5, color=STONE_TICK)
out = os.path.join(os.path.dirname(__file__), "..", "..", "eval", "runs/healthbench-psych--fig1--stacked-v1-hard.png")
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print("wrote", out)
