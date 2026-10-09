---
name: clawd-animation-lite
description: Clawd pixel-art animation generator for a 16×16 LED display, lite version. From the user's natural-language description, generates a short 1-3 second clawd animation on a 16×16 grid and exports it as a Clawd asset manifest the device can play. When the requested interaction is specific and single-focused, use this lite version for low token use and fast generation. The star is Clawd, the Claude Code mascot (a pixel-art little crab). Always use this skill when the user mentions clawd, a clawd animation, pixel animation, making a little animation for clawd, having the little crab do something, or any lightweight request to create an animated scene with the Clawd character. Trigger even if the user only says "make clawd happy" or "make a little crab animation".
---

# Clawd Pixel-Art Animation Generator (16×16, lite)

You are the creative engine for Clawd pixel animations. The user gives you one sentence and you generate an HTML animation file on a 16×16 grid, then export it for the 16×16 LED panel.

Clawd is the Claude Code mascot — a pixel-art little crab in coral orange (#CD6E58), flat and cute, with no mouth. The whole screen is 256 pixels: one cell is a big move and there is no room for text.

This skill shares its engine with the full `clawd-animation` skill, which must be installed next to it: the files are in `../clawd-animation/references/` relative to this skill's directory (below: `ENGINE`).

## Workflow

1. **Parse**: extract the core action, emotion and props needed from the description
2. **Choreograph**: design 1-2 phases, total duration 1-3 seconds at 8 FPS (default 2 seconds = 16 frames)
3. **Generate**: copy `ENGINE/template.html` and replace only the `=== YOUR ANIMATION HERE ===` region (it runs until the LOOP section) with `NAME`, `FPS`, `DUR`, `TOTAL`, optional `PHASES`, and `render(f)`. Update `<title>`, and add colors to PALETTE if needed
4. **Export and check**:
   ```
   node ENGINE/export.mjs shy-clawd.html shy-clawd.json --sheet shy-clawd.png
   ```
   Add `--no-ground` to leave out the ground row (always, for daemon moods). Read the contact sheet PNG. Fix anything unreadable (merged shapes, icons touching Clawd, a jump at the loop seam) and re-export.
5. **Deliver** (skip if the user only wants the files): copy the manifest to `~/.clawd/assets/` (or to `~/.clawd/moods/` if it's named after a mood such as `idle` or `happy`, to replace that mood), restart the Clawd daemon (it loads animations only at startup, and must run in a regular terminal), then run `clawd notify play shy-clawd`

## Available API

| Function | Purpose | Parameters |
|------|------|------|
| `drawClawd(ox,oy,opts)` | Draw Clawd | opts: `{eyes, mini, squash, blush}`; eyes: `'forward'` `'look_left'` `'look_right'` `'look_down'` `'look_up'` `'blink'` `'closed'` `'happy'` |
| `drawClaw(ox,oy,side,pose,opts)` | Claw pose, after drawClawd | side: `'left'` / `'right'`; pose: `'wave'` (up) `'raise'` (1 up) `'down'` (reach down) `'out'` (diagonal); opts: `{mini, squash}` |
| `breathe(f,period)` | Looping breath: true on exhale frames; pass as `squash` | period in frames, a divisor of TOTAL |
| `drawIcon(name,x,y,color,alpha)` | Icon (replaces text) | `heart` (5×4) `heartTiny` `exclaim` `question` `check` `sparkle` `note` `z` `zSmall` `sweat` |
| `drawSprite(rows,x,y,colors,alpha)` | Draw a custom prop from a 2D array of color keys | colors: `{key: hexColor}` |
| `drawBg()` / `drawStars(f,hide)` / `drawGround(row)` | Black background, side-column stars, ground row 15 | hide: `[[x,y],…]` stars to skip |
| `addParticle(x,y,color,opts)` / `tickParticles()` | Particle system | opts: `{life (frames, default 10), vx, vy, gravity}` |
| `phase(f,PHASES)` | Current phase from `[[name, frames], …]` | returns `{ph, i, n, pt}` |
| `rand()` | Seeded random number 0-1 (never use `Math.random()`) | — |
| `px(gx,gy,color,alpha)` | Draw a single pixel cell; combine freely to draw any prop | — |
| `easeOut(t)` / `easeInOut(t)` / `lerp(a,b,t)` | Easing | — |

Standard positions: full Clawd (14×8) on the ground is `drawClawd(1, 7)`; mini Clawd (10×5) is `drawClawd(x, 10, { mini: true })`. Icons above full Clawd go in rows 0-5, columns 3-12.

## Animation Pattern Library

**Important: pick the pattern that fits the user's description; don't always reuse the examples' structure.**

### A. Static expression (for: shy, angry, confused, touched)
Full Clawd stays in place; emotion comes from eye changes, blush, and one icon.
```
render: drawClawd(1,7,{eyes, blush}) → icon fades in with pt
Motion comes from: eye changes + blush + an icon appearing + breathe(f)
```

### B. Movement (for: running, hopping, entering)
Clawd moves in whole cells; use lerp+easeOut for displacement and 1-cell hops.
```
render: cx/cy change with pt → drawClawd(cx,cy,{eyes})
Motion comes from: displacement + hops + optional icon at the end
```

### C. Prop interaction (for: eating, finding treasure, holding a flag)
Mini Clawd plus a custom prop drawn with drawSprite. Props ≤6×6 cells, ≤4 colors.
```
render: drawSprite(prop) → drawClawd(x,10,{mini:true}) next to it → reaction icon
Motion comes from: prop appearing/changing + Clawd's reaction (exclaim → blink → heart)
```

### D. Ambient environment (for: rain, snow, falling leaves)
Clawd stays still; a few environment pixels loop around it.
```
render: drawBg → environment pixels (positions computed from f, so they loop) → drawClawd
Motion comes from: 4-8 moving pixels + small Clawd reactions (looking up, blinking)
```

## Body Motion Tricks

- **Breathing**: `drawClawd(1, 7, { squash: breathe(f, 8) })` — the feet stay planted, so nothing needs hiding
- **Hop**: `cy - 1` for one or two frames; on 16×16 a 1-cell hop already reads clearly
- **Waving**: `drawClaw(cx, cy, f % 4 < 2 ? 'left' : 'right', 'wave')`
- **Typing**: alternate `drawClaw(cx, cy, 'left', 'down')` and `'right'` every 1-2 frames
- **Startle**: step back one cell (`cx - 1`) and show `exclaim`
- **Sleepy**: `closed` eyes with `breathe`, a `zSmall` then a `z` rising beside the head

## Design Rules

- Grid 16×16 (device native); preview canvas 480×480; all drawing through `px()` and the helpers — never `fillText` or `arc` (they don't reach the device)
- Body is a single color `#CD6E58`, no gradients, no shadows; never redraw Clawd's body, use `drawClawd` options and `drawClaw` poses
- Black background (black is "LED off"); no big white or pale areas
- No text: use icons. Keep icons and particles at least one cell away from Clawd and from each other
- Express emotion by combining **eye direction + blush + one icon**; don't use hearts every time
- `blink` is for 1-2 frames; for eyes shut longer use `closed`, for joy use `happy`
- 2-4 particles per burst at most; make sure they've died before the loop seam
- Keep fades short: faded colors look brown on the contact sheet and lose their hue when very dim
- Start and end loop seamlessly; at most 24 frames
- Single HTML file, zero dependencies, hex colors only, add new colors to PALETTE

## Complexity Limits

Suitable: short single-character, single-scene animations with 1-2 action phases.
Out of scope (ask the user to simplify): multiple characters, scene changes, readable text, narratives longer than 3 seconds.

## Example A: Movement — "clawd happily hopping"

```javascript
// === YOUR ANIMATION HERE ====================================
const NAME = 'happy hop';
const FPS = 8;
const DUR = 2;
const TOTAL = FPS * DUR;
const PHASES = [['enter', 6], ['happy', 10]];

function render(f) {
  const { ph, pt } = phase(f, PHASES);
  drawBg(); drawStars(f); drawGround();

  let cx = 1, cy = 7, eyes = 'forward', blush = 0;

  if (ph === 'enter') {
    cx = Math.round(lerp(-14, 1, easeOut(pt)));
    cy = 7 - (f % 2);                       // hop on every other frame
  } else {
    cy = 7 - (Math.floor(pt * 4) % 2);      // two happy hops
    eyes = 'happy';
    blush = 0.8;
    drawIcon('heart', 6, Math.round(lerp(1, 0, pt)), PALETTE.fx.heart);
    if (f % 4 === 0) addParticle(rand() < 0.5 ? 1 : 14, 4, PALETTE.ui.mark, { life: 4 });
  }

  drawClawd(cx, cy, { eyes, blush });
  tickParticles();
}
```

## Example B: Static expression — "shy clawd"

```javascript
// === YOUR ANIMATION HERE ====================================
const NAME = 'shy clawd';
const FPS = 8;
const DUR = 2;
const TOTAL = FPS * DUR;

function render(f) {
  const t = f / TOTAL;
  drawBg(); drawStars(f); drawGround();

  // eyes: look forward first → glance aside → look down
  const eyes = t < 0.3 ? 'forward' : t < 0.5 ? 'look_right' : 'look_down';
  // blush fades in, then fades out in the last frames so the loop is seamless
  const blush = t < 0.25 ? 0 : t < 0.85 ? Math.min((t - 0.25) * 3, 0.8) : (1 - t) * 5;

  drawClawd(1, 7, { eyes, blush, squash: breathe(f, 8) });
  // a sweat drop beside the head in the second half
  if (t > 0.55 && t < 0.9) drawIcon('sweat', 13, 5, PALETTE.stars.bright);
  tickParticles();
}
```

Output filename: an English phrase from the description, e.g. `shy-clawd.html`, `rainy-day.html`
