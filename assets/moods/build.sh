#!/bin/sh
# Export every mood animation here to the daemon's mood directory.
# Usage: assets/moods/build.sh [out_dir]   (default ~/.clawd/moods)
# Needs Node. Restart the daemon afterwards; it loads moods only at startup.
set -e
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$HOME/.clawd/moods}
export_mjs="$here/../../.claude/skills/clawd-animation/references/export.mjs"
mkdir -p "$out"
for html in "$here"/*.html; do
  name=$(basename "$html" .html)
  node "$export_mjs" "$html" "$out/$name.json" --no-ground
done
