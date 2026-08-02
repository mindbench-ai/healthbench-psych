"""Generate candidate responses for ONE provider's candidates over a subset.

One process per provider (kill-safe: if a provider runs out of credits, kill just
this process; others are untouched). Idempotent + prompt-keyed via store.py, so a
re-run resumes and a larger round-2 subset only does the new prompts.

Batchable providers (openai/anthropic/google) use the Batch API; sync providers
(deepseek/kimi/mistral/xai/dashscope) use a bounded thread pool over independent
calls. Grading is a separate phase (grade.py) that reads these responses.

CLI: python eval/generate.py --provider deepseek --subset includes_majority [--workers 8]
"""
import argparse
import concurrent.futures as cf
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backends import openai as batch_openai  # noqa: E402
from backends import anthropic as batch_anthropic  # noqa: E402
from backends import google as batch_google  # noqa: E402
from lib import prices  # noqa: E402
import run_eval as R  # noqa: E402  (load_subset / SOURCE helpers)
from lib import samplers as S  # noqa: E402
from lib import store  # noqa: E402

BACKENDS = {"openai": batch_openai, "anthropic": batch_anthropic, "google": batch_google}
PROVIDER_WORKERS = {"mistral": 1, "moonshot": 4}  # mistral rate-limits even at 2 -> serial is faster
FORCE_SYNC = {"gpt-5.6-sol"}  # batchable provider, but THIS model's batch queue hangs -> gen sync


def load_examples(prompt_ids, source):
    ex = {}
    for line in open(source):
        import json
        d = json.loads(line)
        if d["prompt_id"] in prompt_ids:
            ex[d["prompt_id"]] = d
    missing = prompt_ids - set(ex)
    if missing:
        raise SystemExit(f"{len(missing)} subset prompt_ids not in {source}")
    return ex


def _gen_one(smp, messages, retries=2):
    """One candidate generation, returning (text, stop_reason), with BOUNDED retry
    on non-refusal empties (transient flukes self-heal; refusals/truncation kept)."""
    txt, sr = smp.generate(messages)
    tries = 0
    while S.should_retry_empty(txt, sr) and tries < retries:
        txt, sr = smp.generate(messages)
        tries += 1
    return txt or "", sr


def gen_batch(provider, cand, todo, examples, poll):
    backend = BACKENDS[provider]
    smp = S.REGISTRY[cand]
    specs = [S.spec_for(cand, f"r{i}", examples[pid]["prompt"]) for i, pid in enumerate(todo)]
    results, meta = backend.run_requests(specs, poll=poll)
    stops = meta.get("stop_reasons", {})
    recs, failed = [], []
    for i, pid in enumerate(todo):
        cid = f"r{i}"
        txt, sr = results.get(cid), stops.get(cid)
        if cid not in results or S.should_retry_empty(txt, sr):  # dropped or fluke-empty -> sync retry
            try:
                txt, sr = _gen_one(smp, examples[pid]["prompt"])
            except Exception as e:
                detail = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"    {pid[:8]} fallback ERROR {detail[:90]}")
                failed.append((pid, detail))
                continue
        recs.append({"prompt_id": pid, "response_text": txt or "", "stop_reason": sr})
    empty = sum(1 for r in recs if not (r["response_text"] or "").strip())
    return recs, empty, meta.get("usage", {"input": 0, "cached": 0, "output": 0}), failed


def gen_sync(cand, todo, examples, workers, flush_every=40):
    smp = S.REGISTRY[cand]
    path = store.resp_path(cand)
    u0 = (smp.usage.input, smp.usage.cached, smp.usage.output)
    recs, failed, buf = [], [], []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_gen_one, smp, examples[pid]["prompt"]): pid for pid in todo}
        for fut in cf.as_completed(futs):  # runs in main thread -> store.append is safe
            pid = futs[fut]
            try:
                txt, sr = fut.result()
            except Exception as e:  # failure -> don't persist, retried on re-run
                detail = f"{type(e).__name__}: {str(e)[:200]}"
                print(f"    {pid[:8]} ERROR {detail[:90]}")
                failed.append((pid, detail))
                continue
            r = {"prompt_id": pid, "response_text": txt, "stop_reason": sr}
            recs.append(r); buf.append(r)
            if len(buf) >= flush_every:  # incremental save -> a kill keeps completed work
                store.append(path, buf); buf = []
    if buf:
        store.append(path, buf)
    usage = {"input": smp.usage.input - u0[0], "cached": smp.usage.cached - u0[1],
             "output": smp.usage.output - u0[2]}
    empty = sum(1 for r in recs if not (r["response_text"] or "").strip())
    return recs, empty, usage, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--source", default=R.SOURCE)
    ap.add_argument("--workers", type=int, default=8, help="thread pool size for sync providers")
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--max-cost", type=float, default=0.0,
                    help="halt the generation arm once GLOBAL generation spend >= this ($); 0 = off")
    ap.add_argument("--flush-every", type=int, default=40,
                    help="sync providers: flush responses to the store every N completions")
    args = ap.parse_args()

    by_prov = S.candidates_by_provider()
    if args.provider not in by_prov:
        raise SystemExit(f"no candidates for provider '{args.provider}'. "
                         f"providers: {sorted(by_prov)}")
    cands = by_prov[args.provider]
    _, prompt_ids = R.load_subset(args.subset)
    examples = load_examples(prompt_ids, args.source)
    prov_batchable = args.provider in S.BATCHABLE
    workers = PROVIDER_WORKERS.get(args.provider, args.workers)
    print(f"[{args.provider}] {len(cands)} candidates, {len(prompt_ids)} prompts")

    total = {"input": 0, "cached": 0, "output": 0}
    all_failed = {}
    for cand in cands:
        path = store.resp_path(cand)
        todo = [pid for pid in sorted(prompt_ids) if pid not in store.load_done(path)]
        if not todo:
            print(f"  {cand}: all {len(prompt_ids)} done — skip")
            continue
        if args.max_cost and store.spend_to_date("generate") >= args.max_cost:
            print(f"[{args.provider}] STOP: generation spend "
                  f"${store.spend_to_date('generate'):.2f} >= cap ${args.max_cost:.0f} — "
                  f"{cand} and later NOT started (raise --max-cost or re-run to resume)")
            break
        use_batch = prov_batchable and cand not in FORCE_SYNC
        print(f"  {cand}: generating {len(todo)} (of {len(prompt_ids)}) via "
              f"{'batch' if use_batch else f'sync x{workers}'} ...")
        if use_batch:
            recs, empty, usage, failed = gen_batch(args.provider, cand, todo, examples, args.poll)
        else:
            recs, empty, usage, failed = gen_sync(cand, todo, examples, workers, args.flush_every)
        wrote = store.append(path, recs)
        for k in total:
            total[k] += usage.get(k, 0)
        cost = prices.cost_of(cand, usage, batch=use_batch)
        store.record_spend("generate", cand, cost)
        for pid, detail in failed:  # durable error log
            store.log_error(phase="generate", provider=args.provider, candidate=cand,
                            prompt_id=pid, kind="call_failed", detail=detail)
        for r in recs:  # genuine empties are stored (parity) but flagged for the refusal audit
            if not (r["response_text"] or "").strip():
                store.log_error(phase="generate", provider=args.provider, candidate=cand,
                                prompt_id=r["prompt_id"], kind="empty_response",
                                detail=f"stop_reason={r.get('stop_reason')}")
        if failed:
            all_failed[cand] = failed
        flag = (f" [{empty} empty]" if empty else "") + (f" [{len(failed)} FAILED-not stored]" if failed else "")
        print(f"  {cand}: gen {len(recs)} (wrote {wrote}){flag} | ${cost:.2f} | tok in={usage.get('input',0)} "
              f"cached={usage.get('cached',0)} out={usage.get('output',0)}")
    print(f"[{args.provider}] TOTAL tokens  in={total['input']}  cached={total['cached']}  "
          f"out={total['output']}  | global gen spend to date ${store.spend_to_date('generate'):.2f}")
    if all_failed:
        nfail = sum(len(v) for v in all_failed.values())
        print(f"[{args.provider}] {nfail} FAILED calls NOT stored (retry by re-running): "
              + ", ".join(f"{c}:{len(v)}" for c, v in all_failed.items()))


if __name__ == "__main__":
    main()
