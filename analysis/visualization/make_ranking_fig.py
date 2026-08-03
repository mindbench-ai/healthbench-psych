"""Shareable PNG of a single-judge ranking (make_panel_fig.py draws the 3-judge panel).

Color encodes lab, shade the tier within a lab; model names on the y-axis carry the
non-color encoding, with a lab legend as backup.

Run with the .venv-fig interpreter (has matplotlib).
"""
import argparse, json, os, sys, statistics as st
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "eval")))
from lib import samplers as S, store
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]
matplotlib.rcParams["font.serif"] = ["Source Serif 4", "Source Serif Pro", "Georgia", "DejaVu Serif"]

_ap = argparse.ArgumentParser()
_ap.add_argument("--judge", default="claude-haiku-4-5-20251001")
_ap.add_argument("--subset", default="healthbench-psych-v1")
_args = _ap.parse_args()
JUDGE = _args.judge
JUDGE_DISP = JUDGE.replace("-20251001", "")
JUDGE_SLUG = {"claude-haiku-4-5-20251001": "haiku", "gemini-2.5-flash": "gemini",
              "gpt-4.1-2025-04-14": "gpt41"}.get(JUDGE, JUDGE.replace(".", "").replace("-", "")[:10])
sub = set(json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "eval", f"subsets/{_args.subset}.json")))["prompt_ids"])
N_SUB = len(sub)

# (lab, hex); shade darkens with tier within a lab
COLORS = {
    # OpenAI
    "gpt-5.6-sol": ("OpenAI", "#163B6E"), "gpt-5.5": ("OpenAI", "#2960A8"),
    "gpt-4.1-2025-04-14": ("OpenAI", "#4A88CA"), "gpt-3.5-turbo": ("OpenAI", "#7CB0DE"),
    # Anthropic
    "claude-fable-5": ("Anthropic", "#B85518"), "claude-opus-5": ("Anthropic", "#D47A3A"),
    "claude-sonnet-5": ("Anthropic", "#ECA060"),
    "claude-haiku-4-5-20251001": ("Anthropic", "#F4C08A"),
    # Google DeepMind
    "gemini-3.6-flash": ("Google", "#5529A0"), "gemini-2.5-pro": ("Google", "#7650BC"),
    "gemini-2.5-flash": ("Google", "#9A7DD0"),
    # xAI
    "grok-4.5": ("xAI", "#3D3D3D"),
    # Qwen
    "qwen3.7-plus": ("Qwen", "#A82028"), "qwen3-8b": ("Qwen", "#CC4450"),
    # Mistral
    "mistral-large-latest": ("Mistral", "#A87800"), "mistral-small-latest": ("Mistral", "#CCA020"),
    # DeepSeek
    "deepseek-v4-pro": ("DeepSeek", "#1A7040"), "deepseek-v4-flash": ("DeepSeek", "#2EA060"),
    # Moonshot
    "kimi-k3": ("Moonshot", "#A02878"), "kimi-k2.6": ("Moonshot", "#C84E98"),
}
LAB_DEEP = {"OpenAI": "#163B6E", "Anthropic": "#B85518", "Google": "#5529A0", "xAI": "#3D3D3D",
            "Qwen": "#A82028", "Mistral": "#A87800", "DeepSeek": "#1A7040", "Moonshot": "#A02878"}

STONE_AX, STONE_TICK, GRID = "#78716C", "#57534E", "#E7E5E4"

rows = []
for c in S.CANDIDATES:
    p = store.grade_path(c, JUDGE)
    if not os.path.exists(p):
        continue
    scs = [json.loads(l)["score"] for l in open(p)
           if json.loads(l)["prompt_id"] in sub and json.loads(l)["score"] is not None]
    if scs:
        rows.append((c, len(scs), st.mean(scs)))
rows.sort(key=lambda r: r[2])  # ascending -> best at top of horizontal bars

def disp_label(c, n):
    name = c.replace("-20251001", "")
    if c == JUDGE:
        name += "  (judge)"
    if n < N_SUB:
        name += f"  (n={n})"
    return name

fig, ax = plt.subplots(figsize=(9, 9))
bar_colors = [COLORS[c][1] for c, n, m in rows]
ax.barh(range(len(rows)), [m for c, n, m in rows], color=bar_colors, height=0.70, zorder=3)
ax.set_yticks(range(len(rows)))
ax.set_yticklabels([disp_label(c, n) for c, n, m in rows], fontsize=9, color=STONE_TICK)
# adaptive x-limit: longest bar + room for its value label + a right gutter the
# bottom-right legend lives in (so it never overlaps bars or labels, any judge)
_maxm = max(m for c, n, m in rows)
ax.set_xlim(0, _maxm + 0.20)

for i, (c, n, m) in enumerate(rows):
    ax.text(m + 0.006, i, f"{m:.3f}", va="center", fontsize=8.5, color=STONE_TICK, zorder=4)

ax.set_title("HealthBench-Psych: Model Ranking",
             fontsize=15, fontweight=600, family="serif", color="#1B3A5C", pad=26)
ax.text(0, 1.012, f"Psychiatry/mental-health subset (n={N_SUB}); judge: {JUDGE_DISP}, temp=0; 1 of 3 judges",
        transform=ax.transAxes, fontsize=9, color=STONE_TICK)
ax.set_xlabel("Mean HealthBench score (fraction of positive rubric points)", fontsize=10, color=STONE_TICK)

# Lab legend, ordered by each lab's best score (descending)
best = {}
for c, n, m in rows:
    lab = COLORS[c][0]; best[lab] = max(best.get(lab, 0), m)
order = sorted(LAB_DEEP, key=lambda l: -best.get(l, 0))
handles = [Patch(facecolor=LAB_DEEP[l], edgecolor="none", label=l) for l in order]
ax.legend(handles=handles, title="Lab (shade: capability tier)", loc="lower right",
          frameon=False, fontsize=8.5, title_fontsize=9, handlelength=1.1, labelspacing=0.4)

ax.text(0, -0.085,
        f"Provisional: single judge ({JUDGE_DISP} is itself a candidate). Severity-correction + "
        "self-preference audit pending the full 3-judge panel.",
        transform=ax.transAxes, fontsize=8, color=STONE_AX, style="italic")

ax.spines[["top", "right"]].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(STONE_AX); ax.spines[s].set_linewidth(1)
ax.tick_params(length=0, colors=STONE_TICK)
ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
ax.set_axisbelow(True)
fig.patch.set_facecolor("white")
plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), "..", "..", "eval", f"runs/healthbench-psych--fig1--{JUDGE_SLUG}-ranking.png")
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print("wrote", out)
