"""OpenAI Batch API helpers (stdlib only).

Upload a JSONL of chat-completion requests, create a batch, poll to completion,
and fetch results keyed by custom_id. The Batch API is ~50% cheaper than sync
and runs server-side (the machine need not stay awake past submission), at the
cost of a completion window (up to 24h; small jobs usually finish in minutes).

OpenAI-only for now: DeepSeek/Google OpenAI-compat and Anthropic expose separate
batch endpoints — add sibling modules when those judges/candidates are batched.

Reference: POST /v1/files (purpose=batch) -> POST /v1/batches -> GET /v1/batches/{id}
-> GET /v1/files/{output_file_id}/content.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

OPENAI_BASE = "https://api.openai.com/v1"
_TERMINAL = {"completed", "failed", "expired", "cancelled"}


def _key():
    return os.environ["OPENAI_API_KEY"]


_RETRY_CODES = {429, 500, 502, 503, 529}


_QUOTA = ("insufficient balance", "insufficient_quota", "exceeded_current_quota",
          "credit balance", "suspended", "recharge", "out of credit", "quota_exceeded",
          "depleted", "prepayment credit", "billing")


def _urlopen_retry(req, timeout, retries=6):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:500]
            except Exception:
                pass
            if any(m in body.lower() for m in _QUOTA):  # exhausted account -> fail fast
                raise RuntimeError(f"quota/balance exhausted (HTTP {e.code}): {body[:200]}") from None
            if e.code in _RETRY_CODES and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30)); continue
            raise RuntimeError(f"batch HTTP {e.code}: {body[:200]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30)); continue
            raise


def _request(url, data=None, headers=None, method="GET", timeout=300):
    h = {"Authorization": f"Bearer {_key()}"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    return json.loads(_urlopen_retry(req, timeout).decode())


def upload_jsonl(lines, purpose="batch"):
    """Upload a list of request dicts as one JSONL file. Returns the file id.
    Multipart/form-data is hand-built (stdlib has no multipart encoder)."""
    payload = ("\n".join(json.dumps(x) for x in lines) + "\n").encode()
    boundary = "----hbbatch" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="purpose"\r\n\r\n{purpose}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="batch.jsonl"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + payload + tail
    return _request(
        OPENAI_BASE + "/files", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )["id"]


def create_batch(input_file_id, endpoint="/v1/chat/completions", window="24h"):
    body = json.dumps({
        "input_file_id": input_file_id, "endpoint": endpoint,
        "completion_window": window,
    }).encode()
    return _request(
        OPENAI_BASE + "/batches", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )["id"]


def get_batch(batch_id):
    return _request(OPENAI_BASE + f"/batches/{batch_id}")


def download_file(file_id):
    req = urllib.request.Request(
        OPENAI_BASE + f"/files/{file_id}/content",
        headers={"Authorization": f"Bearer {_key()}"},
    )
    return _urlopen_retry(req, timeout=600).decode()


def wait_batch(batch_id, poll=30, log=print):
    while True:
        b = get_batch(batch_id)
        log(f"  batch {batch_id}: {b['status']} {b.get('request_counts', {})}")
        if b["status"] in _TERMINAL:
            return b
        time.sleep(poll)


def _parse_output(text, log=print):
    """Map custom_id -> assistant text for successful lines; log failures. Also
    returns summed token usage {input, cached, output}."""
    out, usage, stop = {}, {"input": 0, "cached": 0, "output": 0}, {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid = rec["custom_id"]
        resp = rec.get("response") or {}
        if resp.get("status_code") == 200:
            body = resp["body"]
            ch = body["choices"][0]
            out[cid] = ch["message"].get("content") or ""
            stop[cid] = ch.get("finish_reason")
            u = body.get("usage", {}) or {}
            cached = (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
            usage["input"] += u.get("prompt_tokens", 0) - cached
            usage["cached"] += cached
            usage["output"] += u.get("completion_tokens", 0)
        else:
            log(f"  request {cid} failed: code={resp.get('status_code')} "
                f"err={str(rec.get('error'))[:140]}")
    return out, usage, stop


def _to_line(s):
    """Neutral request spec -> OpenAI batch input line. A `system` string becomes
    the first message; `extra` merges provider-specific fields; temperature is
    omitted when None (reasoning models that reject it); token_param lets reasoning
    models use max_completion_tokens."""
    tp = s.get("token_param") or "max_tokens"
    body = {"model": s["model"], tp: s["max_tokens"],
            "messages": ([{"role": "system", "content": s["system"]}] if s.get("system") else [])
            + [{"role": m["role"], "content": m["content"]} for m in s["messages"]]}
    if s.get("temperature") is not None:
        body["temperature"] = s["temperature"]
    body.update(s.get("extra", {}))
    return {"custom_id": s["custom_id"], "method": "POST",
            "url": "/v1/chat/completions", "body": body}


def run_requests(specs, endpoint="/v1/chat/completions", poll=30, log=print):
    """Full round-trip. Returns (results: {custom_id: text}, meta: dict).

    `specs` is a list of neutral request dicts (see module docstring). Blocks
    until the batch reaches a terminal state; run in the background for large
    jobs. Raises if the batch does not complete."""
    lines = [_to_line(s) for s in specs]
    fid = upload_jsonl(lines)
    bid = create_batch(fid, endpoint=endpoint)
    log(f"submitted batch {bid}: {len(lines)} requests (input file {fid})")
    b = wait_batch(bid, poll=poll, log=log)
    if b["status"] != "completed":
        raise RuntimeError(f"batch {bid} ended '{b['status']}': {b.get('errors')}")
    results, usage, stop = _parse_output(download_file(b["output_file_id"]), log=log)
    meta = {
        "batch_id": bid, "input_file_id": fid,
        "output_file_id": b.get("output_file_id"),
        "error_file_id": b.get("error_file_id"),
        "request_counts": b.get("request_counts"),
        "usage": usage, "stop_reasons": stop,
    }
    log(f"batch {bid} completed: {len(results)}/{len(lines)} results parsed")
    return results, meta
