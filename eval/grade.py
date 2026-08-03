"""Grade every candidate's responses under ONE judge over a subset.

One process per judge (= per judge-provider; kill-safe). Reads the responses that
generate.py wrote, grades each rubric item with the judge's Batch API, scores with
HealthBench's exact scorer (hb_grade), and appends per (candidate, judge) to the
prompt-keyed grades store. Idempotent: prompts already graded are skipped, so a
re-run resumes and a round-2 subset only grades the new prompts.

Grading specs are combined across all candidates and CHUNKED under the batch cap;
each chunk is scored and written before the next (resumable). custom_ids are a
running index mapped back to (candidate, prompt, rubric).

CLI: python eval/grade.py --judge gpt-4.1-2025-04-14 --subset includes_majority
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backends import openai as batch_openai  # noqa: E402
from backends import anthropic as batch_anthropic  # noqa: E402
from backends import google as batch_google  # noqa: E402
from lib import hb_grade  # noqa: E402
from lib import prices  # noqa: E402
import run_eval as R  # noqa: E402
from lib import samplers as S  # noqa: E402
from lib import store  # noqa: E402

BACKENDS = {"openai": batch_openai, "anthropic": batch_anthropic, "google": batch_google}
CHUNK_SPECS = 25000  # rubric-item requests per batch (well under provider caps; small blast radius)
MAX_BATCH_BYTES = 100_000_000  # ~100MB UTF-8 grader text -> comfortably < 256MB JSON (Anthropic limit)
EST_IN, EST_OUT = 1900, 200  # per grader-call token estimate, for pre-submit cost projection


def load_examples(prompt_ids, source):
    ex = {}
    for line in open(source):
        d = json.loads(line)
        if d["prompt_id"] in prompt_ids:
            ex[d["prompt_id"]] = d
    return ex


def flush(chunk, judge, backend, poll, log):
    """Grade a list of (cand, pid, rubrics, convo) groups: one batch, then score
    + append each group. Bounded sync fallback fills dropped/invalid verdicts."""
    specs, loc, n = [], {}, 0
    for cand, pid, rubrics, convo in chunk:
        for ri, item in enumerate(rubrics):
            cid = f"i{n}"; n += 1
            loc[cid] = (cand, pid, ri)
            gp = hb_grade.build_grader_prompt(convo, item)
            specs.append(S.spec_for(judge, cid, [{"role": "user", "content": gp}],
                                    system=S.GRADER_SYSTEM_MESSAGE, judge=True))
    results, meta = backend.run_requests(specs, poll=poll)
    verdict = {}
    for cid, (cand, pid, ri) in loc.items():
        raw = results.get(cid)
        verdict[(cand, pid, ri)] = hb_grade.robust_verdict(raw) if raw else {}

    judge_fn = S.REGISTRY[judge]
    by_cand, fb, skipped = {}, 0, 0
    for cand, pid, rubrics, convo in chunk:
        grades, ok = [], True
        for ri, item in enumerate(rubrics):
            d = verdict[(cand, pid, ri)]
            tries = 0
            while not isinstance(d.get("criteria_met"), bool) and tries < 6:
                try:  # dropped/missing verdict: re-call at temp=0; robust_verdict recovers malformed JSON
                    d = hb_grade.robust_verdict(judge_fn(hb_grade.build_grader_prompt(convo, item)))
                except Exception as e:
                    if S.is_quota_error(str(e)) or "quota/balance" in str(e):
                        raise  # let balance errors reach the stop handler in main
                    d = {}  # transient fallback error -> invalid; loop/skip, never crash the chunk
                tries += 1; fb += 1
            if not isinstance(d.get("criteria_met"), bool):
                store.log_error(phase="grade", judge=judge, candidate=cand, prompt_id=pid,
                                kind="grade_no_verdict", detail=f"rubric {ri} after {tries} retries; prompt SKIPPED (re-graded on re-run)")
                ok = False
                break  # skip just this (cand,prompt); it stays ungraded -> retried next run
            if tries > 0:
                store.log_error(phase="grade", judge=judge, candidate=cand, prompt_id=pid,
                                kind="grade_fallback", detail=f"rubric {ri}: {tries} sync retries")
            grades.append(d)
        if not ok:
            skipped += 1
            continue
        score = hb_grade.calculate_score(rubrics, grades)
        by_cand.setdefault(cand, []).append({"prompt_id": pid, "score": score, "grades": grades})
    written = 0
    for cand, recs in by_cand.items():
        written += store.append(store.grade_path(cand, judge), recs)
    usage = meta.get("usage", {"input": 0, "cached": 0, "output": 0})
    cost = prices.cost_of(judge, usage, batch=True)
    store.record_spend("grade", judge, cost)
    log(f"  flushed {len(chunk)} (cand,prompt) groups | {n} gradings | {fb} fallbacks | "
        f"wrote {written} | {skipped} skipped | ${cost:.2f}")
    return usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True, help="judge model id (must be batchable)")
    ap.add_argument("--subset", required=True)
    ap.add_argument("--source", default=R.SOURCE)
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--candidates", default=None,
                    help="comma-separated subset of candidates to grade (default: all)")
    ap.add_argument("--max-cost", type=float, default=0.0,
                    help="stop before submitting a chunk if GLOBAL grade spend + its projected "
                         "cost would exceed this ($); 0 = off")
    args = ap.parse_args()

    judge = args.judge
    provider = S.provider_of(judge)
    if provider not in BACKENDS:
        raise SystemExit(f"judge {judge} provider '{provider}' has no batch backend")
    backend = BACKENDS[provider]
    _, prompt_ids = R.load_subset(args.subset)
    examples = load_examples(prompt_ids, args.source)

    # Build the work list (lightweight), skipping ungenerated + already-graded.
    cands = S.CANDIDATES if not args.candidates else [c.strip() for c in args.candidates.split(",")]
    groups, missing_resp = [], []
    for cand in cands:
        resp = store.load_map(store.resp_path(cand))
        if not resp:
            missing_resp.append(cand)
            continue
        gdone = store.load_done(store.grade_path(cand, judge))
        for pid in sorted(prompt_ids):
            if pid not in resp or pid in gdone:
                continue
            rubrics = [hb_grade.RubricItem.from_dict(r) for r in examples[pid]["rubrics"]]
            convo = hb_grade.render_conversation(examples[pid]["prompt"], resp[pid]["response_text"])
            groups.append((cand, pid, rubrics, convo))
    if missing_resp:
        print(f"[{judge}] WARNING no responses yet (run generate.py first): {missing_resp}")
    total_specs = sum(len(g[2]) for g in groups)
    print(f"[{judge}] provider={provider} | {len(groups)} (cand,prompt) to grade | "
          f"{total_specs} rubric gradings")
    if not groups:
        print(f"[{judge}] nothing to do."); return

    pin, pout = prices.PRICES.get(judge, prices._FALLBACK)[:2]
    tmpl_b = len(hb_grade.GRADER_TEMPLATE)

    def gbytes(g):  # est UTF-8 grader-prompt bytes for a group's rubric calls (multibyte-safe)
        return len(g[2]) * (tmpl_b + len(g[3].encode("utf-8")) + 300)

    def would_exceed(chunk):
        if not args.max_cost:
            return False
        n = sum(len(g[2]) for g in chunk)  # rubric-item requests in this chunk
        projected = n * (EST_IN * pin + EST_OUT * pout) / 1e6 * 0.5  # batch rate
        return store.spend_to_date("grade") + projected > args.max_cost

    total = {"input": 0, "cached": 0, "output": 0}
    chunk, count, cbytes = [], 0, 0
    try:
        for g in groups:
            m, gb = len(g[2]), gbytes(g)
            if chunk and (count + m > CHUNK_SPECS or cbytes + gb > MAX_BATCH_BYTES):
                if would_exceed(chunk):
                    print(f"[{judge}] STOP: grade spend ${store.spend_to_date('grade'):.2f} + projected "
                          f"chunk would exceed cap ${args.max_cost:.0f}; remaining NOT submitted "
                          f"(raise --max-cost or re-run to resume)")
                    return
                u = flush(chunk, judge, backend, args.poll, print)
                for k in total:
                    total[k] += u.get(k, 0)
                chunk, count, cbytes = [], 0, 0
            chunk.append(g); count += m; cbytes += gb
        if chunk:
            if would_exceed(chunk):
                print(f"[{judge}] STOP: cap ${args.max_cost:.0f} would be exceeded; remaining NOT submitted")
                return
            u = flush(chunk, judge, backend, args.poll, print)
            for k in total:
                total[k] += u.get(k, 0)
    except RuntimeError as e:
        if S.is_quota_error(str(e)) or "quota/balance" in str(e):
            print(f"[{judge}] STOP: account balance/quota exhausted mid-run; partial grades saved, "
                  f"re-run after recharge to resume (no work lost). detail: {str(e)[:120]}")
            return
        raise
    print(f"[{judge}] done. TOTAL tokens  in={total['input']}  cached={total['cached']}  "
          f"out={total['output']}  | global grade spend to date ${store.spend_to_date('grade'):.2f}")


if __name__ == "__main__":
    main()
