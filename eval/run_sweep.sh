#!/usr/bin/env bash
# Sweep orchestrator for the HealthBench-Psych leaderboard.
#
#   Phase 1  generate  — one process PER PROVIDER (candidate side)
#   Phase 2  grade     — one process PER JUDGE   (judge side)
#   then     aggregate — candidate x judge matrix + severity-corrected stats
#
# Each provider/judge is its own OS process with its own log, so if one runs out
# of API credits you can `kill <pid>` just that one; the others keep going. Every
# step is idempotent + prompt-keyed (store.py), so re-running resumes and a
# round-2 subset only does the new prompts. Concurrency is process-level (this
# script) + batch-parallelism inside each process — no in-Python async.
#
# Usage:
#   eval/run_sweep.sh all   [subset]            # gen -> grade -> aggregate
#   eval/run_sweep.sh gen   [subset] [provider] # generation only (opt. one provider)
#   eval/run_sweep.sh grade [subset] [judge]    # grading only (opt. one judge)
#   eval/run_sweep.sh agg   [subset]            # aggregate only
# subset defaults to includes_majority.
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env 2>/dev/null; set +a

PHASE="${1:-all}"
SUBSET="${2:-healthbench-psych-v1}"
ONLY="${3:-}"
LOGDIR="eval/runs/logs"; mkdir -p "$LOGDIR"
GEN_PROVIDERS="openai anthropic google mistral deepseek moonshot xai dashscope"
JUDGES="gpt-4.1-2025-04-14 claude-haiku-4-5-20251001 gemini-2.5-flash"

phase_gen() {
  local cap="${GEN_MAX_COST:-200}"
  echo "=== PHASE 1: generate ($SUBSET)  [global gen cost cap \$$cap] ==="
  local pids=() targets="${ONLY:-$GEN_PROVIDERS}"
  for p in $targets; do
    python3 eval/generate.py --provider "$p" --subset "$SUBSET" --max-cost "$cap" \
        > "$LOGDIR/gen_$p.log" 2>&1 &
    echo "  gen $p  -> pid $!  (tail -f $LOGDIR/gen_$p.log)"
    pids+=($!)
  done
  wait "${pids[@]}"; echo "=== generation phase done ==="
}

phase_grade() {
  local cap="${GRADE_MAX_COST:-500}"
  echo "=== PHASE 2: grade ($SUBSET)  [global grade cost cap \$$cap] ==="
  local pids=() targets="${ONLY:-$JUDGES}"
  for j in $targets; do
    python3 eval/grade.py --judge "$j" --subset "$SUBSET" --max-cost "$cap" \
        > "$LOGDIR/grade_$j.log" 2>&1 &
    echo "  grade $j  -> pid $!  (tail -f $LOGDIR/grade_$j.log)"
    pids+=($!)
  done
  wait "${pids[@]}"; echo "=== grading phase done ==="
}

case "$PHASE" in
  gen)   phase_gen ;;
  grade) phase_grade ;;
  agg)   python3 eval/aggregate.py --subset "$SUBSET" ;;
  all)   phase_gen; phase_grade; echo "=== AGGREGATE ==="; python3 eval/aggregate.py --subset "$SUBSET" ;;
  *) echo "usage: run_sweep.sh {all|gen|grade|agg} [subset] [only-provider-or-judge]"; exit 1 ;;
esac
