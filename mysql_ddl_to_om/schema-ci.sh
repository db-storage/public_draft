#!/usr/bin/env bash
# CI-provider-neutral generator. No OM token needed; no network is used here.
set -euo pipefail
: "${SCHEMA_HEAD_SHA:?Set the exact target commit SHA}"
SCHEMA_MODE="${SCHEMA_MODE:-diff}"
SCHEMA_TOOL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
args=(
  --mode "$SCHEMA_MODE"
  --repo "${SCHEMA_REPO:-.}"
  --head "$SCHEMA_HEAD_SHA"
  --config "${SCHEMA_MAPPING:-om-mapping.json}"
  --security-classification "${SCHEMA_SECURITY_CLASSIFICATION:-Security}"
  --output "${SCHEMA_OUTPUT_DIR:-om-artifact}"
)
if [[ "$SCHEMA_MODE" == diff ]]; then
  : "${SCHEMA_BASE_SHA:?Set the PR base or merge-before SHA}"
  args+=(--base "$SCHEMA_BASE_SHA" --comparison "${SCHEMA_COMPARISON:-merge-base}")
fi
if [[ -n "${SCHEMA_RENAMES:-}" ]]; then
  args+=(--renames "$SCHEMA_RENAMES")
fi
exec python "$SCHEMA_TOOL_DIR/pr_diff_to_om.py" "${args[@]}"
