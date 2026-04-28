#!/usr/bin/env bash
set -euo pipefail

# Sets the required Fly secrets and deploys.
# Run from the repo root after `fly auth login`.

if [ -z "${EQM_BEARER_TOKEN:-}" ]; then
  echo "EQM_BEARER_TOKEN must be set in environment before running this script." >&2
  exit 1
fi
if [ -z "${EQM_GIT_PUSH_TOKEN:-}" ]; then
  echo "EQM_GIT_PUSH_TOKEN must be set (GitHub PAT with repo:contents write)." >&2
  exit 1
fi

fly secrets set \
  EQM_BEARER_TOKEN="$EQM_BEARER_TOKEN" \
  EQM_GIT_PUSH_TOKEN="$EQM_GIT_PUSH_TOKEN" \
  EQM_GIT_REMOTE_URL="https://x-access-token:${EQM_GIT_PUSH_TOKEN}@github.com/cjmurphy4810/Entitlement-Quality-Monitor-Utility.git"

fly volumes list | grep -q eqm_data || fly volumes create eqm_data --size 1 --region iad

fly deploy
