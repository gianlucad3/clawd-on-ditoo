---
name: clawd-animation
description: Clawd pixel-art animation generator for a 16×16 LED display (Divoom Ditoo / Timebox). From the user's natural-language description, generates a self-contained HTML pixel-art animation on a 16×16 grid starring Clawd, the Claude Code mascot (a pixel-art little crab), and exports it as a Clawd asset manifest the device can play. Always use this skill when the user mentions clawd, a clawd animation, pixel animation, making a little animation for clawd, having the little crab do something, or any request to create an animated scene with the Clawd character. Trigger even if the user only says "have the little crab comfort me" or "working with the little crab today was great". Judge the depth of the requested interaction — if the user only wants a "quick/simple animation" or a "single-state expression", use clawd-animation-lite (fewer tokens, shorter duration) instead of this skill.
---

# Clawd Pixel-Art Animation Generator (16×16)

## Your Role

You are the creative engine for Clawd pixel animations. The user gives you one sentence (e.g. "clawd holding an umbrella in the rain") and you generate an HTML animation file that previews in a browser, then export it to a manifest that plays on a 16×16 LED panel.

Clawd is the official mascot of Claude Code — a pixel-art little crab with a warm color scheme (coral orange #CD6E58) and a flat, cute shape. Every animation must stay faithful to this visual identity.

16×16 is 256 pixels in total. Every design decision follows from that: one cell is 6% of the screen, a 1-cell move is a big move, and there is no room for text.

## Workflow

After receiving the user's description, follow these steps:

### Step 1: Parse the intent

Extract from the description:
- **Core action**: what clawd does (eating, dancing, holding an umbrella in the rain...)
- **Emotional tone**: happy, curious, lazy, surprised...
- **Props needed**: food, weather elements, objects...
- **Scene atmosphere**: defaults to a dark sky with a few twinkling stars and a ground row

Then pick the Clawd size:
- **Full Clawd (14×8)** when Clawd is the whole scene: emotions, reactions, weather around Clawd
- **Mini Clawd (10×5)** when a prop needs its own space next to Clawd

### Step 2: Design the animation script

Split the animation into 2-5 phases. Story-like moments follow a narrative arc:

```
Intro → Discovery/Trigger → Core action (may span several phases) → Emotional climax/Wrap-up
```

Ambient loops (idle, waiting, sleeping) don't need an arc or a climax: a calm cycle of small changes (breathing, glances, a blink) is the right shape for them.

For each phase define:
- Its length in frames (all phases add up to `TOTAL`)
- Clawd's position and movement
- Expression changes (eyes)
- Prop state changes
- Icons/particles

The device plays **8 FPS (125 ms per frame)**. Keep the loop to **3-5 seconds (24-40 frames)**, default 4 seconds. Every phase needs at least 3-4 frames to read; a 1-frame phase is invisible. Exception: fast repeated motion (exercise reps, typing) reads fine as a 4-5 frame cycle with 1-frame in-between poses.

### Step 3: Design new prop sprites

If the scene needs a prop the template doesn't have:
1. Design the prop's pixel matrix: at most **6×6 cells** next to mini Clawd, smaller next to full Clawd
2. Use colors already in the palette, or add 1-3 new colors to PALETTE
3. At most 4 colors per prop, including one white highlight pixel for texture
4. Data format: a 2D array of color keys drawn with `drawSprite(rows, x, y, colors)` (see the ICECREAM sprite in `references/ice-cream.html`)

Prop design principles:
- Silhouette first: the prop must be recognizable from its outline and main color alone
- Use bold, saturated colors that contrast with Clawd's coral and the black background
- No outlines; at this size a 1-pixel outline eats half the shape

### Step 4: Generate code from the template

1. Read `references/template.html` as the base
2. Keep the engine functions (px, drawSprite, drawClawd, drawClaw, drawIcon, drawStars, particles, easing, phase, loop) unchanged. Data tables are yours to extend: add colors to `PALETTE`, icons to `ICONS`, and edit or drop `STARS` if a scene needs it
3. Replace the `=== YOUR ANIMATION HERE ===` region (it runs until the LOOP section) with:
   - `NAME`, `FPS`, `DUR` and `TOTAL`
   - `PHASES`: a list of `[name, frames]` that adds up to `TOTAL`, read with `phase(f, PHASES)` → `{ ph, i, n, pt }` (`i` = frame within the phase, `pt` = 0..1)
   - Sprite data and draw functions for new props
   - The full animation logic in `render(f)`
4. Update `<title>`

### Step 5: Export, review, deliver

1. Save the HTML file with an English kebab-case filename (e.g. `rainy-umbrella.html`). The filename becomes the manifest name, so a mood file must be named exactly after the mood or variant (`idle.html`, `sporty.tea.html`)
2. Export it at native resolution with a contact sheet:
   ```
   node <this skill's directory>/references/export.mjs rainy-umbrella.html rainy-umbrella.json --sheet rainy-umbrella.png
   ```
   Add `--no-ground` to leave out the ground row, keeping row 15 free for the daemon's session dots and progress bar. Mood animations for the daemon should always be exported with `--no-ground`, so never rely on the ground to hide anything (e.g. feet).
3. **Look at the contact sheet** (Read the PNG) before delivering. Check that Clawd and the props are recognizable in every frame, icons don't merge with other shapes, and the last frame flows into the first. Fix and re-export if not.
4. Unless the user only asked for the files, tell them how to play it on the device. The daemon loads `~/.clawd/assets/` only at startup, so it must be restarted after copying a new manifest, and it must run in a regular terminal (the Claude Code sandbox blocks its port):
   ```
   cp rainy-umbrella.json ~/.clawd/assets/
   # restart the Clawd daemon, then:
   clawd notify play rainy-umbrella
   ```
   A manifest named after a mood (`idle`, `thinking`, `typing`, `tool_use`, `happy`, `alert`, `sleeping`, `hatch`, `poke`, `coding`, `sporty`) can instead go in `~/.clawd/moods/`, where it replaces that mood's built-in animation after a daemon restart. Name variants `<mood>.<variant>` (e.g. `sporty.tea`, `coding.whiteboard`): a mood with only variants plays one per loop in shuffled order; a mood with a main file plus variants plays a variant before the main loop about once a minute. `tool_use`, `alert` and `happy` are the exception: their variants are chosen by the event (`tool_use.bash`, `.edit`, `.read`, `.web`, `.task` by tool; `alert.permission`, `alert.waiting`, `alert.tests`, `happy.tests`; see `variant_for` in `divoom_pet/daemon/moods.py`). One-shot scenes played with `clawd notify play` go in `assets/scenes/` and install to `~/.clawd/assets`. Short moods are timed and fall back to idle after about this long: `poke` 1.6 s, `happy` 2.6 s, `alert` 3 s, `hatch` 3.5 s, `tool_use` 4 s. They end on the loop boundary nearest that time, so a one-shot intro like `hatch` should run close to its timeout and end on a calm standing pose; it need not loop seamlessly. Variants of one mood play back to back, so they must share the same first and last frame (same pose, same background, e.g. all with or all without stars). With `--no-ground` full Clawd's feet are on row 14, so there is no room for floor props (mats, cushions) under him.

---

## Design Rules (must not be violated)

### Pixel grid
- Logical grid is 16×16 — the device's native resolution
- The browser preview canvas is 480×480 (30 screen pixels per cell); `PX` is derived from the canvas, never hard-coded
- All drawing goes through `px(gx, gy, color, alpha)` or helpers built on it (`drawSprite`, `drawIcon`, `drawClawd`...). Never call `fillText`, `arc` or paths: the exporter only captures `fillRect`, so anything else never reaches the device
- Colors are hex strings only
- Canvas must set `image-rendering: pixelated`

### Clawd's shape
Full (14×8) and mini (10×5) bodies, eye anchors and hand anchors are defined in the `CLAWD` and `CLAWD_MINI` objects in template.html — use them as-is, never redraw Clawd.

Standard positions:
- Full Clawd standing on the ground: `drawClawd(1, 7)` (rows 7-14, ground on row 15)
- Mini Clawd standing on the ground: `drawClawd(x, 10, { mini: true })` (rows 10-14)
- Icons above full Clawd's head go in rows 0-5, columns 3-12; stars stay in columns 0-1 and 14-15, clear of centered icons; when a prop or icon goes near the edge (a sweat drop at column 13), hide the stars it would touch with `drawStars(f, [[x, y]])`

Key constraints:
- Body is a single flat color `#CD6E58`, no gradients, no shadows
- Eyes are 1×1 pure black pixels, **no mouth** — emotion is expressed through eye direction + blush + icons + particles
- Eye variants (`drawClawd(x, y, { eyes })`):
  - `forward`, `look_left`, `look_right` (only the inner eye moves, so the outline stays clean), `look_down`
  - `look_up`: eyes on the head's top edge; reads as looking up, but use it for a few frames only
  - `blink`: no eyes; 1-2 frames only, longer reads as a blank face
  - `closed`: dark lids, for sleeping and eyes-shut moments
  - `happy`: ^^ lids, for joy and delight (clearest on full Clawd)
- Body poses:
  - `drawClawd(x, y, { squash: true })`: exhale pose, body one row lower with shorter legs and the feet planted. `breathe(f, period)` alternates it for a looping breath
  - `drawClaw(x, y, side, pose)` after drawClawd: `'wave'` (straight up, cheering/alarm), `'raise'` (one cell up, thinking/claw to chin), `'down'` (reaching down, typing/pressing), `'out'` (diagonal up and out, big celebration; can reach the screen edge). Pass `{ squash }` when the body is squashed
  - Blush: `drawClawd(x, y, { blush: 0.8 })`, which always draws it on top of the body

### Palette / background
Fully defined in the `PALETTE` object in template.html. Always reference colors from PALETTE; never hard-code hex. Add new prop colors to PALETTE.

The display is an LED matrix: black is "LED off". Keep the background black or very dark and never fill large areas with white or pale colors — they glare on the device and wash out Clawd.

### Text
There is no room for text. Speech bubbles are replaced by icons from `ICONS`: `exclaim` (discovery), `question` (confusion), `check` (success), `heart` / `heartTiny` (love), `sparkle` (delight), `note` (music), `z` / `zSmall` (sleep), `sweat` (nervous). Add new icons to `ICONS` in the same format if needed (≤5×5). To show part of an icon (dots appearing one by one), draw single pixels with `px`.

---

## Animation Quality Standards

### Rhythm
- The animation needs a clear beginning, development, turn and resolution — not uniform motion
- Movement happens in whole cells. Use easeOut for entrances and easeInOut for movement, rounded to integers (`px` rounds for you)
- Hops are 1 cell; a 2-cell jump is already dramatic
- Hold key poses for 2-3 frames so they register; mark key moments with an icon or a short particle burst

### Expressiveness
- Clawd's expression must follow the story (eyes look at the target when discovering something, blink while eating)
- Use bounce to express emotion — hop when happy, step back one cell when surprised
- Use an icon at key emotional beats (`exclaim` for discovery, `heart` for love)
- End on a clear emotional beat (hearts, sparkles, blush)

### Readability at 16×16
- One focal point at a time: don't show an icon, particles and a moving prop all at once
- Keep icons and particles at least one cell away from Clawd's body and from each other, or they merge into a blob
- Particles: 2-4 per burst. More than that turns into noise. `addParticle(x, y, color, { life, vx, vy, gravity })`: by default a particle lives 10 frames, rises ~0.3-0.8 cells per frame and falls back under gravity 0.08. Shorten `life` near props and make sure every particle has died before the loop seam
- Faded pixels (alpha) show as dimmer LEDs. On the contact sheet, faded yellow, orange and green look brown; that's the monitor, but keep fades short (2-3 frames) and above ~40% (yellow already looks brown at 60%, so avoid fading it) except on the way out, because very dim pixels lose their hue

### Loop design
- The start and end must loop seamlessly
- `resetLoop()` runs at the start of each loop: it clears particles and resets the RNG seed
- Use only `rand()` for randomness, never `Math.random()`, so every loop and the device export are identical
- Entrances may start from off-screen (`px` skips off-grid cells), so each loop's starting point feels natural

### Technical constraints
- Single HTML file, zero external dependencies
- All sprite data inlined in `<script>`
- 8 FPS, at most 40 frames per loop (more frames make the Bluetooth upload slower)
- File size under 20KB

---

## Complexity Limits

This system suits **single-character, single-scene, simple-narrative** short animations.

Reasonable requests:
- "clawd eats ice cream" → walks over, eats bite by bite, happy
- "clawd holds an umbrella in the rain" → rain falls, opens umbrella, raindrops bounce off
- "clawd gets a letter" → letter drops in, Clawd looks at it, heart
- "clawd is sleepy" → slow blinks, eyes close, zzz rises

Out-of-scope requests (politely ask the user to simplify):
- Multiple interacting characters (there is no room for two crabs)
- Detailed scenery or scene changes
- Anything that depends on readable text or small details
- Non-looping narratives longer than 5 seconds
- Animations requiring user input/interaction

---

## Reference Files

| File | When to read | Contents |
|------|---------|------|
| `references/template.html` | Every time | The 16×16 animation engine with all draw functions, sprites, icons and the loop |
| `references/export.mjs` | Run it every time (no need to read it) | Renders the HTML at 16×16 and writes the device manifest and a contact sheet PNG. Only `fillRect` with hex colors reaches the device; any other canvas call is reported as a warning. Each frame's `px` is flat RGB (768 ints; pixel (x, y) at index `(y*16 + x)*3`, so row 15 is entries 720-767) |
| `references/ice-cream.html` | **Only** if you're unsure about multi-phase pacing or prop design | Prop example: mini Clawd, a 5×6 ice cream, 5 phases over 40 frames, bites, crumbs, a floating heart |
| `references/clawd-kiss.html` | When you need a reference for emotion without props | Emotion example: full Clawd, 4 phases over 24 frames, told with eyes, blush and hearts (no mouth) |

---

## Full Example

**User input:** "clawd eats ice cream"

**Claude's thought process:**
1. Core action: eating ice cream (bite by bite)
2. Emotional arc: curious → excited → satisfied → happy
3. Size: the ice cream needs space, so mini Clawd (10×5)
4. Prop: two-scoop cone, 5×6, mint/strawberry/cone + white highlight (4 colors)
5. Phase design (40 frames): enter(6) → spot(6) → approach(4) → eat×3(14) → happy(10)
6. Expression plan: forward → look_right + "!" (discovery) → look_right (walking over) → blink on each bite → blush + heart (happy)

**Output:** `ice-cream.html` + `ice-cream.json` — see `references/ice-cream.html`
