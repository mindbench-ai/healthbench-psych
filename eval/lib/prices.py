"""Per-model API prices ($/1M tokens) and a cost helper; the basis for the
spend guard and cost reporting. Batch APIs bill at 50% of these rates.

Prices as researched 2026-07-29 (input, output, cached_input). Cached-input is
the discounted rate for prompt-cache hits; where a provider lists none we fall
back to the input price. Update alongside the panel in samplers.py / NOTES.md.
"""
PRICES = {  # model: (input, output, cached_input) $/1M
    "gpt-3.5-turbo": (0.50, 1.50, 0.50),
    "gpt-4.1-2025-04-14": (2.0, 8.0, 0.50),
    "gpt-5.5": (5.0, 30.0, 0.50),
    "gpt-5.6-sol": (5.0, 30.0, 0.50),
    "claude-haiku-4-5-20251001": (1.0, 5.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "gemini-2.5-flash": (0.30, 2.50, 0.03),
    "gemini-2.5-pro": (1.25, 10.0, 0.125),
    "gemini-3.6-flash": (1.50, 7.50, 0.15),
    "mistral-large-latest": (2.0, 6.0, 2.0),
    "mistral-small-latest": (0.20, 0.60, 0.20),   # behind auth; estimate
    "deepseek-v4-flash": (0.14, 0.28, 0.014),
    "deepseek-v4-pro": (0.44, 0.87, 0.044),
    "kimi-k3": (3.0, 15.0, 0.30),
    "kimi-k2.6": (0.95, 4.0, 0.16),
    "grok-4.5": (2.0, 6.0, 0.50),
    "qwen3.7-plus": (0.32, 1.28, 0.032),
    "qwen3-8b": (0.05, 0.20, 0.05),               # estimate
}
_FALLBACK = (5.0, 30.0, 5.0)  # conservative if a model is unlisted (over-estimates)


def cost_of(model, usage, batch=False):
    """Dollar cost of a usage dict {input, cached, output} for `model`. Batch APIs
    bill at half rate. Unknown models use a high fallback rate."""
    pin, pout, pcache = PRICES.get(model, _FALLBACK)
    mult = 0.5 if batch else 1.0
    return (usage.get("input", 0) * pin + usage.get("cached", 0) * pcache
            + usage.get("output", 0) * pout) / 1e6 * mult
