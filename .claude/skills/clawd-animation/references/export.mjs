#!/usr/bin/env node
// Render a Clawd animation HTML file at native 16×16 and write a Clawd asset
// manifest (the format `clawd notify play` reads from ~/.clawd/assets/).
// Each frame's `px` is flat RGB: 768 ints, pixel (x, y) at index (y*16 + x)*3,
// so row 15 is entries 720-767.
//
// Usage: node export.mjs <animation.html> [out.json] [--sheet sheet.png] [--no-ground]
//   --sheet      also write a contact sheet PNG (every frame, 10× scale) for review
//   --no-ground  leave out the ground row (row 15 stays free for the daemon's
//                session dots and progress bar)
//
// The animation must draw only through px() / fillRect with hex colors; any
// other canvas call (text, arcs, paths) is ignored here and will not reach the device.
import { readFileSync, writeFileSync } from 'node:fs';
import { basename } from 'node:path';
import { deflateSync } from 'node:zlib';

const args = process.argv.slice(2);
const sheetIdx = args.indexOf('--sheet');
const sheetPath = sheetIdx >= 0 ? args.splice(sheetIdx, 2)[1] : null;
const groundIdx = args.indexOf('--no-ground');
const noGround = groundIdx >= 0;
if (noGround) args.splice(groundIdx, 1);
const [src, outArg] = args;
if (!src) {
  console.error('usage: node export.mjs <animation.html> [out.json] [--sheet sheet.png] [--no-ground]');
  process.exit(1);
}

const html = readFileSync(src, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) throw new Error(`no inline <script> found in ${src}`);

const W = 16, H = 16;
const buf = new Float64Array(W * H * 3);

function parseHex(c) {
  let h = String(c).trim().replace(/^#/, '');
  if (h.length === 3) h = [...h].map(x => x + x).join('');
  if (!/^[0-9a-fA-F]{6}$/.test(h)) throw new Error(`only hex colors are supported, got "${c}"`);
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
}

const unsupported = new Set();
const target = {
  fillStyle: '#000000',
  globalAlpha: 1,
  fillRect(x, y, w, h) {
    const col = parseHex(this.fillStyle);
    const a = Math.max(0, Math.min(1, this.globalAlpha));
    for (let yy = Math.max(0, Math.floor(y)); yy < Math.min(H, Math.ceil(y + h)); yy++) {
      for (let xx = Math.max(0, Math.floor(x)); xx < Math.min(W, Math.ceil(x + w)); xx++) {
        const i = (yy * W + xx) * 3;
        for (let k = 0; k < 3; k++) buf[i + k] = buf[i + k] * (1 - a) + col[k] * a;
      }
    }
  }
};
const ctx = new Proxy(target, {
  get(t, k) {
    if (k in t) return t[k];
    return () => unsupported.add(String(k));
  },
  set(t, k, v) { t[k] = v; return true; }
});

const canvas = { width: W, height: H, getContext: () => ctx };
const info = { textContent: '' };
const document = { getElementById: id => (id === 'c' ? canvas : info) };
const api = new Function('document', 'requestAnimationFrame', 'window',
  scripts.join('\n') +
  (noGround ? "\n;if (typeof drawGround === 'function') drawGround = function () {};" : '') +
  '\n;return { render, resetLoop, FPS, TOTAL };'
)(document, () => {}, {});

api.resetLoop();
const ms = Math.round(1000 / api.FPS);
const frames = [];
for (let f = 0; f < api.TOTAL; f++) {
  buf.fill(0);
  api.render(f);
  frames.push({ ms, px: Array.from(buf, v => Math.round(v)) });
}

if (unsupported.size) {
  console.warn(`warning: ignored non-pixel canvas calls: ${[...unsupported].join(', ')}`);
}

const name = basename(src).replace(/\.html$/, '');
const out = outArg || src.replace(/\.html$/, '') + '.json';
writeFileSync(out, JSON.stringify({ name, loop: true, frames }));
console.log(`${name}: ${frames.length} frames x ${ms} ms -> ${out}`);

if (sheetPath) {
  writeFileSync(sheetPath, contactSheet(frames));
  console.log(`contact sheet -> ${sheetPath}`);
}

// ─── contact sheet PNG (no dependencies) ─────────────────────
function contactSheet(frames) {
  const S = 10, GAP = 4, COLS = Math.min(8, frames.length);
  const rows = Math.ceil(frames.length / COLS);
  const cw = W * S + GAP, ch = H * S + GAP;
  const iw = COLS * cw + GAP, ih = rows * ch + GAP;
  const img = Buffer.alloc(ih * (iw * 3 + 1), 0x80);
  for (let y = 0; y < ih; y++) img[y * (iw * 3 + 1)] = 0;  // filter byte: none
  frames.forEach((fr, n) => {
    const ox = GAP + (n % COLS) * cw, oy = GAP + Math.floor(n / COLS) * ch;
    for (let y = 0; y < H * S; y++) {
      for (let x = 0; x < W * S; x++) {
        const s = (Math.floor(y / S) * W + Math.floor(x / S)) * 3;
        const d = (oy + y) * (iw * 3 + 1) + 1 + (ox + x) * 3;
        img[d] = fr.px[s]; img[d + 1] = fr.px[s + 1]; img[d + 2] = fr.px[s + 2];
      }
    }
  });
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(iw, 0); ihdr.writeUInt32BE(ih, 4);
  ihdr[8] = 8; ihdr[9] = 2;  // 8-bit RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', deflateSync(img)), chunk('IEND', Buffer.alloc(0))
  ]);
}

function crc32(b) {
  let c = ~0;
  for (const byte of b) {
    c ^= byte;
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
