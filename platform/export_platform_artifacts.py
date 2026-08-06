"""Export the released run data as MindBench platform artifacts.

Reconstruction (2026-08-04) of the exporter that produced the 20 promoted
mindbench-results.v1 artifacts (run.harness "healthbench-psych-eval"),
verified metric-for-metric, bit-for-bit against those payloads. One
artifact per candidate model — the natural key is benchmark x model x run
(R2.4) — each carrying:

  - healthbench_score        panel mean (3 judges) of the per-judge
                             HealthBench clipped-mean scores on
                             healthbench-psych-v1 (n=610)
  - healthbench_hard_score   the same on healthbench-psych-hard-v1 (n=119)
  - per_judge_scores         the per-judge clipped means behind both

All numbers are recomputed from the committed grades store
(eval/runs/grades/*.jsonl) exactly as eval/aggregate.py does: per-prompt
scores filtered to the subset, mean clipped to [0,1].

Schema (R2.2 / L25): platform/schemas/mindbench-results.v1.schema.json is a
VENDORED, byte-identical copy of the authoritative platform schema at
mindbench-platform/packages/artifact-schemas/schemas/ — the platform's copy
wins and syncs are deliberate; re-copy the file verbatim to sync. Every
payload is validated against it before anything is written.

Self-description (R2.3): mindbench-results.v1 is additionalProperties:false,
so the payload's producer identity rides in run.harness / run.harness_commit
and its generation time in run.started_at / run.finished_at (this exporter,
like the original, stamps export wall-clock time — the store keeps no
per-call timestamps). The batch-level generated_at and producer {repo,
commit} live in <out>/export-manifest.json alongside the payload sha256s.

Usage (no API keys needed):
    python3 platform/export_platform_artifacts.py              # -> platform/out/
    python3 platform/export_platform_artifacts.py --out DIR

Writes one <out>/healthbench-psych--<model>.json per model (gitignored) plus
<out>/export-manifest.json. The platform ingests these through its generic
mindbench-results.v1 importer; no platform code is specific to this spoke.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "eval"))
from lib import samplers, store  # noqa: E402

SCHEMA_PATH = os.path.join(ROOT, "platform", "schemas",
                           "mindbench-results.v1.schema.json")
SUBSETS_DIR = os.path.join(ROOT, "eval", "subsets")
V1_SUBSET = "healthbench-psych-v1"
HARD_SUBSET = "healthbench-psych-hard-v1"
BENCHMARK_SLUG = "healthbench-psych"
HARNESS = "healthbench-psych-eval"
ADAPTER_VERSION = "1.0"
# The HealthBench OSS corpus release the subsets index into (README: Reproducing).
HB_SOURCE = ("https://openaipublic.blob.core.windows.net/simple-evals/"
             "healthbench/2025-05-07-06-14-12_oss_eval.jsonl")
# Platform provider slugs where they differ from the harness's endpoint names.
PROVIDER_SLUGS = {"dashscope": "alibaba"}


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_subset(name):
    return json.load(open(os.path.join(SUBSETS_DIR, f"{name}.json")))


def clipped_mean(scores):
    """HealthBench's reported statistic: mean clipped to [0,1] (aggregate.py).

    Integer bounds on purpose: a clipped cell serializes as JSON 0/1, exactly
    as the promoted artifacts carry it (e.g. gpt-3.5-turbo's hard scores).
    """
    m = sum(scores) / len(scores)
    return max(0, min(1, m))


def judge_scores(candidate, judge, prompt_ids):
    """This candidate's per-prompt scores under one judge, subset-filtered,
    in grades-file line order (the store is append-only and committed)."""
    path = os.path.join(store.GRADE_DIR, f"{candidate}__{judge}.jsonl")
    if not os.path.exists(path):
        raise SystemExit(f"missing grades file: {path}")
    return [r["score"] for r in (json.loads(l) for l in open(path))
            if r["prompt_id"] in prompt_ids and r.get("score") is not None]


def quantize(obj):
    """Serialize floats at 16 significant digits, recursively.

    The promoted v1 artifacts carry floats at %.16g precision (verified
    bit-for-bit against the platform DB, 2026-08-04); full-precision means
    are computed first and quantized only here, at the serialization edge.
    """
    if isinstance(obj, float):
        return float(f"{obj:.16g}")
    if isinstance(obj, dict):
        return {k: quantize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [quantize(v) for v in obj]
    return obj


# --- schema validation (R2.2: validate before writing) -----------------------
# jsonschema is used when installed; otherwise a minimal built-in checker
# covering every construct mindbench-results.v1 uses keeps this repo's
# no-dependency property (the harness itself is stdlib-only).

def _check(schema, obj, path="$"):
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        pymap = {"object": dict, "array": list, "string": str, "integer": int,
                 "number": (int, float), "null": type(None), "boolean": bool}
        if not any(isinstance(obj, pymap[x]) and not (x == "integer" and isinstance(obj, bool))
                   for x in types):
            raise ValueError(f"{path}: expected {t}, got {type(obj).__name__}")
    if "const" in schema and obj != schema["const"]:
        raise ValueError(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and obj not in schema["enum"]:
        raise ValueError(f"{path}: {obj!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(obj, str) and not re.search(schema["pattern"], obj):
        raise ValueError(f"{path}: {obj!r} fails pattern {schema['pattern']}")
    if "minimum" in schema and isinstance(obj, (int, float)) and obj < schema["minimum"]:
        raise ValueError(f"{path}: {obj} < minimum {schema['minimum']}")
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                raise ValueError(f"{path}: missing required {k!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(obj) - set(props)
            if extra:
                raise ValueError(f"{path}: additional properties {sorted(extra)}")
        for k, v in obj.items():
            if k in props:
                _check(props[k], v, f"{path}.{k}")
    if isinstance(obj, list):
        if "minItems" in schema and len(obj) < schema["minItems"]:
            raise ValueError(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, v in enumerate(obj):
                _check(schema["items"], v, f"{path}[{i}]")
    if "anyOf" in schema:
        errs = []
        for sub in schema["anyOf"]:
            try:
                _check(sub, obj, path)
                break
            except ValueError as e:
                errs.append(str(e))
        else:
            raise ValueError(f"{path}: no anyOf branch matched ({'; '.join(errs)})")


def validate(payload, schema):
    try:
        import jsonschema
    except ImportError:
        _check(schema, payload)
    else:
        jsonschema.validate(payload, schema)


# --- payload construction -----------------------------------------------------

def build_payload(candidate, judges, subsets, commit, started_at):
    per_judge = {}   # subset key -> judge -> full-precision clipped mean
    counts = {}      # subset key -> n prompts scored (asserted judge-uniform)
    for key, meta in subsets.items():
        pids = set(meta["prompt_ids"])
        vals, ns = {}, set()
        for j in judges:
            scores = judge_scores(candidate, j, pids)
            vals[j] = clipped_mean(scores)
            ns.add(len(scores))
        if ns != {meta["n"]}:
            raise SystemExit(f"{candidate}/{key}: scored counts {sorted(ns)} != subset n={meta['n']}")
        per_judge[key], counts[key] = vals, meta["n"]

    v1 = subsets["v1"]
    panel = {k: sum(per_judge[k][j] for j in judges) / len(judges) for k in subsets}
    provider = samplers.provider_of(candidate)
    return {
        "schema_version": 1,
        "benchmark": {
            "slug": BENCHMARK_SLUG,
            "dataset_manifest": {
                "source": HB_SOURCE,
                "revision": f"{v1['name']} {v1['version']}",
                "split": v1["name"],
                "n_items": v1["n"],
                "subsample": None,
                "checksum": f"sha256:{v1['prompt_id_sha256']}",
            },
        },
        "model": {
            "label": candidate,
            "api_model_id": candidate,
            "provider": PROVIDER_SLUGS.get(provider, provider),
            # The sweep's default config, as the promoted artifacts record it.
            # Per-model deviations (provider-forced or fixed temperatures) are
            # documented in eval/lib/samplers.py.
            "sampling": {"temperature": 0},
        },
        "run": {
            "harness": HARNESS,
            "harness_commit": commit,
            "adapter_version": ADAPTER_VERSION,
            "started_at": started_at,
            "finished_at": utc_now(),
            "cost_usd": None,
            "n_completed": counts["v1"],
            "n_errors": 0,
        },
        "scoring": {
            "method": "llm_judge",
            "judge": {
                "model": " + ".join(sorted(judges)),
                "prompt_version": "healthbench grader (vendored), temperature 0",
            },
        },
        "metrics": [
            {"key": "healthbench_score", "value": panel["v1"],
             "n": counts["v1"], "ci_low": None, "ci_high": None},
            {"key": "healthbench_hard_score", "value": panel["hard"],
             "n": counts["hard"], "ci_low": None, "ci_high": None},
            {"key": "per_judge_scores",
             "value_json": {"v1": {j: per_judge["v1"][j] for j in sorted(judges)},
                            "hard": {j: per_judge["hard"][j] for j in sorted(judges)}}},
        ],
        "items_artifact": None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "platform", "out"),
                    help="output directory (gitignored; default platform/out/)")
    args = ap.parse_args()

    schema = json.load(open(SCHEMA_PATH))
    subsets = {"v1": load_subset(V1_SUBSET), "hard": load_subset(HARD_SUBSET)}
    judges = list(samplers.JUDGES)
    candidates = sorted(samplers.CANDIDATES)
    commit = git_commit()
    started_at = utc_now()

    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "artifact_type": "mindbench-results.v1",
        "generated_at": started_at,
        "producer": {"repo": "mindbench-ai/healthbench-psych", "commit": commit},
        "schema": os.path.relpath(SCHEMA_PATH, ROOT),
        "files": {},
    }
    for cand in candidates:
        payload = quantize(build_payload(cand, judges, subsets, commit, started_at))
        validate(payload, schema)  # R2.2: never write an invalid artifact
        text = json.dumps(payload, indent=2) + "\n"
        name = f"{BENCHMARK_SLUG}--{cand}.json"
        with open(os.path.join(args.out, name), "w") as f:
            f.write(text)
        manifest["files"][name] = f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"
        score = payload["metrics"][0]["value"]
        print(f"wrote {name}  (healthbench_score={score:.4f})")

    with open(os.path.join(args.out, "export-manifest.json"), "w") as f:
        f.write(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote export-manifest.json  ({len(candidates)} artifacts -> {args.out})")


if __name__ == "__main__":
    main()
