// Belt calibration: click the 4 belt corners (+ optional known points) on a video frame, solve, save.
import { api } from "../api.js";
import { h, clear, icon, fmt, select, card, crumbs, rmsBadge, toast, numInput, field } from "../ui.js";

const CORNERS = [
  ["belt_front_left", "Front left", "Subject's left, at the end they face"],
  ["belt_front_right", "Front right", "Subject's right, at the end they face"],
  ["belt_back_right", "Back right", "Subject's right, behind them"],
  ["belt_back_left", "Back left", "Subject's left, behind them"],
];
const COL = { active: "#ffd23f", placed: "#3fe07a", line: "rgba(255, 210, 63, 0.9)", bad: "#ff5a5a" };

export async function render(view, [sid]) {
  const [s, intrinsics, defaults] = await Promise.all([api.get(`/api/subjects/${api.enc(sid)}`), api.get("/api/intrinsics"),
    api.get("/api/config/default")]);
  const cal = s.calibration;
  const videos = s.videos.filter((v) => !v.info?.error);
  if (!videos.length) {
    view.append(crumbs({ label: "Subjects", href: "#/" }, { label: sid, href: `#/s/${encodeURIComponent(sid)}` }, { label: "Calibrate" }),
      h("div", { class: "card", style: { marginTop: "12px" } }, h("div", { class: "empty" }, h("h2", {}, "No videos"),
        h("p", { class: "muted" }, "Add a trial video to this subject first."), h("a", { class: "btn", href: `#/s/${encodeURIComponent(sid)}` }, "Back"))));
    return;
  }

  // ---------------------------------------------------------------- state
  const st = {
    video: (cal && videos.some((v) => v.name === cal.video) ? cal.video : (videos.find((v) => v.role === "trial") || videos[0]).name),
    frame: cal?.frame || 0,
    points: {},           // name -> [x, y] image px
    extras: [],           // {name, world: [x,y,z]}
    active: CORNERS[0][0],
    img: null, scale: 1, cursor: null, drag: null, result: null, showPreview: false,
  };
  if (cal) {
    for (const lm of cal.landmarks) {
      st.points[lm.name] = lm.pixel;
      if (!CORNERS.some(([n]) => n === lm.name)) st.extras.push({ name: lm.name, world: lm.world });
    }
    st.active = null;
  }
  const order = () => [...CORNERS.map(([n]) => n), ...st.extras.map((e) => e.name)];
  const nextUnplaced = () => order().find((n) => !st.points[n]) || null;

  // -------------------------------------------------------------- toolbar
  const vInfo = () => videos.find((v) => v.name === st.video).info;
  const videoSel = select(videos.map((v) => [v.name, `${v.name}${v.role === "checkerboard" ? " (checkerboard)" : ""}`]), st.video,
    { style: { width: "auto", maxWidth: "260px" }, onchange: () => { st.video = videoSel.value; st.frame = 0; slider.max = vInfo().n_frames - 1; slider.value = 0; frameNum.value = 0; loadFrame(); } });
  const slider = h("input", { type: "range", min: 0, max: Math.max(0, vInfo().n_frames - 1), value: st.frame, "aria-label": "Frame" });
  const frameNum = h("input", { type: "number", min: 0, value: st.frame, style: { width: "90px" }, "aria-label": "Frame number" });
  let t;
  slider.oninput = () => { frameNum.value = slider.value; clearTimeout(t); t = setTimeout(() => { st.frame = +slider.value; loadFrame(); }, 120); };
  frameNum.onchange = () => { slider.value = frameNum.value; st.frame = +slider.value; loadFrame(); };
  const spinner = h("span", { class: "muted hidden" }, icon("loader", 16, "spin"));
  const previewToggle = h("button", { class: "btn sm", onclick: () => { st.showPreview = !st.showPreview; previewToggle.classList.toggle("primary", st.showPreview); loadFrame(); } },
    icon("grid", 14), "Show result overlay");
  previewToggle.disabled = !cal?.has_preview;

  // --------------------------------------------------------------- canvas
  const canvas = h("canvas", { tabindex: 0, "aria-label": "Video frame. Click to place the highlighted landmark; drag points to adjust; arrow keys nudge." });
  const loupeCanvas = h("canvas", { width: 360, height: 360 });
  const loupe = h("div", { class: "loupe" }, loupeCanvas);
  const stage = h("div", { class: "stage-wrap placing" }, canvas, loupe);
  const hint = h("div", { class: "small ink2", style: { minHeight: "21px" } });

  async function loadFrame() {
    spinner.classList.remove("hidden");
    const url = st.showPreview ? `/api/subjects/${api.enc(sid)}/calibration.png?t=${Date.now()}`
      : `/api/subjects/${api.enc(sid)}/videos/${api.enc(st.video)}/frame?idx=${st.frame}`;
    const img = new Image();
    img.onload = () => { st.img = img; spinner.classList.add("hidden"); layout(); };
    img.onerror = () => { spinner.classList.add("hidden"); toast("Could not read that frame", "", "bad"); };
    img.src = url;
  }

  function layout() {
    if (!st.img) return;
    const maxW = stage.clientWidth || 800;
    const maxH = Math.max(360, window.innerHeight - 230);
    st.scale = Math.min(maxW / st.img.naturalWidth, maxH / st.img.naturalHeight);
    const w = Math.round(st.img.naturalWidth * st.scale), hh = Math.round(st.img.naturalHeight * st.scale);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr; canvas.height = hh * dpr;
    canvas.style.width = `${w}px`; canvas.style.height = `${hh}px`;
    draw();
  }

  function draw() {
    if (!st.img) return;
    const g = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.drawImage(st.img, 0, 0, st.img.naturalWidth * st.scale, st.img.naturalHeight * st.scale);
    if (st.showPreview) return;
    const P = (n) => st.points[n] && [st.points[n][0] * st.scale, st.points[n][1] * st.scale];
    // belt outline
    const quad = CORNERS.map(([n]) => P(n));
    const crossed = quad.every(Boolean) && isCrossed(quad);
    if (quad.filter(Boolean).length >= 2) {
      g.strokeStyle = crossed ? COL.bad : COL.line; g.lineWidth = 2; g.setLineDash([6, 4]);
      g.beginPath();
      quad.forEach((p, i) => { if (!p) return; const q = quad[(i + 1) % 4]; if (q && (i < 3 || quad.every(Boolean))) { g.moveTo(...p); g.lineTo(...q); } });
      g.stroke(); g.setLineDash([]);
    }
    order().forEach((n, i) => {
      const p = P(n); if (!p) return;
      const active = n === st.active;
      g.lineWidth = 2; g.strokeStyle = "rgba(0,0,0,0.7)";
      cross(g, p, 11, 4); g.strokeStyle = active ? COL.active : COL.placed; cross(g, p, 10, 2);
      g.font = "600 12px system-ui, sans-serif";
      const label = `${i + 1}`;
      g.fillStyle = "rgba(0,0,0,0.65)"; g.beginPath(); g.arc(p[0] + 15, p[1] - 15, 9, 0, 7); g.fill();
      g.fillStyle = active ? COL.active : "#fff"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(label, p[0] + 15, p[1] - 14.5);
    });
    hint.textContent = crossed ? "⚠ The belt outline crosses itself: two corners are probably swapped (check left/right)." : "";
    hint.style.color = crossed ? "var(--bad-ink)" : "";
    drawLoupe();
  }

  function drawLoupe() {
    if (!st.cursor || !st.img || st.showPreview) { loupe.style.display = "none"; return; }
    const [ix, iy] = st.cursor; // image px
    const z = 4, R = 180; // loupe shows R/z image px square... at 360 canvas px
    const g = loupeCanvas.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.fillStyle = "#000"; g.fillRect(0, 0, 360, 360);
    const half = 360 / (2 * z);
    g.drawImage(st.img, ix - half, iy - half, 2 * half, 2 * half, 0, 0, 360, 360);
    for (const [n, p] of Object.entries(st.points)) {
      const x = (p[0] - ix + half) * z, y = (p[1] - iy + half) * z;
      if (x < 0 || y < 0 || x > 360 || y > 360) continue;
      g.strokeStyle = n === st.active ? COL.active : COL.placed; g.lineWidth = 2; cross(g, [x, y], 14, 2);
    }
    g.strokeStyle = "rgba(255,80,80,0.9)"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(180, 150); g.lineTo(180, 172); g.moveTo(180, 188); g.lineTo(180, 210);
    g.moveTo(150, 180); g.lineTo(172, 180); g.moveTo(188, 180); g.lineTo(210, 180); g.stroke();
    // place the loupe away from the cursor
    const cx = ix * st.scale, cy = iy * st.scale;
    const left = cx > canvas.clientWidth / 2 ? 12 : canvas.clientWidth - R - 12;
    const off = (stage.clientWidth - canvas.clientWidth) / 2;
    loupe.style.left = `${off + left}px`;
    loupe.style.top = `${cy > canvas.clientHeight / 2 ? 12 : Math.max(12, canvas.clientHeight - R - 12)}px`;
    loupe.style.display = "block";
  }

  const toImg = (e) => { const r = canvas.getBoundingClientRect(); return [(e.clientX - r.left) / st.scale, (e.clientY - r.top) / st.scale]; };
  const hit = (p) => {
    let best = null, bd = 12 / st.scale;
    for (const [n, q] of Object.entries(st.points)) { const d = Math.hypot(q[0] - p[0], q[1] - p[1]); if (d < bd) { bd = d; best = n; } }
    return best;
  };
  canvas.addEventListener("pointerdown", (e) => {
    if (st.showPreview || !st.img) return;
    canvas.focus();
    const p = toImg(e);
    const n = hit(p);
    if (n) { st.drag = n; st.active = n; canvas.setPointerCapture(e.pointerId); renderPanel(); draw(); return; }
    if (!st.active) st.active = nextUnplaced();
    if (!st.active) { toast("All points are placed", "Drag a point to move it, or select one in the list to re-place it.", "info", null, 4000); return; }
    st.points[st.active] = p;
    st.active = nextUnplaced();
    st.result = null;
    renderPanel(); draw();
  });
  canvas.addEventListener("pointermove", (e) => {
    st.cursor = toImg(e);
    if (st.drag) { st.points[st.drag] = st.cursor; st.result = null; }
    draw();
  });
  canvas.addEventListener("pointerup", () => { if (st.drag) { st.drag = null; renderPanel(); } });
  canvas.addEventListener("pointerleave", () => { st.cursor = null; loupe.style.display = "none"; });
  canvas.addEventListener("keydown", (e) => {
    const n = st.active && st.points[st.active] ? st.active : null;
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (n && d) {
      e.preventDefault();
      const k = e.shiftKey ? 5 : 0.5;
      st.points[n] = [st.points[n][0] + d[0] * k, st.points[n][1] + d[1] * k];
      st.cursor = st.points[n]; st.result = null; draw(); renderPanel();
    }
  });
  const ro = new ResizeObserver(() => layout());
  ro.observe(stage);

  // ---------------------------------------------------------------- panel
  const panel = h("div", { class: "stack" });
  const L = numInput(cal?.belt_length_m ?? defaults.treadmill?.belt_length_m, "m", { min: 0.2, max: 5, step: 0.01 });
  const W = numInput(cal?.belt_width_m ?? defaults.treadmill?.belt_width_m, "m", { min: 0.1, max: 2, step: 0.01 });
  const intrSel = select([["", "None (estimate from the belt)"], ...intrinsics.map((i) => [i.id, `${i.name} · ${i.image_size?.join("×")}`])],
    s.meta.intrinsics || "");
  const lmBox = h("div", { class: "lm-list" });
  const resultBox = h("div");
  const solveBtn = h("button", { class: "btn primary", onclick: solve }, icon("check", 15), "Solve & save");

  function renderPanel() {
    clear(lmBox);
    const items = [...CORNERS.map(([n, label, sub]) => ({ n, label, sub, corner: true })),
      ...st.extras.map((e) => ({ n: e.name, label: e.name, extra: e }))];
    items.forEach((it, i) => {
      const placed = !!st.points[it.n];
      const row = h("div", { class: `lm${placed ? " placed" : ""}${st.active === it.n ? " active" : ""}`,
        onclick: () => { st.active = it.n; renderPanel(); draw(); canvas.focus(); } },
      h("span", { class: "lm-num" }, placed ? icon("check", 12) : i + 1),
      h("div", {}, h("div", { class: "lm-name" }, it.label),
        h("div", { class: "lm-sub" }, it.corner ? it.sub : `X ${it.extra.world.join(", ")} m`,
          placed ? ` · (${Math.round(st.points[it.n][0])}, ${Math.round(st.points[it.n][1])}) px` : "")),
      h("div", { class: "row", style: { gap: "2px" } },
        placed ? h("button", { class: "btn ghost sm icon", title: "Re-place this point", "aria-label": `Clear ${it.label}`,
          onclick: (e) => { e.stopPropagation(); delete st.points[it.n]; st.active = it.n; st.result = null; renderPanel(); draw(); } }, icon("refresh", 13)) : null,
        it.extra ? h("button", { class: "btn ghost sm icon", title: "Remove", "aria-label": `Remove ${it.label}`,
          onclick: (e) => { e.stopPropagation(); st.extras = st.extras.filter((x) => x !== it.extra); delete st.points[it.n]; if (st.active === it.n) st.active = nextUnplaced(); renderPanel(); draw(); } }, icon("trash", 13)) : null));
      lmBox.append(row);
    });
    const nCorners = CORNERS.filter(([n]) => st.points[n]).length;
    solveBtn.disabled = nCorners < 4;
    stage.classList.toggle("placing", !!st.active);
    clear(resultBox);
    if (st.result) resultBox.append(resultCard(st.result));
  }

  function addExtra() {
    const name = h("input", { type: "text", placeholder: "e.g. rail_front_left_top" });
    const xyz = [0, 1, 2].map((i) => h("input", { type: "number", step: "any", placeholder: "XYZ"[i] }));
    const box = h("div", { class: "card card-pad", style: { display: "grid", gap: "10px" } },
      h("div", { class: "small ink2" }, "A point whose position you measured with a tape, in the treadmill frame: X forward, Y up, Z to the subject's right (m), origin at the belt centre. Off-belt points (e.g. a handrail top) help most."),
      field("Name", name), h("div", { class: "lm-xyz", style: { gridColumn: "auto" } }, xyz),
      h("div", { class: "row" }, h("span", { class: "spacer" }), h("button", { class: "btn sm", onclick: () => box.remove() }, "Cancel"),
        h("button", { class: "btn sm primary", onclick: () => {
          const n = name.value.trim().replace(/\s+/g, "_");
          const w = xyz.map((x) => Number(x.value));
          if (!n || order().includes(n)) { name.classList.add("invalid"); return; }
          if (xyz.some((x) => x.value === "" || Number.isNaN(Number(x.value)))) { xyz.forEach((x) => x.classList.toggle("invalid", x.value === "")); return; }
          st.extras.push({ name: n, world: w }); st.active = n; box.remove(); renderPanel(); draw(); canvas.focus();
        } }, "Add point")));
    lmBox.after(box);
    name.focus();
  }

  async function solve() {
    solveBtn.disabled = true;
    try {
      const landmarks = order().filter((n) => st.points[n]).map((n) => ({ name: n, pixel: st.points[n],
        world: st.extras.find((e) => e.name === n)?.world }));
      const r = await api.post(`/api/subjects/${api.enc(sid)}/calibration`, {
        video: st.video, frame: st.frame, belt_length_m: Number(L.input.value), belt_width_m: Number(W.input.value),
        intrinsics: intrSel.value || null, landmarks });
      st.result = r;
      previewToggle.disabled = false;
      toast("Calibration saved", `Reprojection RMS ${fmt.n(r.rms_px, 2)} px`, r.rms_px <= 2.5 ? "good" : "warn");
      renderPanel();
      resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) {
      toast("Calibration failed", e.message, "bad", null, 10000);
    } finally { solveBtn.disabled = CORNERS.some(([n]) => !st.points[n]); }
  }

  function resultCard(r) {
    const errs = Object.entries(r.reprojection_error_px || {});
    return h("div", { class: "card card-pad", style: { display: "grid", gap: "12px" } },
      h("div", { class: "row" }, h("h3", {}, "Result"), h("span", { class: "spacer" }), rmsBadge(r.rms_px)),
      h("div", { class: "err-list" }, errs.map(([n, e]) => h("div", {}, h("span", { class: "ink2" }, n.replace(/^belt_/, "").replace(/_/g, " ")),
        h("span", { class: "tabnum", style: { color: e > 3 ? "var(--bad-ink)" : e > 1.5 ? "var(--warn-ink)" : "inherit" } }, `${fmt.n(e, 2)} px`)))),
      h("dl", { class: "kv" }, h("dt", {}, "Camera height"), h("dd", {}, `${fmt.n(r.camera_height_m, 2)} m`),
        h("dt", {}, "Focal length"), h("dd", {}, `${fmt.n(r.focal_px, 0)} px${r.focal_estimated ? " (estimated)" : ""}`)),
      r.warning ? h("div", { class: "banner warn small" }, icon("alert", 15), h("div", { class: "grow" }, r.warning)) : null,
      h("div", { class: "small muted" }, "Check the overlay: the orange grid should lie flat on the belt and the green posts are 1 m tall. Errors above 2–3 px usually mean a mis-click or wrong belt size."),
      h("div", { class: "row" }, h("button", { class: "btn sm", onclick: () => { if (!st.showPreview) previewToggle.click(); } }, icon("grid", 14), "Show overlay"),
        h("span", { class: "spacer" }), h("a", { class: "btn sm primary", href: `#/s/${encodeURIComponent(sid)}` }, "Done", icon("chevron", 13))));
  }

  // ---------------------------------------------------------------- page
  view.append(
    crumbs({ label: "Subjects", href: "#/" }, { label: sid, href: `#/s/${encodeURIComponent(sid)}` }, { label: "Belt calibration" }),
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Belt calibration"),
      h("div", { class: "sub" }, "Click the four corners of the belt surface in order. Drag to adjust, arrow keys nudge the selected point (Shift for bigger steps)."))),
    h("div", { class: "calib" },
      h("div", {}, h("div", { class: "stage-toolbar" }, icon("video", 16), videoSel, slider, frameNum, spinner, previewToggle), stage, hint),
      h("div", { class: "stack" },
        card("Belt size", "measured on the treadmill", null, h("div", { class: "card-body form-grid" },
          field("Length (front–back)", L.el), field("Width (left–right)", W.el),
          h("div", { class: "full" }, field("Camera intrinsics", intrSel)))),
        card("Points", null, [h("button", { class: "btn sm", onclick: addExtra }, icon("plus", 13), "Known point")],
          h("div", { class: "card-body", style: { display: "grid", gap: "12px" } }, schematic(), lmBox)),
        h("div", { class: "row" }, h("button", { class: "btn", onclick: () => { st.points = {}; st.active = CORNERS[0][0]; st.result = null; renderPanel(); draw(); } }, "Clear points"),
          h("span", { class: "spacer" }), solveBtn),
        resultBox)));
  renderPanel();
  loadFrame();
  const onResize = () => layout();
  window.addEventListener("resize", onResize);
  return () => { ro.disconnect(); window.removeEventListener("resize", onResize); };
}

function cross(g, [x, y], r, w) {
  g.lineWidth = w;
  g.beginPath(); g.moveTo(x - r, y); g.lineTo(x - 3, y); g.moveTo(x + 3, y); g.lineTo(x + r, y);
  g.moveTo(x, y - r); g.lineTo(x, y - 3); g.moveTo(x, y + 3); g.lineTo(x, y + r); g.stroke();
}

function segX(a, b, c, d) {
  const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  return o(a, b, c) !== o(a, b, d) && o(c, d, a) !== o(c, d, b);
}
function isCrossed(q) { return segX(q[0], q[1], q[2], q[3]) || segX(q[1], q[2], q[3], q[0]); }

// Top view of the treadmill with the click order.
function schematic() {
  const svg = h("svg", { viewBox: "0 0 300 170", class: "schematic", role: "img", "aria-label": "Top view: corner 1 front left, 2 front right, 3 back right, 4 back left; the subject faces the front." });
  const x0 = 100, x1 = 200, y0 = 36, y1 = 146;
  svg.append(
    h("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 6, fill: "var(--surface-3)", stroke: "var(--axis)" }),
    h("path", { d: "M150 116 L150 64 M142 74 L150 62 L158 74", stroke: "var(--ink-2)", "stroke-width": 2, fill: "none", "stroke-linecap": "round" }),
    h("text", { x: 150, y: 14, "text-anchor": "middle" }, "FRONT (subject faces)"),
    h("text", { x: 150, y: 166, "text-anchor": "middle" }, "BACK"),
    h("circle", { cx: 150, cy: 126, r: 7, fill: "var(--ink-2)" }));
  const pts = [[x0, y0, "1", "front left", "end"], [x1, y0, "2", "front right", "start"], [x1, y1, "3", "back right", "start"], [x0, y1, "4", "back left", "end"]];
  for (const [x, y, n, label, anchor] of pts) {
    svg.append(h("circle", { cx: x, cy: y, r: 9, fill: "var(--primary-bg)" }),
      h("text", { x, y: y + 3.5, "text-anchor": "middle", style: { fill: "var(--primary-ink)" } }, n),
      h("text", { x: anchor === "end" ? x - 14 : x + 14, y: y + 4, "text-anchor": anchor }, label));
  }
  return svg;
}
