"""Google Gemini native Batch API (stdlib only).

Not OpenAI-compatible: requests use the GenerateContent shape (contents/parts,
systemInstruction, generationConfig), thinking is disabled via
generationConfig.thinkingConfig.thinkingBudget=0, and auth is the x-goog-api-key
header. File-based submission (JSONL keyed by "key") + keyed results, so it scales
to the full grading sweep and maps results back by custom_id.

Uniform interface with the other backends:
    run_requests(specs, poll, log) -> ({custom_id: text}, meta)
Neutral spec: {custom_id, model, system?, messages:[{role,content}], temperature,
max_tokens, extra?}. `extra` may carry {"reasoning_effort":"none"} (from the
OpenAI-compat sync sampler) which is mapped to thinkingBudget=0.

Refs: ai.google.dev/gemini-api/docs/batch-api ; /docs/thinking ; /api/generate-content
"""
import json
import os
import time
import urllib.error
import urllib.request

HOST = "https://generativelanguage.googleapis.com"
# Live API returns BATCH_STATE_* (docs say JOB_STATE_*); accept both.
_SUCCESS = {"BATCH_STATE_SUCCEEDED", "JOB_STATE_SUCCEEDED"}
_TERMINAL = _SUCCESS | {"BATCH_STATE_FAILED", "BATCH_STATE_CANCELLED", "BATCH_STATE_EXPIRED",
                        "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
_ROLE = {"user": "user", "assistant": "model", "model": "model", "system": "user"}


def _key():
    return os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]


def _headers(extra=None):
    h = {"x-goog-api-key": _key()}
    if extra:
        h.update(extra)
    return h


_RETRY_CODES = {429, 500, 502, 503, 529}


def _req(url, data=None, method="GET", headers=None, timeout=300, raw=False, retries=6):
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers or _headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return b if raw else json.loads(b.decode())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:500]
            except Exception:
                pass
            if any(m in body.lower() for m in ("insufficient balance", "insufficient_quota",
                    "exceeded_current_quota", "credit balance", "suspended", "recharge",
                    "out of credit", "quota_exceeded", "depleted", "prepayment credit",
                    "billing")):  # exhausted -> fail fast
                raise RuntimeError(f"google quota/balance exhausted (HTTP {e.code}): {body[:200]}") from None
            if e.code in _RETRY_CODES and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30)); continue
            raise RuntimeError(f"google {method} {url} -> {e.code}: {body[:200]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30)); continue
            raise


def _to_request(s):
    """Neutral spec -> a Gemini GenerateContentRequest."""
    gen = {"maxOutputTokens": s["max_tokens"]}
    if s.get("temperature") is not None:
        gen["temperature"] = s["temperature"]
    if (s.get("extra") or {}).get("reasoning_effort") == "none":
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    req = {"contents": [{"role": _ROLE.get(m["role"], "user"),
                         "parts": [{"text": m["content"]}]} for m in s["messages"]],
           "generationConfig": gen}
    if s.get("system"):
        req["systemInstruction"] = {"parts": [{"text": s["system"]}]}
    return req


def _upload_jsonl(lines):
    """Resumable upload of a JSONL file; returns the file resource name (files/xxx)."""
    payload = ("\n".join(json.dumps(l) for l in lines) + "\n").encode()
    start = urllib.request.Request(
        HOST + "/upload/v1beta/files",
        data=json.dumps({"file": {"display_name": "hb_batch_input"}}).encode(),
        headers={**_headers(), "X-Goog-Upload-Protocol": "resumable",
                 "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(len(payload)),
                 "X-Goog-Upload-Header-Content-Type": "application/jsonl",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(start, timeout=120) as r:
        upload_url = r.headers.get("X-Goog-Upload-URL") or r.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("google upload: no resumable X-Goog-Upload-URL header returned")
    finalize = urllib.request.Request(
        upload_url, data=payload,
        headers={**_headers(), "Content-Length": str(len(payload)),
                 "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
        method="POST")
    with urllib.request.urlopen(finalize, timeout=300) as r:
        info = json.loads(r.read().decode())
    return info["file"]["name"]


def _state(b):
    return (b.get("state") or (b.get("metadata") or {}).get("state")
            or (b.get("response") or {}).get("state"))


def _dest(b):
    for loc in (b.get("dest"), (b.get("response") or {}).get("dest"),
                (b.get("metadata") or {}).get("dest")):
        if loc:
            return loc
    return None


def _text(resp):
    try:
        parts = resp["candidates"][0].get("content", {}).get("parts", [])
        t = "".join(p.get("text", "") for p in parts)
        return t or None
    except (KeyError, IndexError, TypeError):
        return None


def run_requests(specs, poll=30, log=print):
    """Full round-trip. Returns ({custom_id: text}, meta). Blocks until the job
    reaches a terminal state; run in the background for large jobs."""
    model = specs[0]["model"]
    lines = [{"key": s["custom_id"], "request": _to_request(s)} for s in specs]
    file_name = _upload_jsonl(lines)
    log(f"google batch: uploaded {len(lines)} requests as {file_name}")
    create = _req(f"{HOST}/v1beta/models/{model}:batchGenerateContent",
                  data=json.dumps({"batch": {"display_name": "hb_batch",
                                             "input_config": {"file_name": file_name}}}).encode(),
                  method="POST", headers={**_headers(), "Content-Type": "application/json"})
    name = create.get("name")
    log(f"google batch {name}: submitted")
    b = create
    while True:
        b = _req(f"{HOST}/v1beta/{name}")
        st = _state(b)
        log(f"  batch {name}: state={st}")
        if b.get("done") or st in _TERMINAL:
            break
        time.sleep(poll)
    st = _state(b)
    if st and st not in _SUCCESS:
        raise RuntimeError(f"google batch {name} ended {st}: {str(b)[:300]}")

    out, usage, stop = {}, {"input": 0, "cached": 0, "output": 0}, {}
    # File-based output: results JSONL at response.responsesFile (keyed by "key").
    resp_file = ((b.get("response") or {}).get("responsesFile")
                 or ((b.get("metadata") or {}).get("output") or {}).get("responsesFile"))
    if resp_file:
        text = _req(f"{HOST}/download/v1beta/{resp_file}:download?alt=media", raw=True).decode()
        for line in text.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            resp = rec.get("response") or {}
            t = _text(resp)
            if t is not None:
                out[rec.get("key")] = t
                stop[rec.get("key")] = (resp.get("candidates") or [{}])[0].get("finishReason")
                um = resp.get("usageMetadata", {}) or {}
                cc = um.get("cachedContentTokenCount", 0)
                usage["input"] += um.get("promptTokenCount", 0) - cc
                usage["cached"] += cc
                usage["output"] += um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0)
            else:
                log(f"  request {rec.get('key')} error: {str(rec.get('error') or rec)[:140]}")
    else:
        # Inline output (only for inline-submitted batches): positional order.
        dest = _dest(b)
        if dest and dest.get("inlinedResponses"):
            for s, item in zip(specs, dest["inlinedResponses"]):
                t = _text(item.get("response") or {})
                if t is not None:
                    out[s["custom_id"]] = t
        else:
            raise RuntimeError(f"google batch {name}: no responsesFile/inlined output: {str(b)[:300]}")
    meta = {"batch_name": name, "input_file": file_name, "usage": usage, "stop_reasons": stop}
    log(f"google batch {name} done: {len(out)}/{len(specs)} results parsed")
    return out, meta
