#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
GOAL="${2:-}"

if [[ -z "$GOAL" ]]; then
  echo "用法：$0 deploy.env \"清晰、可验收的功能目标\"" >&2
  exit 2
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"

job_key="${JOB_KEY:-$(printf '%s' "$GOAL" | sha256sum | cut -c1-16)}"
base_ref="${PROJECT_GIT_REF:-main}"

create() {
  "$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" create "$@"
}

research_body=$(cat <<EOF
Goal:
$GOAL

Workstream: technical research and codebase reconnaissance.

Required output:
- relevant modules, symbols, tests, and constraints;
- implementation recommendation;
- risks and unresolved points;
- no project modifications.

Acceptance:
- findings are specific enough for a builder to implement;
- evidence includes paths, symbols, and primary-source references where applicable.
EOF
)

research_json="$(create \
  "Research: $GOAL" \
  --body "$research_body" \
  --assignee researcher \
  --workspace scratch \
  --max-runtime 20m \
  --max-retries 2 \
  --idempotency-key "$job_key:research" \
  --json)"
research_id="$(jq -r '.id' <<<"$research_json")"

if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  code_workspace="worktree"
else
  code_workspace="dir:$PROJECT_DIR"
fi

builder_body=$(cat <<EOF
Goal:
$GOAL

Read the parent research handoff before implementation.

Project base reference: $base_ref
Workspace policy: work only in \$HERMES_KANBAN_WORKSPACE.

Acceptance:
- implement the smallest complete change;
- add or update tests;
- run relevant verification;
- for Git, create a local commit and report branch + commit SHA;
- do not push or merge;
- include changed_files, verification, branch, commit, and residual_risk metadata.
EOF
)

builder_json="$(create \
  "Build: $GOAL" \
  --body "$builder_body" \
  --assignee builder \
  --parent "$research_id" \
  --workspace "$code_workspace" \
  --max-runtime 60m \
  --max-retries 2 \
  --idempotency-key "$job_key:build" \
  --json)"
builder_id="$(jq -r '.id' <<<"$builder_json")"

review_body=$(cat <<EOF
Goal under review:
$GOAL

Read the parent builder handoff. Use its reported branch and commit as the review target.
Base reference: $base_ref

Acceptance:
- inspect the actual diff;
- independently run appropriate tests/checks;
- assess correctness, regressions, security, and operability;
- return exactly PASS or FAIL with concrete evidence;
- do not modify production code.
EOF
)

review_json="$(create \
  "Review: $GOAL" \
  --body "$review_body" \
  --assignee reviewer \
  --parent "$builder_id" \
  --workspace "$code_workspace" \
  --max-runtime 30m \
  --max-retries 1 \
  --idempotency-key "$job_key:review" \
  --json)"
review_id="$(jq -r '.id' <<<"$review_json")"

accept_body=$(cat <<EOF
Final acceptance for:
$GOAL

Read the parent review handoff.

Policy:
- PASS with adequate evidence: complete this gate with verdict ACCEPTED.
- FAIL: create one narrowly scoped repair card for builder, a dependent re-review
  card for reviewer, and a new gate card dependent on that re-review. Complete this
  current gate with verdict REMEDIATION_SCHEDULED and the new graph IDs.
- Never describe a failed review as accepted.
- Do not implement any change yourself.
EOF
)

accept_json="$(create \
  "Gate: $GOAL" \
  --body "$accept_body" \
  --assignee orchestrator \
  --parent "$review_id" \
  --workspace scratch \
  --max-runtime 15m \
  --max-retries 1 \
  --idempotency-key "$job_key:accept" \
  --json)"
accept_id="$(jq -r '.id' <<<"$accept_json")"

"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" dispatch --max 2 >/dev/null || true

cat <<EOF
任务图已创建：
  research: $research_id
  build:    $builder_id
  review:   $review_id
  gate:     $accept_id

查看：
  $HERMES_BIN -p orchestrator kanban --board $BOARD_SLUG list
  $HERMES_BIN -p orchestrator kanban --board $BOARD_SLUG watch
  $HERMES_BIN -p orchestrator kanban --board $BOARD_SLUG show $accept_id
EOF
