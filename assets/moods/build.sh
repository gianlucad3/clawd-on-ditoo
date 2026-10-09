#!/bin/sh
# Export the mood animations to the daemon's mood directory, and the one-shot
# scenes (assets/scenes: commit, push, compact, goodbye) to its asset directory.
# Usage: assets/moods/build.sh [moods_dir] [assets_dir]
#        (default ~/.clawd/moods and ~/.clawd/assets)
# Needs Node. Restart the daemon afterwards; it loads both only at startup.
set -e
here=$(cd "$(dirname "$0")" && pwd)
moods=${1:-$HOME/.clawd/moods}
assets=${2:-$HOME/.clawd/assets}
export_mjs="$here/../../.claude/skills/clawd-animation/references/export.mjs"
mkdir -p "$moods" "$assets"
for html in "$here"/*.html; do
  node "$export_mjs" "$html" "$moods/$(basename "$html" .html).json" --no-ground
done
for html in "$here"/../scenes/*.html; do
  node "$export_mjs" "$html" "$assets/$(basename "$html" .html).json" --no-ground
done
