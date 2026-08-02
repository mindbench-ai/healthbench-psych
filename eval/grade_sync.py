"""Synchronous (online-API) grading — a resilient fallback for when a provider's
BATCH queue is throttled/stalled (e.g. Google native batch).

Grades the SAME deterministic work-list as grade.py (prompt-keyed, idempotent: skips
already-graded (cand,prompt)), but via the online /chat/completions sampler with a
thread pool instead of the batch API. The online sampler's _post already retries
URLError/timeouts, so transient network blips pause-and-retry instead of crashing.

--skip-first-chunk drops the first deterministic chunk from the work-list: use it when
that exact chunk is still in-flight as a batch (so we don't duplicate it — it gets
recovered from the batch separately). The chunk boundary matches grade.py exactly.

Reuses hb_grade (build_grader_prompt/robust_verdict/calculate_score), store (idempotent
append + global spend), prices (cost_of). Same scoring, same grader prompt as the batch path.

CLI: python eval/grade_sync.py --judge gemini-2.5-flash --subset includes_majority \
        --skip-first-chunk --workers 12 --max-cost 250
"""
import argparse
import concurrent.futures as cf
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import hb_grade  # noqa: E402
from lib import prices  # noqa: E402
import run_eval as R  # noqa: E402
from lib import samplers as S  # noqa: E402
from lib import store  # noqa: E402

CHUNK_SPECS = 25000          # must match grade.py (for --skip-first-chunk alignment)
MAX_BATCH_BYTES = 100_000_000
_TMPL_B = len(hb_grade.GRADER_TEMPLATE)


def load_examples(prompt_ids, source):
    ex = {}
    for line in open(source):
        import json
        d = json.loads(line)
        if d["prompt_id"] in prompt_ids:
            ex[d["prompt_id"]] = d
    return ex


def build_worklist(judge, prompt_ids, examples, candidates, skip_first_chunk):
    """Deterministic (cand-order x sorted-pid) ungraded groups, matching grade.py."""
    groups = []
    for cand in candidates:
        resp = store.load_map(store.resp_path(cand))
        if not resp:
            continue
        gdone = store.load_done(store.grade_path(cand, judge))
        for pid in sorted(prompt_ids):
            if pid not in resp or pid in gdone:
                continue
            rubrics = [hb_grade.RubricItem.from_dict(r) for r in examples[pid]["rubrics"]]
            convo = hb_grade.render_conversation(examples[pid]["prompt"], resp[pid]["response_text"])
            groups.append((cand, pid, rubrics, convo))
    if skip_first_chunk:
        def gbytes(g):
            return len(g[2]) * (_TMPL_B + len(g[3].encode("utf-8")) + 300)
        cnt, cby, cut = 0, 0, len(groups)
        for i, g in enumerate(groups):
            m, b = len(g[2]), gbytes(g)
            if i > 0 and (cnt + m > CHUNK_SPECS or cby + b > MAX_BATCH_BYTES):
                cut = i
                break
            cnt += m; cby += b
        dropped = groups[:cut]
        print(f"  --skip-first-chunk: dropped {len(dropped)} groups / "
              f"{sum(len(g[2]) for g in dropped)} gradings (the in-flight batch — recover separately)")
        groups = groups[cut:]
    return groups


def grade_group(judge_fn, g):
    """Grade one (cand,pid,rubrics,convo): all rubrics at temp=0 with robust_verdict +
    bounded retry. Returns (cand, record) or (cand, None) if a rubric never yields a verdict."""
    cand, pid, rubrics, convo = g
    grades = []
    for item in rubrics:
        d, tries = {}, 0
        while not isinstance(d.get("criteria_met"), bool) and tries < 6:
            try:
                d = hb_grade.robust_verdict(judge_fn(hb_grade.build_grader_prompt(convo, item)))
            except Exception as e:
                if S.is_quota_error(str(e)) or "quota/balance" in str(e):
                    raise  # balance exhausted -> propagate to graceful stop
                d = {}
            tries += 1
        if not isinstance(d.get("criteria_met"), bool):
            return cand, pid, None
        grades.append(d)
    score = hb_grade.calculate_score(rubrics, grades)
    return cand, pid, {"prompt_id": pid, "score": score, "grades": grades}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--source", default=R.SOURCE)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--flush-every", type=int, default=200)
    ap.add_argument("--skip-first-chunk", action="store_true",
                    help="drop the first deterministic chunk (still in-flight as a batch)")
    ap.add_argument("--max-cost", type=float, default=0.0,
                    help="stop when GLOBAL grade spend reaches this ($); 0 = off")
    ap.add_argument("--limit", type=int, default=0, help="smoke-test: only grade N groups")
    args = ap.parse_args()

    judge = args.judge
    if judge not in S.REGISTRY:
        raise SystemExit(f"no sampler for judge {judge}")
    _, prompt_ids = R.load_subset(args.subset)
    prompt_ids = set(prompt_ids)
    examples = load_examples(prompt_ids, args.source)
    cands = S.CANDIDATES if not args.candidates else [c.strip() for c in args.candidates.split(",")]

    groups = build_worklist(judge, prompt_ids, examples, cands, args.skip_first_chunk)
    if args.limit:
        groups = groups[:args.limit]
    total_specs = sum(len(g[2]) for g in groups)
    print(f"[{judge}] SYNC | {len(groups)} (cand,prompt) groups / {total_specs} gradings | "
          f"{args.workers} workers | global grade spend so far ${store.spend_to_date('grade'):.2f}")
    if not groups:
        print(f"[{judge}] nothing to do."); return

    smp = S.REGISTRY[judge]
    judge_fn = smp
    by_cand, done, skipped = {}, 0, 0
    last_usage = dict(smp.usage.as_dict())

    def flush_and_cost():
        nonlocal by_cand, last_usage
        written = 0
        for cand, recs in by_cand.items():
            written += store.append(store.grade_path(cand, judge), recs)
        by_cand = {}
        u = smp.usage.as_dict()
        delta = {k: u[k] - last_usage.get(k, 0) for k in ("input", "cached", "output")}
        last_usage = dict(u)
        cost = prices.cost_of(judge, delta, batch=False)
        store.record_spend("grade", judge, cost)
        return written, cost

    stop = False
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(grade_group, judge_fn, g): g for g in groups}
        try:
            for fut in cf.as_completed(futs):
                try:
                    cand, pid, rec = fut.result()
                except Exception as e:  # quota/balance -> stop cleanly
                    if S.is_quota_error(str(e)) or "quota/balance" in str(e):
                        print(f"[{judge}] STOP: account balance/quota exhausted — flushing partial, "
                              f"re-run to resume (idempotent).")
                        stop = True
                        break
                    raise
                if rec is None:
                    store.log_error(phase="grade", judge=judge, candidate=cand, prompt_id=pid,
                                    kind="grade_no_verdict", detail="sync: no criteria_met after retries — SKIPPED")
                    skipped += 1
                    continue
                by_cand.setdefault(cand, []).append(rec)
                done += 1
                if done % args.flush_every == 0:
                    w, cost = flush_and_cost()
                    spent = store.spend_to_date("grade")
                    print(f"  [{done}/{len(groups)}] flushed {w} | +${cost:.2f} | global ${spent:.2f} | {skipped} skipped")
                    if args.max_cost and spent >= args.max_cost:
                        print(f"[{judge}] STOP: global grade spend ${spent:.2f} >= cap ${args.max_cost:.0f} — "
                              f"remaining NOT graded (re-run to resume).")
                        stop = True
                        break
        finally:
            if stop:
                for f in futs:
                    f.cancel()
    w, cost = flush_and_cost()
    print(f"[{judge}] {'STOPPED' if stop else 'done'}. final flush {w} | +${cost:.2f} | "
          f"{done} graded, {skipped} skipped | global grade spend ${store.spend_to_date('grade'):.2f}")


if __name__ == "__main__":
    main()
