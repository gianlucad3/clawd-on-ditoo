# Clawd moods

Sources for the daemon's mood animations, drawn with the
`clawd-animation` skill (`.claude/skills/`). Each `<mood>.html` replaces
that mood's built-in sprites; `<mood>.<variant>.html` adds a variant:

- `sporty.*`: no main loop, so one activity plays per loop in shuffled order.
- `coding.*`: specials (rubber duck, whiteboard, reading) that lead the
  main `coding` loop about once a minute.
- `tool_use.*`: picked by the running tool instead of rotating: `bash`
  (Bash), `edit` (Edit/Write), `read` (Read/Grep/Glob), `web` (WebFetch/
  WebSearch), `task` (subagents). Other tools play `tool_use`.
- `alert.*`: picked by the event too: `alert.permission` (permission
  prompt) and `alert.waiting` (waiting for your input).

One-shot scenes live in `../scenes/` and install to `~/.clawd/assets`, where
`clawd notify play <name>` and the hooks play them: `commit` and `push` (the
git hooks in `examples/git-hooks`), `tests-pass` / `tests-fail` (a Bash
test run passes / fails), `compact` (PreCompact) and `goodbye` (SessionEnd).

Install them with

    assets/moods/build.sh          # writes ~/.clawd/moods and ~/.clawd/assets

then restart the daemon (`bin/clawd start`). `clawd start --no-moods`
goes back to the built-in sprites. To change a mood, edit its HTML (open
it in a browser to preview) and rerun `build.sh`.

To review them all at once, draw every frame into one PNG (needs Pillow):

    python3 assets/moods/overview.py   # writes ~/.clawd/moods-overview.png
