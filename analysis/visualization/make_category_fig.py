"""Fig. 2 — clinician category decomposition of the HealthBench-Psych subset.

Modal category = the category >=2 of the Y-voting panel clinicians assigned (round-1 trio for
round-1 items, same trio for round-2 additions); items without a category majority appear as
their own bar. Wide landscape layout with single-series navy bars, matching the fig-1 wide
design language.

Run with .venv-fig/bin/python. Usage: make_category_fig.py [--subset healthbench-psych-v1]
"""
import argparse, collections, glob, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "eval")))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]
matplotlib.rcParams["font.serif"] = ["Source Serif 4", "Source Serif Pro", "Georgia", "DejaVu Serif"]

_ap = argparse.ArgumentParser()
_ap.add_argument("--subset", default="healthbench-psych-v1")
_args = _ap.parse_args()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sub = json.load(open(os.path.join(ROOT, "eval/subsets", f"{_args.subset}.json")))
ids = set(sub["prompt_ids"])
r2new = set(sub.get("round2_added_prompt_ids", []))

PRETTY = {
    "perinatal_mh": "Perinatal mental health", "anxiety": "Anxiety",
    "psychiatric_medication": "Psychiatric medication", "mood_depression_bipolar": "Mood (depression/bipolar)",
    "sleep": "Sleep", "cognitive_neuro": "Cognitive / neurocognitive",
    "neurodevelopmental_adhd": "ADHD / neurodevelopmental", "substance_use": "Substance use",
    "suicidality_self_harm": "Suicidality / self-harm", "other_mh": "Other mental health",
    "psychotherapy_access": "Psychotherapy / access", "eating_disorder": "Eating disorders",
    "stress_adjustment": "Stress / adjustment", "psychosis": "Psychosis",
    "trauma_ptsd": "Trauma / PTSD", "personality": "Personality",
    "(no category majority)": "No category majority",
}
NAVY, TEAL, STONE, AMBER = "#1B3A5C", "#4A8DB0", "#78716C", "#D97706"
STONE_AX, STONE_TICK, GRID = "#78716C", "#57534E", "#E7E5E4"

ratings = collections.defaultdict(dict)
for f in sorted(glob.glob(os.path.join(ROOT, "provenance", "review", "results", "round1", "*.json"))):
    d = json.load(open(f))
    for x in d["ratings"]:
        if x["prompt_id"] in ids and x["is_mental_health"] == "Y":
            ratings[x["prompt_id"]][d["reviewer"]] = x["category"]
for f in sorted(glob.glob(os.path.join(ROOT, "provenance", "review", "results", "round2", "*.json"))):
    d = json.load(open(f))
    for x in d["ratings"]:
        if x["prompt_id"] in r2new and x["is_mental_health"] == "Y":
            ratings[x["prompt_id"]][d["reviewer"]] = x["category"]

modal = collections.Counter()
for pid in ids:
    c = collections.Counter(ratings.get(pid, {}).values())
    top, n = c.most_common(1)[0] if c else ("none", 0)
    modal[top if n >= 2 else "(no category majority)"] += 1
total = sum(modal.values())
assert total == len(ids), (total, len(ids))

# hard-subset modal counts over the same per-conversation modal assignments
hard_ids = set(json.load(open(os.path.join(ROOT, "eval/subsets", "healthbench-psych-hard-v1.json")))["prompt_ids"])
modal_by_conv = {}
for pid in ids:
    c = collections.Counter(ratings.get(pid, {}).values())
    top = c.most_common(1)
    modal_by_conv[pid] = top[0][0] if top and top[0][1] >= 2 else "(no category majority)"
hard_counts = collections.Counter(modal_by_conv[p] for p in ids & hard_ids)

rows = sorted(modal.items(), key=lambda kv: -kv[1])  # full-set order fixes both panels
labels = [PRETTY.get(k, k) for k, v in rows]
cats_order = [k for k, v in rows]
full_vals = [v for k, v in rows]
hard_vals = [hard_counts.get(k, 0) for k in cats_order]
n_hard = sum(hard_vals)

fig, axes = plt.subplots(2, 1, figsize=(12.5, 7.2), sharex=True)
for ax, vals, label in [(axes[0], full_vals, f"HealthBench-Psych (n = {total})"),
                        (axes[1], hard_vals, f"HealthBench-Psych-Hard (n = {n_hard})")]:
    xs = range(len(cats_order))
    ax.bar(xs, vals, color=NAVY, width=0.7, zorder=3)
    for i, v in enumerate(vals):
        if v:
            ax.text(i, v + max(vals) * 0.02, str(v), ha="center", fontsize=8, color=STONE_TICK)
    ax.set_ylim(0, max(vals) * 1.14)
    ax.set_ylabel("Conversations", fontsize=9.5, color=STONE_TICK)
    ax.set_title(label, loc="left", fontsize=10.5, fontweight="bold", color=NAVY, pad=6)
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(STONE_AX); ax.spines[sp].set_linewidth(1)
    ax.tick_params(length=0, colors=STONE_TICK)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
axes[1].set_xticks(range(len(cats_order)))
axes[1].set_xticklabels(labels, rotation=40, ha="right", fontsize=8.5, color=STONE_TICK)

fig.patch.set_facecolor("white")
plt.tight_layout(rect=(0, 0, 1, 0.925))
_x0 = axes[0].get_position().x0
fig.text(_x0, 0.985, "HealthBench-Psych: Clinician Category Decomposition",
         ha="left", va="top", fontsize=14, fontweight=600, family="serif", color=NAVY)
fig.text(_x0, 0.945, f"Modal category across the reviewing clinicians (at least two agree); "
         "categories follow the full-set ordering in both panels",
         ha="left", va="top", fontsize=8.5, color=STONE_TICK)
out = os.path.join(ROOT, "eval/runs/healthbench-psych--fig2--category-decomposition.png")
plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
print("wrote", out)
top_hard = max(((k, v) for k, v in hard_counts.items() if k != "(no category majority)"), key=lambda kv: kv[1])
print(f"hard: n={n_hard}, largest category {top_hard[0]} = {top_hard[1]} ({100*top_hard[1]/n_hard:.1f}%); "
      f"no-majority {hard_counts.get('(no category majority)', 0)}")
