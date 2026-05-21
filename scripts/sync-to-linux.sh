#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="paportug@phoenix93718.dev3sub2phx.databasede3phx.oraclevcn.com"
REMOTE_PATH="/home/paportug/GitHub/Exawatcher_ParserTool"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This directory is not a git repository. Run: git init && git switch -c macos" >&2
  exit 1
fi

current_branch="$(git branch --show-current)"
if [[ "${current_branch}" != "macos" ]]; then
  echo "Expected to sync from branch 'macos', but current branch is '${current_branch}'." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree has uncommitted changes. Commit before syncing." >&2
  exit 1
fi

ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_PATH}'"
ssh "${REMOTE_HOST}" "cd '${REMOTE_PATH}' && if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git init && git checkout -b linux; fi && git config receive.denyCurrentBranch updateInstead"
git remote remove linuxbox >/dev/null 2>&1 || true
git remote add linuxbox "ssh://${REMOTE_HOST}${REMOTE_PATH}"
git push linuxbox macos:macos macos:linux

ssh "${REMOTE_HOST}" "cd '${REMOTE_PATH}' && git switch linux"

echo "Synced macos branch to Linux and refreshed linux branch at ${REMOTE_HOST}:${REMOTE_PATH}"
