"""Prompt-keyed, append-only stores for the sweep — the mechanism that makes
round 2 free of duplicate work.

Responses live per candidate; grades live per (candidate, judge). Each is a JSONL
keyed by prompt_id. `load_done` returns the prompt_ids already present, so a
generate/grade pass only processes prompts NOT yet done. A larger subset (round 2
adds prompts) therefore reuses everything from round 1 and only does the delta.

Files (committed for provenance):
  runs/responses/<candidate>.jsonl          {prompt_id, response_text, [finish_reason]}
  runs/grades/<candidate>__<judge>.jsonl     {prompt_id, score, grades}
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESP_DIR = os.path.join(ROOT, "eval", "runs", "responses")
GRADE_DIR = os.path.join(ROOT, "eval", "runs", "grades")
ERROR_LOG = os.path.join(ROOT, "eval", "runs", "errors.jsonl")
SPEND_LOG = os.path.join(ROOT, "eval", "runs", "spend.jsonl")


def record_spend(phase, who, cost):
    """Append an actual-cost record ($) to a shared, append-only spend ledger.
    The spend guard reads its cumulative sum across all processes."""
    os.makedirs(os.path.dirname(SPEND_LOG), exist_ok=True)
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "phase": phase, "who": who, "cost": round(cost, 4)}
    with open(SPEND_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def spend_to_date(phase=None):
    """Cumulative $ recorded so far (optionally for one phase). Shared across the
    parallel provider/judge processes, so it's a GLOBAL running total."""
    if not os.path.exists(SPEND_LOG):
        return 0.0
    total = 0.0
    for line in open(SPEND_LOG):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if phase is None or r.get("phase") == phase:
            total += r.get("cost", 0.0)
    return total


def log_error(**fields):
    """Append one timestamped anomaly record to a DURABLE, append-only log (never
    truncated) — the transparency/audit trail for the paper. Typical fields:
    phase ('generate'|'grade'), kind (e.g. 'call_failed', 'empty_response',
    'grade_fallback', 'grade_no_verdict'), candidate, judge, prompt_id, detail."""
    os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), **fields}
    with open(ERROR_LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _safe(name):
    return name.replace("/", "-")


def resp_path(candidate):
    return os.path.join(RESP_DIR, f"{_safe(candidate)}.jsonl")


def grade_path(candidate, judge):
    return os.path.join(GRADE_DIR, f"{_safe(candidate)}__{_safe(judge)}.jsonl")


def load_done(path):
    """Set of prompt_ids already recorded in a store file (empty if absent)."""
    if not os.path.exists(path):
        return set()
    done = set()
    for line in open(path):
        line = line.strip()
        if line:
            done.add(json.loads(line)["prompt_id"])
    return done


def load_map(path):
    """prompt_id -> full record for a store file."""
    out = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["prompt_id"]] = r
    return out


def append(path, records):
    """Append records (dicts with prompt_id) as JSONL; skips prompt_ids already
    present so re-runs are idempotent. Returns the number actually written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    done = load_done(path)
    n = 0
    with open(path, "a") as f:
        for r in records:
            if r["prompt_id"] in done:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            done.add(r["prompt_id"])
            n += 1
    return n
