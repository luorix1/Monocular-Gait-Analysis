import { api } from "../api.js";
import { h, clear, icon, fmt, card, crumbs, seg, jobBadge, progressBar } from "../ui.js";
import { cycleChart, strideChart, legend, SIDES } from "../charts.js";
import { runDialog } from "./subject.js";

const PARAMS = [
  ["stride_time", "Stride time", "s", 3], ["stride_frequency", "Stride frequency", "Hz", 3],
  ["stride_length", "Stride length", "m", 3], ["step_time", "Step time", "s", 3], ["step_length", "Step length", "m", 3],
  ["step_width", "Step width", "m", 3], ["stance_time", "Stance time", "s", 3], ["swing_time", "Swing time", "s", 3],
  ["stance_pct", "Stance", "% cycle", 1], ["double_support_pct", "Double support", "% cycle", 1],
];

export async function render(view, [sid, tid], ctx) {
  const base = `/api/subjects/${api.enc(sid)}/trials/${api.enc(tid)}`;
  const cleanups = [];
  const subjHref = `#/s/${encodeURIComponent(sid)}`;
  let r;
  try { r = await api.get(`${base}/results`); } catch (e) {
    view.append(crumbs({ label: "Subjects", href: "#/" }, { label: sid, href: subjHref }, { label: tid }),
      h("div", { class: "card", style: { marginTop: "12px" } }, h("div", { class: "empty" }, h("h2", {}, "No results yet"),
        h("p", { class: "muted" }, e.message), h("a", { class: "btn", href: subjHref }, "Back to subject"))));
    return;
  }
  const s = r.summary, run = r.run || {}, cfg = run.settings || {};
  const reprocess = async () => runDialog(await api.get(`/api/subjects/${api.enc(sid)}`), [tid]);

  // ----------------------------------------------------------------- header
  const shown = run.displayed_speed_m_s;
  const bits = [h("span", {}, `Processed ${fmt.date(r.processed_at)}`),
    h("span", {}, `${s.n_strides?.L ?? 0} left + ${s.n_strides?.R ?? 0} right strides`)];
  if (cfg.pose2d) bits.push(h("span", { class: "muted" }, `${cfg.pose2d.device?.toUpperCase()} · pose ${cfg.pose2d.mode} · events ${cfg.events?.method}`));
  view.append(crumbs({ label: "Subjects", href: "#/" }, { label: sid, href: subjHref }, { label: tid }),
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, tid), h("div", { class: "sub" }, bits)),
      h("div", { class: "actions" },
        r.job ? h("a", { class: "btn", href: `#/jobs/${r.job.id}` }, icon("file", 15), "Log") : null,
        h("button", { class: "btn", onclick: reprocess }, icon("refresh", 15), "Re-process"))));

  const banner = h("div");
  view.append(banner);
  const paintBanner = (j) => {
    clear(banner);
    if (!j) return;
    if (["queued", "running"].includes(j.status)) {
      banner.append(h("div", { class: "banner run", style: { marginBottom: "18px" } }, icon("loader", 16, "spin"),
        h("div", { class: "grow" }, h("div", { class: "row" }, h("b", {}, "Re-processing"), jobBadge(j), j.stage ? h("span", { class: "small ink2" }, j.stage) : null),
          progressBar(j), h("span", { class: "small ink2" }, "The results below are from the previous run and refresh when it finishes.")),
        h("a", { class: "btn sm", href: `#/jobs/${j.id}` }, "Open log")));
    } else if (j.status === "failed" && j.finished > r.processed_at) {
      banner.append(h("div", { class: "banner bad", style: { marginBottom: "18px" } }, icon("alert", 16),
        h("div", { class: "grow" }, h("b", {}, "The latest run failed"), h("span", { class: "small" }, j.error || ""),
          h("span", { class: "small ink2" }, "Showing results from the previous successful run.")),
        h("a", { class: "btn sm", href: `#/jobs/${j.id}` }, "Open log")));
    }
  };
  paintBanner(r.job);
  let lastStatus = r.job?.status;
  ctx.onJobs((jobs) => {
    const j = jobs.find((x) => x.kind === "pipeline" && x.meta?.subject === sid && x.meta?.trial === tid);
    if (!j) return;
    if (lastStatus && ["queued", "running"].includes(lastStatus) && j.status === "done") { window.dispatchEvent(new HashChangeEvent("hashchange")); return; }
    lastStatus = j.status;
    paintBanner(j);
  });

  // ------------------------------------------------------------------ tiles
  const g = (k) => s[k] || {};
  const diff = shown ? (100 * (s.belt_speed_m_s - shown)) / shown : null;
  const tile = (label, value, unit, sub) => h("div", { class: "card tile" }, h("div", { class: "tile-label" }, label),
    h("div", { class: "tile-value tabnum" }, value, unit ? h("span", { class: "unit" }, unit) : null), sub ? h("div", { class: "tile-sub" }, sub) : null);
  const sd = (k, d) => (g(k).sd != null ? `± ${fmt.n(g(k).sd, d)} SD` : "");
  view.append(h("div", { class: "tiles" },
    tile("Belt speed (estimated)", fmt.n(s.belt_speed_m_s, 2), "m/s",
      shown ? `Treadmill ${fmt.n(shown, 2)} · ${diff >= 0 ? "+" : ""}${diff.toFixed(1)} %` : `source: ${s.belt_speed_estimates?.source ?? "–"}`),
    tile("Cadence", fmt.n(s.cadence_steps_per_min, 1), "steps/min", `${fmt.n(g("stride_frequency").mean, 3)} strides/s`),
    tile("Stride length", fmt.n(g("stride_length").mean, 2), "m", sd("stride_length", 3)),
    tile("Stride time", fmt.n(g("stride_time").mean, 3), "s", sd("stride_time", 3)),
    tile("Step width", fmt.n(g("step_width").mean, 3), "m", sd("step_width", 3)),
    tile("Stance", fmt.n(g("stance_pct").mean, 1), "%", `Double support ${fmt.n(g("double_support_pct").mean, 1)} %`)));

  // ------------------------------------------------------------ param table
  const rows = PARAMS.filter(([k]) => s[k]).map(([k, label, unit, d]) => {
    const p = s[k];
    return h("tr", {}, h("td", {}, h("span", { class: "cell-main" }, label), h("span", { class: "cell-sub" }, `  ${unit}`)),
      h("td", { class: "num" }, `${fmt.n(p.mean, d)} ± ${fmt.n(p.sd, d)}`),
      h("td", { class: "num" }, fmt.n(p.L, d)), h("td", { class: "num" }, fmt.n(p.R, d)),
      h("td", { class: "num" }, p.symmetry_index_pct != null ? `${fmt.n(p.symmetry_index_pct, 1)} %` : "–"),
      h("td", { class: "num" }, p.cv_pct != null ? `${fmt.n(p.cv_pct, 1)} %` : "–"));
  });
  view.append(h("div", { class: "section-title" }, h("h2", {}, "Spatiotemporal parameters"),
    h("span", { class: "hint" }, "Spatial values are over-ground equivalents (belt coordinates).")),
  card(null, null, null, h("div", { class: "table-wrap" }, h("table", { class: "t" },
    h("thead", {}, h("tr", {}, h("th", {}, "Parameter"), h("th", { class: "num" }, "Mean ± SD"),
      h("th", { class: "num" }, h("span", { class: "dot", style: { background: SIDES.L.color, marginRight: "6px" } }), "Left"),
      h("th", { class: "num" }, h("span", { class: "dot", style: { background: SIDES.R.color, marginRight: "6px" } }), "Right"),
      h("th", { class: "num", title: "200·|L−R|/(L+R)" }, "Symmetry index"), h("th", { class: "num", title: "SD / mean" }, "CV"))),
    h("tbody", {}, rows)))));

  // ----------------------------------------------------------- joint angles
  view.append(h("div", { class: "section-title" }, h("h2", {}, "Joint angles over the gait cycle"),
    h("span", { class: "hint" }, "OpenSim inverse kinematics, heel strike to heel strike")));
  if (r.joint_angles?.length) {
    const grid = h("div", { class: "grid-3" });
    const ja = card(null, null, null, h("div", { class: "card-body", style: { display: "grid", gap: "14px" } }, legend(["L", "R"], true), grid));
    view.append(ja);
    for (const j of r.joint_angles) {
      const cell = h("div");
      grid.append(cell);
      cleanups.push(cycleChart(cell, { title: j.title, sides: j.sides }));
    }
  } else {
    view.append(h("div", { class: "banner" }, icon("info", 16), h("div", { class: "grow" },
      "No joint angles for this trial: OpenSim was turned off or is not installed (see System). Gait parameters above come from the 3D keypoints.")));
  }

  // ---------------------------------------------------------- stride chart
  const avail = PARAMS.filter(([k]) => r.strides.some((x) => x[k] != null));
  if (avail.length) {
    const chartBox = h("div");
    let current = avail.some(([k]) => k === "stride_length") ? "stride_length" : avail[0][0];
    let stop = null;
    const draw = () => {
      stop?.();
      clear(chartBox);
      const [k, label, unit, d] = PARAMS.find(([x]) => x === current);
      stop = strideChart(chartBox, { rows: r.strides, key: k, label, unit, digits: d });
    };
    const picker = h("select", { style: { width: "auto" }, onchange: (e) => { current = e.target.value; draw(); } },
      avail.map(([k, label]) => h("option", { value: k }, label)));
    picker.value = current;
    view.append(h("div", { class: "section-title" }, h("h2", {}, "Stride by stride"), h("span", { class: "hint" }, "consistency over the trial")),
      card(null, null, null, h("div", { class: "card-body", style: { display: "grid", gap: "12px" } },
        h("div", { class: "row" }, picker, h("span", { class: "spacer" }), legend()), chartBox,
        h("details", { class: "adv" }, h("summary", {}, icon("chevron", 14), `Show all ${r.strides.length} strides as a table`), strideTable(r.strides)))));
    draw();
    cleanups.push(() => stop?.());
  }

  // ----------------------------------------------------------- video review
  if (r.video && r.video_file) {
    view.append(h("div", { class: "section-title" }, h("h2", {}, "Video review"), h("span", { class: "hint" }, "2D keypoints and detected gait events. ← → step one frame, Shift for 10.")),
      card(null, null, null, h("div", { class: "card-body" }, viewer(base, r, cleanups))));
  }

  // -------------------------------------------------------- belt + quality
  const est = s.belt_speed_estimates || {};
  const estRows = [["Treadmill display", shown, "entered when processing"],
    ["2D stance foot", est["2d"], "foot on the belt plane, 2D only"], ["Refinement", est.refined, "treadmill-constrained optimisation"],
    ...Object.entries(est).filter(([k]) => k.startsWith("3d")).map(([k, v]) => [`3D (${k.slice(3)})`, v, "heel speed in stance"]),
    ["Used", est.used, `source: ${est.source}`]];
  view.append(h("div", { class: "grid-2", style: { marginTop: "30px" } },
    card("Belt speed estimates", "m/s", null, h("div", { class: "table-wrap" }, h("table", { class: "t" }, h("tbody", {},
      estRows.map(([l, v, sub]) => h("tr", {}, h("td", {}, h("div", { class: "cell-main" }, l), h("div", { class: "cell-sub" }, sub)),
        h("td", { class: "num" }, v != null ? fmt.n(v, 3) : "–"),
        h("td", { class: "num cell-sub" }, v != null && shown && l !== "Treadmill display" ? `${(100 * (v - shown) / shown >= 0 ? "+" : "")}${(100 * (v - shown) / shown).toFixed(1)} %` : ""))))))),
    card("Reconstruction quality", null, null, h("div", { class: "card-body" }, h("dl", { class: "kv" },
      h("dt", {}, "Reprojection RMSE"), h("dd", {}, r.refine?.reproj_rmse_px != null ? `${fmt.n(r.refine.reproj_rmse_px, 2)} px` : "–"),
      h("dt", {}, "2D belt-speed IQR"), h("dd", {}, r.analysis_2d?.iqr ? `${fmt.n(r.analysis_2d.iqr[0], 3)} – ${fmt.n(r.analysis_2d.iqr[1], 3)} m/s` : "–"),
      h("dt", {}, "Leg length (refined)"), h("dd", {}, legLength(r.refine)),
      h("dt", {}, "Strides used"), h("dd", {}, `${s.n_strides?.L ?? 0} L · ${s.n_strides?.R ?? 0} R`),
      h("dt", {}, "Video"), h("dd", {}, r.video ? `${r.video.n_frames} frames @ ${fmt.n(r.video.fps, 1)} fps` : "–"))))));

  // --------------------------------------------------------- plots + files
  const plots = r.files.filter((f) => f.startsWith("plots/") && f.endsWith(".png"));
  if (plots.length) {
    view.append(h("div", { class: "section-title" }, h("h2", {}, "Pipeline plots"), h("span", { class: "hint" }, "as written by the pipeline (click to enlarge)")),
      h("div", { class: "stack" }, plots.map((p) => h("a", { href: `${base}/files/${p}`, target: "_blank" },
        h("img", { class: "figure", src: `${base}/files/${p}?t=${r.processed_at}`, alt: p, loading: "lazy" })))));
  }
  const KEY_FILES = { "summary.json": "Summary (means, SD, L/R)", "strides.csv": "Per-stride table", "events.json": "Gait events",
    "opensim/ik.mot": "Joint angles (OpenSim)", "opensim/scaled.osim": "Scaled OpenSim model", "kp3d_refined.npz": "3D keypoints" };
  const files = [...r.files].sort((a, b) => (KEY_FILES[b] ? 1 : 0) - (KEY_FILES[a] ? 1 : 0));
  view.append(h("div", { class: "section-title" }, h("h2", {}, "Files"), h("span", { class: "hint" }, "in data/", sid, "/results/", tid)),
    h("div", { class: "files" }, files.map((f) => h("a", { href: `${base}/files/${f}?download=1`, download: f.split("/").pop() }, icon("download", 14),
      h("span", { style: { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, KEY_FILES[f] ? h("b", {}, KEY_FILES[f]) : null,
        KEY_FILES[f] ? h("span", { class: "muted small" }, ` ${f}`) : f)))));

  return () => cleanups.forEach((c) => c?.());
}

function legLength(ref) {
  const b = ref?.bone_lengths;
  if (!b) return "–";
  const L = (b["LHip-LKnee"] ?? 0) + (b["LKnee-LAnkle"] ?? 0);
  return L ? `${fmt.n(L, 3)} m (thigh + shank)` : "–";
}

function strideTable(strides) {
  const cols = ["side", "t_hs", ...PARAMS.map(([k]) => k).filter((k) => strides.some((s) => s[k] != null))];
  const label = (k) => (k === "side" ? "Side" : k === "t_hs" ? "Time (s)" : PARAMS.find(([x]) => x === k)[1]);
  return h("div", { class: "table-wrap", style: { marginTop: "10px", maxHeight: "380px", overflowY: "auto" } },
    h("table", { class: "t" }, h("thead", {}, h("tr", {}, cols.map((k) => h("th", { class: k === "side" ? "" : "num" }, label(k))))),
      h("tbody", {}, [...strides].sort((a, b) => a.t_hs - b.t_hs).map((s) => h("tr", {}, cols.map((k) =>
        k === "side" ? h("td", {}, h("span", { class: "dot", style: { background: SIDES[s.side].color, marginRight: "6px" } }), SIDES[s.side].label)
          : h("td", { class: "num" }, fmt.n(s[k], k.endsWith("pct") ? 1 : 3))))))));
}

// --------------------------------------------------------------- viewer
function viewer(base, r, cleanups) {
  const n = r.video.n_frames, fps = r.video.fps;
  let idx = Math.min(n - 1, Math.round((r.events?.hs?.L?.[1] ?? 0))), playing = false, loading = false, pending = null;
  const img = h("img", { alt: "Video frame with 2D keypoints" });
  const slider = h("input", { type: "range", min: 0, max: n - 1, value: idx, "aria-label": "Frame" });
  const time = h("span", { class: "small tabnum ink2 nowrap", style: { minWidth: "150px", textAlign: "right" } });
  const playBtn = h("button", { class: "btn icon", "aria-label": "Play" }, icon("play", 15));
  const head = h("div", { class: "head" });
  const tl = h("div", { class: "timeline", title: "Click to jump. Solid = heel strike, faded = toe off" },
    h("div", { class: "lane l" }, h("span", { class: "lane-label" }, "L")), h("div", { class: "lane r" }, h("span", { class: "lane-label" }, "R")), head);
  for (const side of ["L", "R"]) {
    const lane = tl.querySelector(`.lane.${side.toLowerCase()}`);
    for (const kind of ["hs", "to"]) for (const f of r.events?.[kind]?.[side] || []) {
      lane.append(h("div", { class: `ev ${kind}`, style: { left: `${(100 * f) / n}%`, background: SIDES[side].color } }));
    }
  }
  const frameBox = h("div", { class: "viewer-frame", tabindex: 0 }, img);

  const show = (i) => {
    idx = Math.max(0, Math.min(n - 1, i));
    slider.value = idx;
    head.style.left = `${(100 * idx) / n}%`;
    time.textContent = `${(idx / fps).toFixed(2)} s · frame ${idx}`;
    if (loading) { pending = idx; return; }
    loading = true;
    img.src = `${base}/frame?idx=${idx}&max_w=960`;
  };
  img.onload = img.onerror = () => {
    loading = false;
    if (pending !== null) { const p = pending; pending = null; show(p); return; }
    if (playing) setTimeout(() => { if (playing) show(idx + Math.max(1, Math.round(fps / 12))); }, 0);
  };
  const setPlay = (p) => { playing = p; clear(playBtn).append(icon(p ? "pause" : "play", 15)); playBtn.setAttribute("aria-label", p ? "Pause" : "Play"); if (p && !loading) show(idx + 1); };
  playBtn.onclick = () => setPlay(!playing);
  slider.oninput = () => show(+slider.value);
  tl.addEventListener("click", (e) => { const b = tl.getBoundingClientRect(); show(Math.round(((e.clientX - b.left) / b.width) * n)); });
  frameBox.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); show(idx + (e.shiftKey ? 10 : 1)); }
    if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - (e.shiftKey ? 10 : 1)); }
    if (e.key === " ") { e.preventDefault(); setPlay(!playing); }
  });
  cleanups.push(() => { playing = false; });
  show(idx);
  return h("div", { class: "viewer" }, frameBox,
    h("div", { class: "viewer-controls" }, playBtn,
      h("button", { class: "btn icon", "aria-label": "Previous frame", onclick: () => show(idx - 1) }, icon("left", 15)),
      h("button", { class: "btn icon", "aria-label": "Next frame", onclick: () => show(idx + 1) }, icon("chevron", 15)),
      slider, time),
    tl,
    h("div", { class: "legend small" }, h("span", { class: "key" }, h("span", { class: "swatch-line", style: { background: SIDES.L.color } }), "Left side / events"),
      h("span", { class: "key" }, h("span", { class: "swatch-line", style: { background: SIDES.R.color } }), "Right side / events"),
      h("span", { class: "muted" }, "Playback skips frames to keep up; use the arrow keys for every frame.")));
}
