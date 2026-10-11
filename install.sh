#!/usr/bin/env bash
# Installs t3code-customize and builds it for your T3 Code Nightly (macOS or Linux).
# Usage: bash -c "$(curl -fsSL https://raw.githubusercontent.com/tomertec/t3code-customize/main/install.sh)"
set -euo pipefail
for tool in git python3; do
  command -v "$tool" >/dev/null || { echo "$tool is required. Install it and run this again." >&2; exit 1; }
done
repo="${XDG_DATA_HOME:-$HOME/.local/share}/t3code-customize/repo"
if [[ -d "$repo/.git" ]]; then
  git -C "$repo" pull --ff-only --quiet
else
  mkdir -p "$(dirname "$repo")"
  git clone --quiet https://github.com/tomertec/t3code-customize "$repo"
fi
exec "$repo/t3code-customize" "$@"
