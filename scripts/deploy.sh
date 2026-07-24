#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing deployment: the worktree is not clean." >&2
  exit 1
fi

git fetch origin master
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]]; then
  echo "Refusing deployment: HEAD does not exactly match origin/master." >&2
  exit 1
fi

flyctl deploy --remote-only --config fly.toml
curl --fail --retry 12 --retry-delay 5 https://zamzam-api.fly.dev/health

