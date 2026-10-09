# Clawd moods

Sources for the daemon's mood animations, drawn with the
`clawd-animation` skill (`.claude/skills/`). Each `<mood>.html` replaces
that mood's built-in sprites; `<mood>.<variant>.html` adds a variant:

- `sporty.*`: no main loop, so one activity plays per loop in shuffled order.
- `coding.*`: specials (rubber duck, whiteboard, reading) that lead the
  main `coding` loop about once a minute.

Install them with

    assets/moods/build.sh          # writes ~/.clawd/moods/*.json

then restart the daemon (`bin/clawd start`). `clawd start --no-moods`
goes back to the built-in sprites. To change a mood, edit its HTML (open
it in a browser to preview) and rerun `build.sh`.
