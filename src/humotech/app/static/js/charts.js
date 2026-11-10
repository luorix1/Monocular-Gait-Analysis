// Small SVG charts drawn at the container's real pixel width (re-drawn on resize).
// Left = series slot 1 (blue), Right = slot 2 (orange); text always in ink tokens.
import { h, clear } from "./ui.js";

export const SIDES = { L: { label: "Left", color: "var(--series-l)" }, R: { label: "Right", color: "var(--series-r)" } };

function ticks(lo, hi, n = 5) {
  if (!(hi > lo)) { hi = lo + 1; }
  const step0 = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || 10 * mag;
  // the axis spans whole steps that enclose [lo, hi], so no data falls outside the plot
  const out = [];
  const end = Math.ceil(hi / step - 1e-9) * step;
  for (let v = Math.floor(lo / step + 1e-9) * step; v <= end + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return { list: out, step };
}
const dec = (step) => Math.max(0, -Math.floor(Math.log10(step) + 1e-9));

function responsive(container, drawFn) {
  let w = 0;
  const ro = new ResizeObserver(() => {
    const nw = Math.floor(container.clientWidth);
    if (nw && Math.abs(nw - w) > 2) { w = nw; drawFn(w); }
  });
  ro.observe(container);
  return () => ro.disconnect();
}

function frame(svg, { W, H, m, x, y, xt, yt, xLabel, yLabel }) {
  const grid = h("g", { class: "grid" });
  yt.list.forEach((v) => grid.append(h("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) })));
  const ax = h("g", { class: "axis" }, h("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
  const tk = h("g", { class: "tick" });
  yt.list.forEach((v) => tk.append(h("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }, v.toFixed(dec(yt.step)))));
  xt.list.forEach((v) => tk.append(h("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle" }, v.toFixed(dec(xt.step)))));
  if (xLabel) tk.append(h("text", { x: (m.l + W - m.r) / 2, y: H - 4, "text-anchor": "middle" }, xLabel));
  if (yLabel) tk.append(h("text", { x: m.l - 8, y: m.t - 10, "text-anchor": "end" }, yLabel));
  svg.append(grid, ax, tk);
}

function tooltip(container) {
  const tt = h("div", { class: "tooltip", role: "status" });
  container.append(tt);
  return {
    show(x, y, head, rows) {
      clear(tt).append(h("div", { class: "tt-head" }, head),
        rows.map((r) => h("div", { class: "tt-row" }, h("span", { class: "tt-key", style: { background: r.color } }), h("b", {}, r.value), h("span", { class: "n" }, r.label))));
      tt.style.display = "block";
      const cw = container.clientWidth;
      const left = x + 14 + tt.offsetWidth > cw ? x - 14 - tt.offsetWidth : x + 14;
      tt.style.left = `${Math.max(0, left)}px`; tt.style.top = `${Math.max(0, y - 10)}px`;
    },
    hide() { tt.style.display = "none"; },
  };
}

export function legend(sides = ["L", "R"], band = false) {
  return h("div", { class: "legend" }, sides.map((s) => h("span", { class: "key" },
    h("span", { class: "swatch-line", style: { background: SIDES[s].color } }), SIDES[s].label)),
  band ? h("span", { class: "key muted" }, h("span", { class: "swatch-band", style: { background: "var(--ink-2)" } }), "± 1 SD") : null);
}

// Mean ± SD over the gait cycle (0–100 %), one line per side.
export function cycleChart(container, { title, sides, unit = "°", height = 210 }) {
  const box = h("div", { class: "chart" });
  container.append(h("div", { class: "chart-title" }, h("span", {}, title),
    h("span", { class: "muted small" }, Object.entries(sides).map(([s, d]) => `${s} n=${d.n}`).join(" · "))), box);
  const keys = Object.keys(sides);
  let lo = Infinity, hi = -Infinity;
  for (const s of keys) sides[s].mean.forEach((v, i) => { if (v == null) return; lo = Math.min(lo, v - sides[s].sd[i]); hi = Math.max(hi, v + sides[s].sd[i]); });
  const pad = (hi - lo) * 0.06 || 1;
  const yt = ticks(lo - pad, hi + pad, 4), xt = { list: [0, 20, 40, 60, 80, 100], step: 20 };
  const tt = tooltip(box);
  return responsive(box, (W) => {
    const H = height, m = { l: 38, r: 10, t: 22, b: 34 };
    const x = (v) => m.l + (v / 100) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - yt.list[0]) / (yt.list.at(-1) - yt.list[0])) * (H - m.t - m.b);
    const svg = h("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${title}, ${unit === "°" ? "degrees" : unit} over the gait cycle` });
    frame(svg, { W, H, m, x, y, xt, yt, xLabel: "% gait cycle", yLabel: unit });
    for (const s of keys) {
      const { mean, sd } = sides[s];
      const N = mean.length, xi = (i) => x((100 * i) / (N - 1));
      const up = mean.map((v, i) => `${xi(i)},${y(v + sd[i])}`), dn = mean.map((v, i) => `${xi(i)},${y(v - sd[i])}`).reverse();
      svg.append(h("polygon", { points: [...up, ...dn].join(" "), fill: SIDES[s].color, opacity: 0.14 }));
    }
    for (const s of keys) {
      const { mean } = sides[s];
      const N = mean.length;
      svg.append(h("polyline", { points: mean.map((v, i) => `${x((100 * i) / (N - 1))},${y(v)}`).join(" "), fill: "none",
        stroke: SIDES[s].color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    }
    const hair = h("line", { class: "hair", y1: m.t, y2: H - m.b, visibility: "hidden" });
    const dots = keys.map((s) => h("circle", { r: 4, fill: SIDES[s].color, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }));
    const hitArea = h("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    svg.append(hair, ...dots, hitArea);
    const move = (e) => {
      const r = svg.getBoundingClientRect();
      const px = Math.min(Math.max(e.clientX - r.left, m.l), W - m.r);
      const pct = ((px - m.l) / (W - m.l - m.r)) * 100;
      const rows = [];
      keys.forEach((s, k) => {
        const { mean, sd } = sides[s];
        const i = Math.round((pct / 100) * (mean.length - 1));
        const xx = x((100 * i) / (mean.length - 1));
        hair.setAttribute("x1", xx); hair.setAttribute("x2", xx); hair.setAttribute("visibility", "visible");
        dots[k].setAttribute("cx", xx); dots[k].setAttribute("cy", y(mean[i])); dots[k].setAttribute("visibility", "visible");
        rows.push({ color: SIDES[s].color, value: `${mean[i].toFixed(1)}${unit} ± ${sd[i].toFixed(1)}`, label: SIDES[s].label });
      });
      tt.show(px, e.clientY - r.top, `${Math.round(pct)} % of gait cycle`, rows);
    };
    hitArea.addEventListener("pointermove", move);
    hitArea.addEventListener("pointerleave", () => { tt.hide(); hair.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); });
    const ttEl = box.querySelector(".tooltip");
    clear(box).append(svg, ttEl);
  });
}

// Stride-by-stride values over time, dots + thin connecting line per side.
export function strideChart(container, { rows, key, label, unit, digits = 2, height = 240 }) {
  const box = h("div", { class: "chart" });
  container.append(box);
  const pts = rows.filter((r) => r[key] != null && r.t_hs != null).map((r, i) => ({ ...r, _i: i }));
  if (!pts.length) { box.append(h("div", { class: "muted small", style: { padding: "30px 0" } }, "No values for this parameter.")); return () => {}; }
  const vals = pts.map((p) => p[key]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.05 || 1;
  const yt = ticks(lo - pad, hi + pad, 4);
  const t0 = Math.min(...pts.map((p) => p.t_hs)), t1 = Math.max(...pts.map((p) => p.t_hs));
  const xt = ticks(t0, t1 || 1, 6);
  const tt = tooltip(box);
  const counters = { L: 0, R: 0 };
  pts.sort((a, b) => a.t_hs - b.t_hs).forEach((p) => { p._n = ++counters[p.side]; });
  return responsive(box, (W) => {
    const H = height, m = { l: 46, r: 12, t: 22, b: 34 };
    const xlo = Math.min(xt.list[0], t0), xhi = Math.max(xt.list.at(-1), t1);
    const x = (v) => m.l + ((v - xlo) / (xhi - xlo || 1)) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - yt.list[0]) / (yt.list.at(-1) - yt.list[0])) * (H - m.t - m.b);
    const svg = h("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${label} per stride over time` });
    frame(svg, { W, H, m, x, y, xt: { list: xt.list.filter((v) => v >= xlo && v <= xhi), step: xt.step }, yt, xLabel: "time (s)", yLabel: unit });
    const dotsBySide = {};
    for (const s of ["L", "R"]) {
      const ps = pts.filter((p) => p.side === s);
      if (!ps.length) continue;
      svg.append(h("polyline", { points: ps.map((p) => `${x(p.t_hs)},${y(p[key])}`).join(" "), fill: "none", stroke: SIDES[s].color,
        "stroke-width": 1.5, opacity: 0.55, "stroke-linejoin": "round" }));
      dotsBySide[s] = ps.map((p) => {
        const c = h("circle", { cx: x(p.t_hs), cy: y(p[key]), r: 4.5, fill: SIDES[s].color, stroke: "var(--surface)", "stroke-width": 2 });
        svg.append(c);
        return { p, c };
      });
    }
    const all = Object.values(dotsBySide).flat();
    const hitArea = h("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    svg.append(hitArea);
    let last = null;
    hitArea.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      let best = null, bd = Infinity;
      for (const d of all) { const dd = Math.hypot(x(d.p.t_hs) - px, y(d.p[key]) - py); if (dd < bd) { bd = dd; best = d; } }
      if (last && last !== best) last.c.setAttribute("r", 4.5);
      if (!best || bd > 40) { tt.hide(); last = null; return; }
      best.c.setAttribute("r", 6.5); last = best;
      tt.show(x(best.p.t_hs), y(best.p[key]), `${SIDES[best.p.side].label} stride ${best.p._n} · t = ${best.p.t_hs.toFixed(2)} s`,
        [{ color: SIDES[best.p.side].color, value: `${best.p[key].toFixed(digits)} ${unit}`, label }]);
    });
    hitArea.addEventListener("pointerleave", () => { tt.hide(); if (last) last.c.setAttribute("r", 4.5); last = null; });
    const ttEl = box.querySelector(".tooltip");
    clear(box).append(svg, ttEl);
  });
}
