#!/usr/bin/env bash
# Audit that a release tag on GitHub and the same tag on Hugging Face agree.
#
# The run data (responses, grades) lives on HF, not in this repo, so GitHub
# cannot BUILD the dataset -- but it can PROVE the two surfaces describe the
# same release. This script does that for one tag:
#
#   1. take the tag's own subsets and committed matrices (git show TAG:path)
#   2. fetch responses + grades from HF at the SAME tag name
#   3. recompute every committed matrix with eval/aggregate.py
#   4. diff the recomputed matrices against the tag's committed ones
#
# Zero diff means: the HF payload at TAG reproduces exactly the numbers the
# repo at TAG claims. A subset mismatch surfaces as a diff too, because
# n_prompts is a matrix column.
#
# Runs current tooling against the tag's DATA. That is deliberate: a tag made
# before this script existed (v1.0.0) has no --revision flag and no workflow,
# so the auditor has to be whatever branch carries this file. If tooling ever
# drifts such that it cannot reproduce an old release, this is where that
# shows, and it should.
#
# Needs: git with the tag fetched, python3 (stdlib only), network to HF.
# No secrets. Writes eval/runs/{responses,grades} -- run in a clean checkout.
#
#   .github/scripts/audit_release.sh v1.0.0
set -euo pipefail

TAG="${1:?usage: audit_release.sh vX.Y.Z}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
  || { echo "::error::tag $TAG not present locally (fetch tags first)"; exit 1; }

echo "== audit $TAG  (tooling: $(git rev-parse --short HEAD), data: $(git rev-parse --short "$TAG^{commit}"))"

# 1. the tag's own view of subsets, matrices, and the anomaly log
git checkout -q "$TAG" -- eval/subsets 'eval/runs/matrix_*.csv' eval/runs/errors.jsonl 2>/dev/null \
  || git checkout -q "$TAG" -- eval/subsets eval/runs/errors.jsonl
# (no mapfile: macOS ships bash 3.2, and this must run locally as well as in CI)
MATRICES=()
while IFS= read -r line; do [ -n "$line" ] && MATRICES+=("$line"); done \
  < <(git ls-tree -r --name-only "$TAG" -- eval/runs | grep -E 'matrix_.*\.csv$' || true)
[ "${#MATRICES[@]}" -gt 0 ] || { echo "::error::no committed matrices at $TAG -- nothing to audit"; exit 1; }
echo "== committed matrices at $TAG:"; printf '   %s\n' "${MATRICES[@]}"

# 2. run data from HF at the same tag (fails here if HF is not tagged)
rm -rf eval/runs/responses eval/runs/grades
python3 eval/fetch_runs.py --revision "$TAG" --force

# 3. recompute
for m in "${MATRICES[@]}"; do
  subset="$(basename "$m" .csv)"; subset="${subset#matrix_}"
  echo "== aggregate --subset $subset"
  python3 eval/aggregate.py --subset "$subset" >/dev/null
done

# 4. compare against the tag, not HEAD
echo "== diff recomputed matrices vs $TAG"
if git diff --exit-code --stat "$TAG" -- "${MATRICES[@]}"; then
  echo "== PASS: HF@$TAG reproduces every matrix committed at $TAG"
  {
    echo "### Release audit: \`$TAG\` PASS"
    echo "HF revision \`$TAG\` reproduces every committed matrix byte-for-byte:"
    printf -- '- `%s`\n' "${MATRICES[@]}"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
else
  echo "::error::FAIL: recomputed matrices differ from $TAG (see diff above)"
  git diff "$TAG" -- "${MATRICES[@]}" | head -60
  exit 1
fi
