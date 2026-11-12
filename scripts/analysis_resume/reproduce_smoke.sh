#!/bin/sh
# Offline only: parse the existing recorded roots and verify reconciliation.
set -eu
repo_path=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repo_path"
export PYTHONDONTWRITEBYTECODE=1
evidence_path=scripts/analysis_resume/baseline-repeat-2026-11-11/isolated-cli/smoke-evidence
root_base=/private/tmp/reflexforge-baseline-repeat-2026-11-11-4nkfx21u
.venv/bin/python scripts/analysis_resume/analyze.py \
  --artifact-root "$root_base/smoke-retry-01/artifacts" \
  --artifact-root "$root_base/smoke/artifacts" \
  --artifact-root "$root_base/train/artifacts" \
  --artifact-root "$root_base/dev/artifacts" \
  --output-dir "$evidence_path" --no-report
.venv/bin/python scripts/analysis_resume/report_smoke.py
# Refresh the input hashes after generating the report; no artifact is changed.
.venv/bin/python scripts/analysis_resume/analyze.py \
  --artifact-root "$root_base/smoke-retry-01/artifacts" \
  --artifact-root "$root_base/smoke/artifacts" \
  --artifact-root "$root_base/train/artifacts" \
  --artifact-root "$root_base/dev/artifacts" \
  --output-dir "$evidence_path" --no-report
.venv/bin/python scripts/analysis_resume/verify.py \
  --artifact-root "$root_base/smoke-retry-01/artifacts" \
  --artifact-root "$root_base/smoke/artifacts" \
  --artifact-root "$root_base/train/artifacts" \
  --artifact-root "$root_base/dev/artifacts" \
  --evidence-dir "$evidence_path"
