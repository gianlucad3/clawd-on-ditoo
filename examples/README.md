# Hands-free recipes

Ways to let Clawd run himself. Everything here just calls the generic
`clawd notify` / `clawd watch` surface — copy, tweak, done.

## Git hooks — react to your commits & merges

```bash
cp examples/git-hooks/post-commit .git/hooks/ && chmod +x .git/hooks/post-commit
cp examples/git-hooks/post-merge  .git/hooks/ && chmod +x .git/hooks/post-merge
cp examples/git-hooks/pre-push    .git/hooks/ && chmod +x .git/hooks/pre-push
```

`post-commit` plays the `commit` stamp (or a `pulse` if it isn't installed); `pre-push` launches the `push` rocket; `post-merge` throws confetti + says "Merged!".
Edit the scripts to taste (any `clawd notify …` works). Set `CLAWD_BIN` if your
checkout isn't at `~/code/divoom-pet`.

## Always-on PR/CI watcher (launchd)

Keep `clawd watch` following a repo across logins:

1. Edit `launchd/com.clawd.watch.plist` — set your username, `OWNER/REPO`, and path.
2. `cp examples/launchd/com.clawd.watch.plist ~/Library/LaunchAgents/`
3. `launchctl load ~/Library/LaunchAgents/com.clawd.watch.plist`

Stop it with `launchctl unload …`. Needs the pet daemon running (the menu-bar
app's **Launch at Login** covers that) and `gh` authenticated. Logs to
`/tmp/clawd-watch.log`.

## Test results — react when your suite finishes

Wrap your test command so Clawd reflects the result:

```bash
# put in your shell profile or a Makefile target
clawd-test() {
  if "$@"; then
    clawd notify banner "TESTS OK" --color green --say "Tests passed."
  else
    clawd notify banner "TESTS RED" --mood alert --say "Tests are failing."
  fi
}
# usage:  clawd-test pytest   |   clawd-test npm test
```
