"""Model samplers: candidates and judges, one per provider. Raw HTTP (stdlib),
prompt caching where supported, cumulative usage tracking.

Candidate call: __call__(messages: list[{"role","content"}]) -> response text.
Judge call:     __call__(grader_prompt: str) -> raw model text.
The same instance serves both roles; run_eval picks by argument type.

Reasoning policy: candidates run in their DEFAULT API config (reasoning models
reason, non-reasoning don't) — no forced parity; reasoning affects generation
only, not grading. Judges (gpt-4.1, claude-haiku, gemini-2.5-flash) run
non-reasoning + temperature=0 for deterministic HealthBench-faithful grading.

Per-model quirks handled below (verified live 2026-07-29 where noted):
- kimi-k2.6: temperature forced to 1 by the provider.
- claude-fable-5: thinking always on -> temperature must be 1.
- gpt-5.x (reasoning): omit temperature (only default allowed) + max_completion_tokens.
- qwen3-8b: Qwen3 open models need enable_thinking=false on non-streaming calls.
- gpt-3.5-turbo: 4096 output cap.

API keys come from the environment (source .env before running).
"""
import json
import os
import time
import urllib.error
import urllib.request

RUBRIC_MARKER = "\n# Rubric item\n"  # cache everything up to & including this
GEN_MAX_TOKENS = 8192   # candidate generation cap (headroom for reasoning models)
JUDGE_MAX_TOKENS = 2048  # HealthBench grader uses max_tokens=2048
GRADER_SYSTEM_MESSAGE = "You are a helpful assistant."  # OPENAI_SYSTEM_MESSAGE_API
_RETRY_CODES = {429, 500, 502, 503, 529}
# Balance/quota errors are PERMANENT (often masquerade as 429) — never retry them:
# hammering a suspended account is rude and risks getting the key blocked.
_QUOTA_MARKERS = ("insufficient balance", "insufficient_quota", "exceeded_current_quota",
                  "exceeded your current quota", "credit balance", "suspended",
                  "recharge", "billing_hard_limit", "out of credit", "quota_exceeded",
                  "depleted", "prepayment credit", "billing")


def is_quota_error(body):
    b = (body or "").lower()
    return any(m in b for m in _QUOTA_MARKERS)


# Empties with these stop/finish reasons are NOT retried: genuine declines
# (refusal/content_filter) or truncation (length/max_tokens) — retrying just
# pesters the API. Any other empty (stop/end_turn/unknown) is a likely fluke.
_NO_RETRY_EMPTY = ("refusal", "content_filter", "length", "max_tokens")


def should_retry_empty(text, stop_reason):
    return not (text and text.strip()) and (stop_reason or "") not in _NO_RETRY_EMPTY


# provider (base_url, key_env-or-list) — key_env list tries each name in order
OPENAI = ("https://api.openai.com/v1", "OPENAI_API_KEY")
DEEPSEEK = ("https://api.deepseek.com", "DEEPSEEK_API_KEY")
GOOGLE = ("https://generativelanguage.googleapis.com/v1beta/openai", "GOOGLE_API_KEY")
MOONSHOT = ("https://api.moonshot.ai/v1", ["MOONSHOT_API_KEY", "KIMI_API_KEY"])
XAI = ("https://api.x.ai/v1", "XAI_API_KEY")
MISTRAL = ("https://api.mistral.ai/v1", "MISTRAL_API_KEY")
DASHSCOPE = ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             ["DASHSCOPE_API_KEY", "QWEN_API_KEY"])


def _resolve_key(key_env):
    names = [key_env] if isinstance(key_env, str) else list(key_env)
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    raise KeyError(f"none of {names} set in environment")


def _post(url, headers, payload, timeout=300, retries=6):
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read().decode()[:500]
            except Exception:
                pass
            if is_quota_error(body_txt):  # exhausted account -> fail fast, do NOT retry
                raise RuntimeError(f"quota/balance exhausted (HTTP {e.code}): {body_txt[:200]}") from None
            if e.code in _RETRY_CODES and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise RuntimeError(f"HTTP {e.code}: {body_txt[:200]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise


class _Usage:
    def __init__(self):
        self.input = 0
        self.cached = 0
        self.output = 0
        self.calls = 0

    def as_dict(self):
        return {"input": self.input, "cached": self.cached,
                "output": self.output, "calls": self.calls}




def _lazy_key(obj):
    """Resolve the API key at first use, not import — analysis-only users need no keys."""
    if getattr(obj, "_key_cached", None) is None:
        obj._key_cached = _resolve_key(obj._key_env)
    return obj._key_cached

class OpenAICompatSampler:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, DeepSeek, Google,
    Moonshot/Kimi, xAI, Mistral, Qwen/DashScope). Prefix caching is automatic."""
    def __init__(self, id, base_url, key_env, extra=None, temperature=0,
                 gen_max=GEN_MAX_TOKENS, token_param="max_tokens"):
        self.id = id
        self._base = base_url
        self._key_env = key_env  # resolved lazily at first call
        self._extra = extra or {}
        self._temp = temperature          # None -> omit (reasoning models w/ fixed temp)
        self._gen_max = gen_max
        self._token_param = token_param    # "max_tokens" | "max_completion_tokens"
        self.params = {"temperature": temperature, "gen_max_tokens": gen_max,
                       "judge_max_tokens": JUDGE_MAX_TOKENS, "token_param": token_param,
                       "caching": "auto-prefix",
                       **({"extra": self._extra} if self._extra else {})}
        self.usage = _Usage()

    def _raw(self, x):
        if isinstance(x, list):
            messages, mt = x, self._gen_max
        else:  # judge call: HealthBench prepends the system message
            messages = [{"role": "system", "content": GRADER_SYSTEM_MESSAGE},
                        {"role": "user", "content": x}]
            mt = JUDGE_MAX_TOKENS
        payload = {"model": self.id, "messages": messages, self._token_param: mt, **self._extra}
        if self._temp is not None:
            payload["temperature"] = self._temp
        r = _post(self._base + "/chat/completions",
                  {"Authorization": f"Bearer {_lazy_key(self)}", "Content-Type": "application/json"},
                  payload)
        u = r.get("usage", {})
        cached = (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0) \
            or u.get("prompt_cache_hit_tokens", 0)
        self.usage.input += u.get("prompt_tokens", 0) - cached
        self.usage.cached += cached
        self.usage.output += u.get("completion_tokens", 0)
        self.usage.calls += 1
        return r

    def __call__(self, x):  # judge/text path
        return self._raw(x)["choices"][0]["message"].get("content") or ""

    def generate(self, messages):  # candidate path -> (text, finish_reason)
        ch = self._raw(messages)["choices"][0]
        return (ch["message"].get("content") or "", ch.get("finish_reason"))


class AnthropicSampler:
    """Anthropic /v1/messages. Ephemeral cache_control on the grader prefix so it
    is reused across a response's rubric-item calls (identical text either way)."""
    def __init__(self, id, temperature=0, gen_max=GEN_MAX_TOKENS):
        self.id = id
        self._key_env = "ANTHROPIC_API_KEY"  # resolved lazily at first call
        self._temp = temperature
        self._gen_max = gen_max
        self.params = {"temperature": temperature, "gen_max_tokens": gen_max,
                       "judge_max_tokens": JUDGE_MAX_TOKENS, "caching": "ephemeral-prefix"}
        self.usage = _Usage()

    def _raw(self, x):
        system = None
        if isinstance(x, list):
            messages = [{"role": m["role"], "content": m["content"]} for m in x]
            mt = self._gen_max
        else:  # judge call: HealthBench prepends the system message
            mt = JUDGE_MAX_TOKENS
            system = GRADER_SYSTEM_MESSAGE
            if RUBRIC_MARKER in x:
                i = x.index(RUBRIC_MARKER) + len(RUBRIC_MARKER)
                content = [
                    {"type": "text", "text": x[:i], "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": x[i:]},
                ]
            else:
                content = [{"type": "text", "text": x}]
            messages = [{"role": "user", "content": content}]
        payload = {"model": self.id, "max_tokens": mt, "messages": messages}
        if self._temp is not None:  # newest Claudes (Sonnet 5/Opus 5) reject temperature
            payload["temperature"] = self._temp
        if system:
            payload["system"] = system
        r = _post("https://api.anthropic.com/v1/messages",
                  {"x-api-key": _lazy_key(self), "anthropic-version": "2023-06-01",
                   "content-type": "application/json"},
                  payload)
        u = r.get("usage", {})
        self.usage.input += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        self.usage.cached += u.get("cache_read_input_tokens", 0)
        self.usage.output += u.get("output_tokens", 0)
        self.usage.calls += 1
        return r

    @staticmethod
    def _text(r):
        return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")

    def __call__(self, x):  # judge/text path
        return self._text(self._raw(x))

    def generate(self, messages):  # candidate path -> (text, stop_reason)
        r = self._raw(messages)
        return (self._text(r), r.get("stop_reason"))


# ============================ PANEL ============================
# 3 judges (gpt-4.1, claude-haiku, gemini-2.5-flash) are also candidates
# (self-preference). "r" in comments = reasoning under default config.
REGISTRY = {
    # ---- OpenAI ----
    "gpt-3.5-turbo": OpenAICompatSampler("gpt-3.5-turbo", *OPENAI, gen_max=4096),  # 4096 cap
    "gpt-4.1-2025-04-14": OpenAICompatSampler("gpt-4.1-2025-04-14", *OPENAI),      # JUDGE + candidate
    "gpt-5.5": OpenAICompatSampler("gpt-5.5", *OPENAI, temperature=None,           # r: fixed temp
                                   token_param="max_completion_tokens"),
    "gpt-5.6-sol": OpenAICompatSampler("gpt-5.6-sol", *OPENAI, temperature=None,   # r
                                       token_param="max_completion_tokens"),
    # ---- Anthropic (non-Fable run plain/non-thinking by default) ----
    "claude-haiku-4-5-20251001": AnthropicSampler("claude-haiku-4-5-20251001"),    # JUDGE + candidate
    "claude-sonnet-5": AnthropicSampler("claude-sonnet-5", temperature=None),   # temp deprecated
    "claude-opus-5": AnthropicSampler("claude-opus-5", temperature=None),       # temp deprecated
    "claude-fable-5": AnthropicSampler("claude-fable-5", temperature=1),           # thinking always on
    # ---- Google ----
    "gemini-2.5-flash": OpenAICompatSampler("gemini-2.5-flash", *GOOGLE,           # JUDGE + candidate
                                            extra={"reasoning_effort": "none"}),   # thinking off
    "gemini-2.5-pro": OpenAICompatSampler("gemini-2.5-pro", *GOOGLE),              # r (default)
    "gemini-3.6-flash": OpenAICompatSampler("gemini-3.6-flash", *GOOGLE),          # r (default)
    # ---- Mistral ----
    "mistral-large-latest": OpenAICompatSampler("mistral-large-latest", *MISTRAL),
    "mistral-small-latest": OpenAICompatSampler("mistral-small-latest", *MISTRAL),
    # ---- DeepSeek (reasoning; temp=0 verified) ----
    "deepseek-v4-flash": OpenAICompatSampler("deepseek-v4-flash", *DEEPSEEK),
    "deepseek-v4-pro": OpenAICompatSampler("deepseek-v4-pro", *DEEPSEEK),
    # ---- Kimi / Moonshot (reasoning) ----
    "kimi-k3": OpenAICompatSampler("kimi-k3", *MOONSHOT, temperature=1),           # temp forced to 1
    "kimi-k2.6": OpenAICompatSampler("kimi-k2.6", *MOONSHOT, temperature=1),       # temp forced to 1
    # ---- xAI ----
    "grok-4.5": OpenAICompatSampler("grok-4.5", *XAI),
    # ---- Qwen / DashScope ----
    "qwen3.7-plus": OpenAICompatSampler("qwen3.7-plus", *DASHSCOPE),               # r (thinking on)
    "qwen3-8b": OpenAICompatSampler("qwen3-8b", *DASHSCOPE,                        # non-streaming -> no thinking
                                    extra={"enable_thinking": False}),
}

# Judge subset (must be non-reasoning + temperature=0).
JUDGES = ["gpt-4.1-2025-04-14", "claude-haiku-4-5-20251001", "gemini-2.5-flash"]
CANDIDATES = list(REGISTRY)  # all 20 are candidates (judges included, for self-preference)

_BASES = {"openai": OPENAI[0], "deepseek": DEEPSEEK[0], "google": GOOGLE[0],
          "moonshot": MOONSHOT[0], "xai": XAI[0], "mistral": MISTRAL[0],
          "dashscope": DASHSCOPE[0]}
BATCHABLE = {"openai", "anthropic", "google"}  # providers with a batch backend


def provider_of(model_id):
    smp = REGISTRY[model_id]
    if isinstance(smp, AnthropicSampler):
        return "anthropic"
    for name, base in _BASES.items():
        if smp._base == base:
            return name
    return "unknown"


def candidates_by_provider():
    out = {}
    for mid in CANDIDATES:
        out.setdefault(provider_of(mid), []).append(mid)
    return out


def spec_for(model_id, custom_id, messages, system=None, judge=False):
    """Neutral batch/HTTP request spec mirroring a sampler's config (temperature,
    token param, extra, max_tokens) so batched calls match sync calls."""
    smp = REGISTRY[model_id]
    return {"custom_id": custom_id, "model": model_id, "messages": messages,
            "system": system,
            "temperature": smp._temp if not isinstance(smp, AnthropicSampler) else getattr(smp, "_temp", 0),
            "max_tokens": JUDGE_MAX_TOKENS if judge else getattr(smp, "_gen_max", GEN_MAX_TOKENS),
            "extra": getattr(smp, "_extra", {}),
            "token_param": getattr(smp, "_token_param", "max_tokens")}
