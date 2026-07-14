/* n9-web frontend — vanilla JS, polling, no external dependencies. */
"use strict";

// ── API helpers ───────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch("/api" + path, opts);
  let data = null;
  try { data = await resp.json(); } catch (e) { /* empty body */ }
  if (!resp.ok) {
    const detail = data && data.detail ? data.detail : resp.statusText;
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(`${resp.status}: ${msg}`);
  }
  return data;
}

function toast(msg, kind = "") {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 8000 : 3500);
}

function confirmAction(description, fn) {
  const dlg = document.getElementById("confirm-dialog");
  document.getElementById("confirm-text").textContent = description;
  dlg.showModal();
  const ok = document.getElementById("confirm-ok");
  const cancel = document.getElementById("confirm-cancel");
  const cleanup = () => { ok.onclick = null; cancel.onclick = null; dlg.close(); };
  ok.onclick = () => { cleanup(); fn(); };
  cancel.onclick = cleanup;
}

/* Run an async action tied to a button: disable while in flight, toast errors. */
function bindBusy(btn, fn) {
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await fn(); }
    catch (e) { toast(e.message, "err"); }
    finally { btn.disabled = false; }
  });
}

// ── Global state ──────────────────────────────────────────────────────────────

let CONFIG = null;
let lastStatus = null;
let activeTab = "dashboard";
const tempHistory = {};   // board_id → [temps]

// ── Header status poll (always on) ───────────────────────────────────────────

async function pollHeader() {
  try {
    const s = await api("GET", "/status");
    lastStatus = s;
    const badge = document.getElementById("mode-badge");
    badge.textContent = s.mode.replace("_", " ");
    badge.className = "badge " + s.mode;

    const dots = document.getElementById("device-dots");
    const dev = s.devices;
    const dot = (name, d) =>
      `<span><i class="dot ${d.sim ? "sim" : d.connected ? "on" : ""}"></i>${name}${d.sim ? " (sim)" : ""}</span>`;
    dots.innerHTML =
      dot("Robot", dev.robot) + dot("Fluidic", dev.fluidic) + dot("Boards", dev.boards) +
      `<span><i class="dot ${s.echem && s.echem.state === "running" ? "on" : ""}"></i>Gamry</span>`;

    if (activeTab === "experiment") renderExperimentStatus(s.experiment);
  } catch (e) { /* server down — leave last state */ }
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

const tabPollers = { dashboard: pollDashboard, temperature: pollTemperature,
                     spectral: pollSpectral, pumps: pollPumps,
                     echem: pollEchem, experiment: pollExperiment };

document.querySelectorAll("#tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    activeTab = btn.dataset.tab;
    document.getElementById("tab-" + activeTab).classList.add("active");
    const poll = tabPollers[activeTab];
    if (poll) poll();
  });
});

setInterval(pollHeader, 2000);
setInterval(() => { const p = tabPollers[activeTab]; if (p) p(); }, 3000);

// ── Dashboard: to-scale platform map ─────────────────────────────

const STATE_FILL = {
  FRESH: "#66bb6a", EMPTY: "#eceff1", USED: "#ef9a9a", CLEAN: "#90caf9",
  EMPTY_CLEAN: "#e3f2fd", SAMPLE_LOADED: "#ffe082", DYE_FILLED: "#ce93d8",
  SCANNING: "#fff176", MEASURED: "#a5d6a7", COMPLETE: "#4db6ac",
  EMPTY_DIRTY: "#bcaaa4",
};

function stationVisible(s) {
  // Hide stations whose board is disabled (their origins may be placeholders)
  const em = lastStatus && lastStatus.devices && lastStatus.devices.boards
    ? lastStatus.devices.boards.enabled : null;
  if (em && s.board_id in em) return !!em[s.board_id];
  const cb = CONFIG.boards.find(b => b.board_id === s.board_id);
  return !cb || cb.enabled !== false;
}

function buildHolderControls() {
  const div = document.getElementById("holder-controls");
  for (const h of CONFIG.sample_holders) {
    const box = document.createElement("div");
    box.className = "card";
    box.innerHTML =
      `<h3>${h.holder_id}</h3>
       <div class="row">
         <input class="h-count" type="number" value="5" min="1" max="${h.n_cols * h.n_rows}" style="width:4em" title="number of samples">
         <button class="h-add">Add</button>
         <button class="h-clear danger">Clear</button>
       </div>`;
    div.appendChild(box);

    bindBusy(box.querySelector(".h-add"), async () => {
      const count = parseInt(box.querySelector(".h-count").value);
      const sample_type = document.getElementById("holder-type").value || "PC";
      const res = await api("POST", `/holders/${h.holder_id}/add`,
        { count, sample_type });
      toast(`${h.holder_id}: added ${res.added} × ${sample_type}`, "ok");
      pollDashboard();
    });

    box.querySelector(".h-clear").addEventListener("click", () =>
      confirmAction(`Clear ALL slots of ${h.holder_id}? This empties the holder record.`, async () => {
        try {
          const res = await api("POST", `/holders/${h.holder_id}/clear`);
          toast(`${h.holder_id} cleared (${res.slots_cleared} slots)`, "ok");
          pollDashboard();
        } catch (err) { toast(err.message, "err"); }
      }));
  }

  // Click a holder slot on the map → paint it
  document.getElementById("platform-map").addEventListener("click", async (e) => {
    const el = e.target.closest("[data-holder]");
    if (!el) return;
    const state = document.getElementById("holder-paint").value;
    const sample_type = document.getElementById("holder-type").value || "PC";
    try {
      await api("POST", `/holders/${el.dataset.holder}/slot`, {
        col: parseInt(el.dataset.c), row: parseInt(el.dataset.r),
        state, sample_type,
      });
      pollDashboard();
    } catch (err) { toast(err.message, "err"); }
  });
}

function renderPlatformMap(holderLookup, pcbLookup, testCellSample) {
  const stations = CONFIG.sensing_stations.filter(stationVisible);
  const holders = CONFIG.sample_holders;
  const tcXYZ = (CONFIG.test_cell && CONFIG.test_cell.xyz) || null;
  const TC_SIZE = 44;   // drawn test-cell footprint (mm)
  const PAD = 30;       // margin around everything (mm)

  // Bounds in robot mm
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const ext = (x, y) => {
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  };
  for (const h of holders) {
    const [ox, oy] = h.origin_xyz;
    ext(ox, oy);
    ext(ox + (h.n_cols - 1) * h.col_spacing_mm, oy + (h.n_rows - 1) * h.row_spacing_mm);
  }
  for (const s of stations) {
    const [ox, oy] = s.origin_xyz;
    ext(ox, oy);
    ext(ox + s.col_spacing_mm, oy + 7 * s.row_spacing_mm);
  }
  if (tcXYZ) { ext(tcXYZ[0] - TC_SIZE, tcXYZ[1] - TC_SIZE); ext(tcXYZ[0] + TC_SIZE, tcXYZ[1] + TC_SIZE); }
  ext(0, 0);   // robot base
  if (minX === Infinity) return;

  const W = maxX - minX + 2 * PAD;
  const H = maxY - minY + 2 * PAD;
  // Rotated 180° to match the operator's viewpoint: robot +X points left,
  // robot +Y points toward the viewer (down on screen).
  const fx = x => maxX - x + PAD;
  const fy = y => y - minY + PAD;

  const rectC = (cx, cy, w, h, fill, extra = "", tip = "") =>
    `<rect x="${(fx(cx) - w / 2).toFixed(1)}" y="${(fy(cy) - h / 2).toFixed(1)}" ` +
    `width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="1.5" fill="${fill}" ` +
    `stroke="#78909c" stroke-width="0.5" ${extra}>` +
    (tip ? `<title>${tip}</title>` : "") + `</rect>`;
  const label = (x, y, text, size = 9) =>
    `<text x="${fx(x).toFixed(1)}" y="${fy(y).toFixed(1)}" font-size="${size}" ` +
    `text-anchor="middle" fill="#455a64">${text}</text>`;
  // In-slot sample-type text; pointer-events off so clicks reach the rect
  const cellText = (cx, cy, text, size) =>
    `<text x="${fx(cx).toFixed(1)}" y="${(fy(cy) + size * 0.36).toFixed(1)}" ` +
    `font-size="${size}" text-anchor="middle" fill="#263238" ` +
    `pointer-events="none">${text}</text>`;
  // Screen-space label with a background halo for readability
  const haloLabel = (sx, sy, text, size = 10) =>
    `<text x="${sx.toFixed(1)}" y="${sy.toFixed(1)}" font-size="${size}" ` +
    `text-anchor="middle" fill="#37474f" font-weight="600" ` +
    `stroke="#f7fafc" stroke-width="3" style="paint-order:stroke" ` +
    `pointer-events="none">${text}</text>`;
  // Screen bounding box of a grid (centres ± half a pitch)
  const gridBox = (ox, oy, spanX, spanY, pitchX, pitchY) => {
    const xs = [fx(ox - pitchX / 2), fx(ox + spanX + pitchX / 2)];
    const ys = [fy(oy - pitchY / 2), fy(oy + spanY + pitchY / 2)];
    return { x0: Math.min(...xs), x1: Math.max(...xs),
             y0: Math.min(...ys), y1: Math.max(...ys) };
  };

  let svg = `<svg viewBox="0 0 ${W.toFixed(0)} ${H.toFixed(0)}" xmlns="http://www.w3.org/2000/svg" style="max-height:75vh;display:block;margin:auto">`;
  svg += `<rect x="0" y="0" width="${W.toFixed(0)}" height="${H.toFixed(0)}" fill="#f7fafc" stroke="#cfd8dc"/>`;

  // Sample holders (clickable slots)
  for (const h of holders) {
    const [ox, oy] = h.origin_xyz;
    const spanX = (h.n_cols - 1) * h.col_spacing_mm;
    const spanY = (h.n_rows - 1) * h.row_spacing_mm;
    const cw = Math.abs(h.col_spacing_mm) * 0.82, ch = Math.abs(h.row_spacing_mm) * 0.8;
    svg += rectC(ox + spanX / 2, oy + spanY / 2,
                 Math.abs(spanX) + Math.abs(h.col_spacing_mm),
                 Math.abs(spanY) + Math.abs(h.row_spacing_mm),
                 "none", `stroke-dasharray="3 2"`);
    const lookup = holderLookup[h.holder_id] || {};
    for (let r = 0; r < h.n_rows; r++)
      for (let c = 0; c < h.n_cols; c++) {
        const info = lookup[c + "_" + r] || {};
        const fill = STATE_FILL[info.state] || STATE_FILL.EMPTY;
        const cx = ox + c * h.col_spacing_mm, cy = oy + r * h.row_spacing_mm;
        svg += rectC(cx, cy, cw, ch,
          fill,
          `data-holder="${h.holder_id}" data-c="${c}" data-r="${r}" style="cursor:pointer"`,
          `${h.holder_id} (col ${c}, row ${r}) ${info.state || "EMPTY"} ` +
          `${info.type || ""} ${info.tip || ""}`);
        if (info.type && info.state && info.state !== "EMPTY")
          svg += cellText(cx, cy, info.type, 3.6);
      }
    const hb = gridBox(ox, oy, spanX, spanY, h.col_spacing_mm, h.row_spacing_mm);
    svg += haloLabel((hb.x0 + hb.x1) / 2, hb.y0 - 5, h.holder_id);
  }

  // Sensing stations (2×8 wells)
  for (const s of stations) {
    const [ox, oy] = s.origin_xyz;
    const spanX = s.col_spacing_mm, spanY = 7 * s.row_spacing_mm;
    const cw = Math.abs(s.col_spacing_mm) * 0.55, ch = Math.abs(s.row_spacing_mm) * 0.7;
    svg += rectC(ox + spanX / 2, oy + spanY / 2,
                 Math.abs(spanX) + Math.abs(s.col_spacing_mm) * 0.7,
                 Math.abs(spanY) + Math.abs(s.row_spacing_mm),
                 "#eef4f8");
    const lookup = pcbLookup[s.id] || {};
    for (let r = 0; r < 8; r++)
      for (let c = 0; c < 2; c++) {
        const info = lookup[c + "_" + r] || {};
        const fill = STATE_FILL[info.state] || "#dde7ee";
        const sensorNo = r * 2 + c + 1;
        const cx = ox + c * s.col_spacing_mm, cy = oy + r * s.row_spacing_mm;
        svg += rectC(cx, cy, cw, ch,
          fill, "",
          `${s.id} sensor ${sensorNo} ${info.state || ""} ` +
          `${info.type || ""} ${info.tip || ""}`);
        if (info.type && info.state && !info.state.startsWith("EMPTY"))
          svg += cellText(cx, cy, info.type, 5);
      }
    const sb = gridBox(ox, oy, spanX, spanY, s.col_spacing_mm, s.row_spacing_mm);
    svg += haloLabel((sb.x0 + sb.x1) / 2, sb.y0 - 5, `${s.id} (${s.board_id})`);
  }

  // Test cell
  if (tcXYZ) {
    const fill = testCellSample ? STATE_FILL.SAMPLE_LOADED : STATE_FILL.EMPTY;
    svg += rectC(tcXYZ[0], tcXYZ[1], TC_SIZE, TC_SIZE, fill, "",
      testCellSample ? `Test cell: ${testCellSample}` : "Test cell: empty");
    svg += haloLabel(fx(tcXYZ[0]), fy(tcXYZ[1]) - TC_SIZE / 2 - 6, "test cell");
  }

  // Robot base marker at origin (0,0)
  svg += `<circle cx="${fx(0).toFixed(1)}" cy="${fy(0).toFixed(1)}" r="8" fill="#b0bec5" stroke="#78909c"/>`;
  svg += haloLabel(fx(0), fy(0) + 20, "robot base", 9);

  svg += "</svg>";
  document.getElementById("platform-map").innerHTML = svg;
}

async function pollDashboard() {
  let st;
  try { st = await api("GET", "/experiment/state"); }
  catch (e) { return; }
  const ex = st.experiment_state;

  // Test cell occupancy from samples
  let inCell = null;
  if (ex && ex.samples)
    for (const s of Object.values(ex.samples))
      if (s.in_test_cell) inCell = s.sample_id || s.id || "sample";

  const summary = document.getElementById("dash-summary");
  if (ex) {
    summary.innerHTML =
      `<div class="card">Experiment: <b>${ex.experiment_id}</b>` +
      ` &nbsp; scans: <b>${ex.scan_count}</b>` +
      ` &nbsp; completed: <b>${ex.completed}</b>` +
      ` &nbsp; test cell: <b>${inCell || "empty"}</b></div>`;
  } else {
    summary.innerHTML = `<div class="card note">No experiment state on disk yet — map shows holder_state.json only.</div>`;
  }

  // Holder slots: prefer live experiment state; fall back to holder_state.json
  const holderLookup = {};
  for (const h of CONFIG.sample_holders) {
    const lookup = {};
    if (ex) {
      for (const rec of Object.values(ex.holder_slots || {}))
        if (rec.holder_id === h.holder_id)
          lookup[rec.col + "_" + rec.row] =
            { state: rec.state, type: rec.sample_type || "", tip: rec.sample_id || "" };
    } else if (st.holder_state && st.holder_state[h.holder_id]) {
      for (const rec of st.holder_state[h.holder_id])
        lookup[rec.col + "_" + rec.row] =
          { state: rec.state, type: rec.sample_type || "", tip: rec.sample_id || "" };
    }
    holderLookup[h.holder_id] = lookup;
  }

  // PCB wells (sample type resolved through the samples registry)
  const typeById = {};
  if (ex && ex.samples)
    for (const [sid, s] of Object.entries(ex.samples))
      typeById[sid] = s.sample_type || "";
  const pcbLookup = {};
  if (ex) {
    for (const rec of Object.values(ex.pcb_sensors || {})) {
      (pcbLookup[rec.pcb_id] = pcbLookup[rec.pcb_id] || {})[rec.col + "_" + rec.row] = {
        state: rec.state,
        type: typeById[rec.current_sample_id] || "",
        tip: rec.current_sample_id || "",
      };
    }
  }

  renderPlatformMap(holderLookup, pcbLookup, inCell);
  renderTrace();
}

async function renderTrace() {
  let t;
  try { t = await api("GET", "/trace?n=30"); }
  catch (e) { return; }
  const table = document.getElementById("dash-trace");
  if (!t.events.length) {
    table.innerHTML = "<tr><td class='note'>No sample events recorded yet.</td></tr>";
    return;
  }
  const cols = ["timestamp", "event", "sample_id", "sample_type", "from", "to", "data_ref", "context"];
  table.innerHTML = "<tr>" + cols.map(c => `<th>${c}</th>`).join("") + "</tr>" +
    [...t.events].reverse().map(e => "<tr>" + cols.map(c => {
      let v = e[c] || "";
      if (c === "timestamp") v = v.replace("T", " ").slice(0, 19);
      return `<td>${v}</td>`;
    }).join("") + "</tr>").join("");
}

// ── Temperature ───────────────────────────────────────────────────────────────

async function pollTemperature() {
  let boards;
  try { boards = await api("GET", "/temperature"); }
  catch (e) {
    document.getElementById("temp-cards").innerHTML =
      `<div class="card note">Boards unavailable: ${e.message}</div>`;
    return;
  }
  const div = document.getElementById("temp-cards");

  // Drop cards for boards no longer reported (e.g. disabled in Spectral tab)
  const reported = new Set(boards.map(b => "temp-" + b.board_id));
  for (const card of [...div.children])
    if (!reported.has(card.id)) card.remove();

  for (const b of boards) {
    let card = document.getElementById("temp-" + b.board_id);
    if (!card) {
      card = document.createElement("div");
      card.className = "card temp-card";
      card.id = "temp-" + b.board_id;
      card.innerHTML =
        `<h3>${b.board_id} <span class="heat-badge heat-off">OFF</span></h3>
         <div class="temp-big" title="average of the 4 probes (PID input)"></div>
         <div class="temp-probes"></div>
         <div class="temp-meta"></div>
         <div class="spark"></div>
         <div class="row">
           <label title="temperature setpoint in degrees Celsius">Target (°C)
             <input type="number" class="t-target" step="0.5" min="0" max="60" style="width:5em"></label>
           <label title="maximum heater power as % of full output">Max power (%)
             <input type="number" class="t-power" step="1" min="1" max="100" style="width:4.5em"></label>
           <button class="t-set primary">Set</button>
           <button class="t-off">Heater off</button>
         </div>`;
      div.appendChild(card);
      const setBtn = card.querySelector(".t-set");
      bindBusy(setBtn, async () => {
        const target = parseFloat(card.querySelector(".t-target").value);
        const power = parseFloat(card.querySelector(".t-power").value);
        if (isNaN(target)) throw new Error("Enter a target temperature");
        await api("POST", `/temperature/${b.board_id}/target`,
          { target_c: target, max_power_pct: isNaN(power) ? null : power });
        toast(`${b.board_id}: target ${target} °C`, "ok");
        pollTemperature();
      });
      bindBusy(card.querySelector(".t-off"), async () => {
        await api("DELETE", `/temperature/${b.board_id}/target`);
        toast(`${b.board_id}: heaters off`, "ok");
        pollTemperature();
      });
      const cfgBoard = CONFIG.boards.find(x => x.board_id === b.board_id);
      card.querySelector(".t-power").value = (cfgBoard || {}).max_power_pct || 20;
    }
    if (b.error) {
      card.querySelector(".temp-big").textContent = "—";
      card.querySelector(".temp-meta").textContent = "error: " + b.error;
      continue;
    }
    card.querySelector(".temp-big").textContent = b.temp_c.toFixed(2) + " °C";
    card.querySelector(".temp-probes").innerHTML = b.probes
      ? Object.entries(b.probes).map(([pin, t]) =>
          `<span class="probe"><b>P${pin}</b> ${t.toFixed(1)}°</span>`).join("")
      : "";
    card.querySelector(".temp-meta").textContent =
      `target: ${b.target_temp_c != null ? b.target_temp_c + " °C" : "off"}  ·  ` +
      `heater power now: ${b.duty_pct}%  ·  power limit: ${b.max_power_pct}%`;
    const badge = card.querySelector(".heat-badge");
    const labels = { off: "HEATERS OFF", heating: "HEATING", at_target: "AT TARGET" };
    badge.textContent = labels[b.status] || b.status || "?";
    badge.className = "heat-badge heat-" + (b.status || "off");
    const hist = tempHistory[b.board_id] = (tempHistory[b.board_id] || []);
    hist.push(b.temp_c);
    if (hist.length > 120) hist.shift();
    sparkline(card.querySelector(".spark"), hist);
  }
}

bindBusy(document.getElementById("temp-all-off"), async () => {
  await api("POST", "/temperature/all-off");
  toast("All heaters off", "ok");
  pollTemperature();
});

// ── Spectral ──────────────────────────────────────────────────────────────────

const SPEC_CHANNELS = ["Violet_%", "Indigo_%", "Blue_%", "Cyan_%", "Green_%", "Yellow_%", "Orange_%", "Red_%"];
const SPEC_COLORS = ["#7b1fa2", "#3f51b5", "#1976d2", "#00acc1", "#43a047", "#fdd835", "#fb8c00", "#e53935"];

let lastBoardsJSON = "";

async function pollSpectralBoards() {
  let data;
  try { data = await api("GET", "/spectral/boards"); }
  catch (e) { return; }
  const json = JSON.stringify(data);
  if (json === lastBoardsJSON) return;   // don't rebuild checkboxes needlessly
  lastBoardsJSON = json;

  const table = document.getElementById("spec-boards-table");
  table.innerHTML = "<tr><th>Board</th><th>Enabled</th><th>Connected</th></tr>";
  for (const b of data.boards) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${b.board_id}</td>
       <td><input type="checkbox" ${b.enabled ? "checked" : ""}></td>
       <td><i class="dot ${b.connected ? "on" : ""}"></i></td>`;
    table.appendChild(tr);
    tr.querySelector("input").addEventListener("change", async (e) => {
      const enabled = e.target.checked;
      try {
        await api("POST", `/spectral/boards/${b.board_id}/enabled`, { enabled });
        toast(`${b.board_id} ${enabled ? "enabled" : "disabled"}`, "ok");
      } catch (err) {
        toast(err.message, "err");
        e.target.checked = !enabled;   // revert on failure
      }
      lastBoardsJSON = "";
      pollSpectralBoards();
    });
  }

  // Keep the scan dropdown in sync with enabled boards
  const sel = document.getElementById("spec-board");
  const prev = sel.value;
  sel.innerHTML = `<option value="">all boards</option>` +
    data.boards.filter(b => b.enabled)
      .map(b => `<option>${b.board_id}</option>`).join("");
  sel.value = prev;
}

async function pollSpectral() {
  pollSpectralBoards();
  const board = document.getElementById("spec-board").value || null;
  let data;
  try { data = await api("GET", `/spectral/latest?n=40${board ? "&board_id=" + board : ""}`); }
  catch (e) { return; }
  renderSpectralRows(data.rows);
}

bindBusy(document.getElementById("led-on"), async () => {
  const res = await api("POST", "/spectral/led", { on: true });
  toast(`LED panel ON (${res.boards.join(", ")})`, "ok");
});
bindBusy(document.getElementById("led-off"), async () => {
  const res = await api("POST", "/spectral/led", { on: false });
  toast("LED panel OFF", "ok");
});

function renderSpectralRows(rows) {
  const table = document.getElementById("spec-table");
  if (!rows.length) { table.innerHTML = "<tr><td class='note'>No data yet.</td></tr>"; return; }
  const cols = ["timestamp", "board_id", "sensor", "hex_color", "sample_id", "temp_c", ...SPEC_CHANNELS];
  let html = "<tr>" + cols.map(c => `<th>${c.replace("_%", "")}</th>`).join("") + "</tr>";
  for (const r of [...rows].reverse()) {
    html += "<tr>" + cols.map(c => {
      let v = r[c];
      if (c === "hex_color" && v)
        return `<td><span style="background:${v};padding:1px 10px;border-radius:4px;border:1px solid #ccc"></span> ${v}</td>`;
      if (typeof v === "number") v = Math.round(v * 100) / 100;
      return `<td>${v == null ? "" : v}</td>`;
    }).join("") + "</tr>";
  }
  table.innerHTML = html;

  const last = rows[rows.length - 1];
  const vals = SPEC_CHANNELS.map(c => last[c] || 0);
  barPlot(document.getElementById("spec-plot"), SPEC_CHANNELS.map(c => c.replace("_%", "")),
          vals, SPEC_COLORS,
          { xlabel: `Latest: ${last.board_id} sensor ${last.sensor} (${last.timestamp || ""})` });
}

bindBusy(document.getElementById("spec-scan"), async () => {
  const board = document.getElementById("spec-board").value || null;
  const status = document.getElementById("spec-scan-status");
  status.textContent = "Scanning…";
  try {
    const res = await api("POST", "/spectral/scan", { board_ids: board ? [board] : null });
    status.textContent = `${res.new_rows} rows recorded.`;
    toast(`Scan complete: ${res.new_rows} readings`, "ok");
    pollSpectral();
  } finally {
    setTimeout(() => { status.textContent = ""; }, 5000);
  }
});

// ── Robot / locations ─────────────────────────────────────────────────────────

function buildLocationPicker(containerId) {
  const div = document.getElementById(containerId);
  const sel = document.createElement("select");
  sel.innerHTML =
    CONFIG.sample_holders.map(h => `<option value="holder:${h.holder_id}">${h.holder_id}</option>`).join("") +
    CONFIG.sensing_stations.map(s => `<option value="pcb:${s.id}">${s.id}</option>`).join("") +
    `<option value="test_cell:">test cell</option>`;
  const col = document.createElement("input");
  col.type = "number"; col.min = 0; col.value = 0; col.style.width = "4.5em"; col.title = "col";
  const row = document.createElement("input");
  row.type = "number"; row.min = 0; row.value = 0; row.style.width = "4.5em"; row.title = "row";
  const wrap = document.createElement("div");
  wrap.className = "locpick";
  wrap.append(sel, document.createTextNode("col"), col, document.createTextNode("row"), row);
  div.appendChild(wrap);
  sel.addEventListener("change", () => {
    const isTc = sel.value.startsWith("test_cell");
    col.disabled = row.disabled = isTc;
  });
  return () => {
    const [type, id] = sel.value.split(":");
    if (type === "test_cell") return { type: "test_cell" };
    return { type, id, col: parseInt(col.value || 0), row: parseInt(row.value || 0) };
  };
}

function locText(loc) {
  return loc.type === "test_cell" ? "test cell" : `${loc.id} (col ${loc.col}, row ${loc.row})`;
}

let getFromLoc, getToLoc;

function setupRobotTab() {
  getFromLoc = buildLocationPicker("loc-from");
  getToLoc = buildLocationPicker("loc-to");

  bindBusy(document.getElementById("rb-home"), () => api("POST", "/robot/home").then(() => toast("Homed", "ok")));
  bindBusy(document.getElementById("rb-safez"), () => api("POST", "/robot/safe-z").then(() => toast("Raised to safe Z", "ok")));
  bindBusy(document.getElementById("rb-grip-open"), () => api("POST", "/robot/gripper", { action: "open" }));
  bindBusy(document.getElementById("rb-grip-close"), () => api("POST", "/robot/gripper", { action: "close" }));

  document.getElementById("rb-move").addEventListener("click", () => {
    const x = parseFloat(document.getElementById("rb-x").value);
    const y = parseFloat(document.getElementById("rb-y").value);
    const z = parseFloat(document.getElementById("rb-z").value);
    if ([x, y, z].some(isNaN)) return toast("Enter X, Y, Z", "err");
    confirmAction(`Move robot to X=${x}, Y=${y}, Z=${z} mm?`, async () => {
      try { await api("POST", "/robot/move", { x, y, z }); toast("Move complete", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });

  document.getElementById("rb-transfer").addEventListener("click", () => {
    const from = getFromLoc(), to = getToLoc();
    confirmAction(`Transfer sample: ${locText(from)} → ${locText(to)}?`, async () => {
      try { await api("POST", "/robot/transfer", { from, to }); toast("Transfer complete", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
  document.getElementById("rb-pick").addEventListener("click", () => {
    const from = getFromLoc();
    confirmAction(`Pick sample from ${locText(from)}? (arm will hold it)`, async () => {
      try { await api("POST", "/robot/pick", { location: from }); toast("Picked", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
  document.getElementById("rb-place").addEventListener("click", () => {
    const to = getToLoc();
    confirmAction(`Place held sample at ${locText(to)}?`, async () => {
      try { await api("POST", "/robot/place", { location: to }); toast("Placed", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });

  // Test cell
  document.getElementById("tc-insert").addEventListener("click", () => {
    const from = getFromLoc();
    confirmAction(`Insert sample from ${locText(from)} into the test cell (pick → move → piston → release)?`, async () => {
      try { await api("POST", "/testcell/insert", { from }); toast("Inserted into test cell", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
  document.getElementById("tc-retrieve").addEventListener("click", () => {
    const to = getToLoc();
    confirmAction(`Retrieve sample from test cell and place at ${locText(to)}?`, async () => {
      try { await api("POST", "/testcell/retrieve", { to }); toast("Retrieved from test cell", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
  document.getElementById("tc-piston-on").addEventListener("click", () =>
    confirmAction("Engage test cell piston?", async () => {
      try { await api("POST", "/testcell/piston", { engage: true }); toast("Piston engaged", "ok"); }
      catch (e) { toast(e.message, "err"); }
    }));
  document.getElementById("tc-piston-off").addEventListener("click", () =>
    confirmAction("Release test cell piston?", async () => {
      try { await api("POST", "/testcell/piston", { engage: false }); toast("Piston released", "ok"); }
      catch (e) { toast(e.message, "err"); }
    }));
  document.getElementById("tc-fill").addEventListener("click", () => {
    const ml = parseFloat(document.getElementById("tc-fill-ml").value);
    if (isNaN(ml)) return toast("Enter volume", "err");
    confirmAction(`Fill test cell with ${ml} mL (${CONFIG.test_cell.fill_pump})?`, async () => {
      try { await api("POST", "/testcell/fill", { volume_ml: ml }); toast("Fill complete", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
  document.getElementById("tc-drain").addEventListener("click", () => {
    const ml = parseFloat(document.getElementById("tc-drain-ml").value);
    if (isNaN(ml)) return toast("Enter volume", "err");
    confirmAction(`Drain ${ml} mL from test cell?`, async () => {
      try { await api("POST", "/testcell/drain", { volume_ml: ml }); toast("Drain complete", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
}

// ── Calibration ───────────────────────────────────────────────────────────────

function calShowOffset(s) {
  const el = document.getElementById("cal-offset");
  const pad = document.getElementById("cal-jog");
  if (!s.active) { el.textContent = ""; pad.style.display = "none"; return; }
  pad.style.display = "";
  const [dx, dy, dz] = s.offset;
  el.textContent = `${s.id}: offset X ${dx.toFixed(2)}  Y ${dy.toFixed(2)}  Z ${dz.toFixed(2)} mm`;
}

function setupCalibration() {
  const sel = document.getElementById("cal-target");
  sel.innerHTML =
    CONFIG.sample_holders.map(h => `<option value="holder:${h.holder_id}">${h.holder_id}</option>`).join("") +
    CONFIG.sensing_stations.map(s => `<option value="pcb:${s.id}">${s.id}</option>`).join("");

  document.getElementById("cal-start").addEventListener("click", () => {
    const [type, id] = sel.value.split(":");
    confirmAction(
      `Start calibration of ${id}? The robot will move over its slot (col 0, row 0) ` +
      `and hover 20 mm above pick height.`, async () => {
        try {
          const s = await api("POST", "/calibrate/start", { type, id });
          calShowOffset(s);
          toast(`Calibrating ${id} — jog until aligned, then Save`, "ok");
        } catch (e) { toast(e.message, "err"); }
      });
  });

  document.querySelectorAll("#cal-jog [data-jog]").forEach(btn => {
    bindBusy(btn, async () => {
      const step = parseFloat(document.getElementById("cal-step").value);
      const j = btn.dataset.jog;
      const body = { dx: 0, dy: 0, dz: 0 };
      body["d" + j[0]] = (j[1] === "+" ? 1 : -1) * step;
      const s = await api("POST", "/calibrate/jog", body);
      calShowOffset(s);
    });
  });

  document.getElementById("cal-save").addEventListener("click", () => {
    confirmAction(
      "Save the jogged position as the new origin in config.yaml?", async () => {
        try {
          const res = await api("POST", "/calibrate/save");
          toast(`${res.id}: origin ${res.old_origin.join(",")} → ${res.new_origin.join(",")}` +
                (res.new_pick_z != null ? ` (pick_z ${res.new_pick_z})` : ""), "ok");
          calShowOffset({ active: false });
          CONFIG = await api("GET", "/config");   // map + pickers use new geometry
        } catch (e) { toast(e.message, "err"); }
      });
  });

  bindBusy(document.getElementById("cal-cancel"), async () => {
    await api("POST", "/calibrate/cancel");
    calShowOffset({ active: false });
    toast("Calibration cancelled — arm raised", "ok");
  });
}

// ── Pumps ─────────────────────────────────────────────────────────────────────

let pumpsBuilt = false;

async function pollPumps() {
  let info;
  try { info = await api("GET", "/pumps"); }
  catch (e) { return; }

  document.getElementById("pumps-env").textContent = info.environment
    ? `Fluidic PCB environment: ${info.environment.temp_c.toFixed(1)} °C, ${info.environment.humidity_pct.toFixed(0)} % RH`
    : "Fluidic PCB environment: (connect a stepper pump first)";

  if (pumpsBuilt) return;
  pumpsBuilt = true;

  const peri = document.getElementById("pumps-peri");
  peri.innerHTML = "<tr><th>Pump</th><th>Flow (mL/s)</th><th>Volume (mL)</th><th></th></tr>";
  for (const [name, p] of Object.entries(info.peristaltic)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${name}</td><td>${p.flow_rate_ml_per_s}</td>
      <td><input type="number" value="1" min="0.1" step="0.5" style="width:5em"></td>
      <td><button class="primary">Run</button></td>`;
    peri.appendChild(tr);
    bindBusy(tr.querySelector("button"), async () => {
      const ml = parseFloat(tr.querySelector("input").value);
      await api("POST", `/pumps/peristaltic/${name}`, { volume_ml: ml });
      toast(`${name}: ${ml} mL dispensed`, "ok");
    });
  }

  const step = document.getElementById("pumps-step");
  step.innerHTML = "<tr><th>#</th><th>Role</th><th>Volume (mL)</th><th>Flow (mL/s)</th><th></th></tr>";
  for (const s of info.steppers) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.no}</td><td>${s.role}</td>
      <td><input class="ml" type="number" value="0.5" step="0.1" style="width:5em"></td>
      <td><input class="fr" type="number" value="0.02" step="0.01" min="0.01" style="width:5em"></td>
      <td><button class="primary">Run</button></td>`;
    step.appendChild(tr);
    bindBusy(tr.querySelector("button"), async () => {
      const ml = parseFloat(tr.querySelector(".ml").value);
      const fr = parseFloat(tr.querySelector(".fr").value);
      await api("POST", `/pumps/stepper/${s.no}`, { ml, flow_rate: fr });
      toast(`Stepper ${s.no}: ${ml} mL`, "ok");
    });
  }
}

bindBusy(document.getElementById("pumps-stop"), async () => {
  await api("POST", "/pumps/stop");
  toast("Emergency stop sent — fluidic controller resetting", "ok");
});

document.getElementById("pumps-prime").addEventListener("click", () => {
  const ml = parseFloat(document.getElementById("prime-ml").value) || 2;
  confirmAction(
    `Prime ALL pumps? Each peristaltic pump runs ${ml} mL, then all 4 stepper ` +
    `pumps run 1 mL together. Takes ~30-40 s.`, async () => {
      const btn = document.getElementById("pumps-prime");
      btn.disabled = true;
      try {
        const res = await api("POST", "/pumps/prime", { peristaltic_ml: ml });
        toast(`Primed: ${res.primed.join(", ")}`, "ok");
      } catch (e) { toast(e.message, "err"); }
      finally { btn.disabled = false; }
    });
});

// ── Electrochemistry ──────────────────────────────────────────────────────────

let ecPolling = false;

function setupEchemTab() {
  const sel = document.getElementById("ec-technique");
  sel.innerHTML = Object.entries(CONFIG.echem_techniques)
    .map(([k, v]) => `<option value="${k}">${k} — ${v.label}</option>`).join("");
  sel.addEventListener("change", renderEcForm);
  renderEcForm();

  bindBusy(document.getElementById("ec-run"), async () => {
    const technique = sel.value;
    const params = {};
    document.querySelectorAll("#ec-params input, #ec-params select").forEach(inp => {
      params[inp.dataset.name] = parseFloat(inp.value);
    });
    const sample_id = document.getElementById("ec-sample").value || "";
    const res = await api("POST", "/echem/run", { technique, params, sample_id });
    toast(`${technique} started (run ${res.run_id})`, "ok");
    ecPolling = true;
  });
  bindBusy(document.getElementById("ec-abort"), async () => {
    await api("POST", "/echem/abort");
    toast("Echem abort requested", "ok");
  });
}

function renderEcForm() {
  const technique = document.getElementById("ec-technique").value;
  const spec = CONFIG.echem_techniques[technique];
  const div = document.getElementById("ec-params");
  div.innerHTML = spec.params.map(p => {
    if (p.type === "select") {
      const opts = (p.options || []).map(o =>
        (o && typeof o === "object") ? o : { value: o, label: o });
      return `<label>${p.label}</label><select data-name="${p.name}">` +
        opts.map(o => `<option value="${o.value}"${String(o.value) === String(p.default) ? " selected" : ""}>${o.label}</option>`).join("") +
        `</select>`;
    }
    return `<label>${p.label}</label><input type="number" data-name="${p.name}" value="${p.default}" step="any">`;
  }).join("");
}

function findCol(columns, patterns) {
  for (const pat of patterns) {
    const hit = columns.find(c => pat.test(c));
    if (hit) return hit;
  }
  return null;
}

async function pollEchem() {
  let s;
  try { s = await api("GET", "/echem/status"); }
  catch (e) { return; }
  const el = document.getElementById("ec-status");
  if (s.state === "running") {
    const secs = Math.round(Date.now() / 1000 - s.started_at);
    el.textContent = `Running ${s.technique} (${secs}s)…`;
    ecPolling = true;
  } else {
    el.textContent = s.state === "idle" ? "" :
      `${s.technique || ""} ${s.state}` + (s.error ? " — " + s.error.split("\n")[0] : "");
    if (ecPolling && (s.state === "done" || s.state === "aborted") && s.run_id) {
      ecPolling = false;
      renderEcResult(s.run_id, s.technique);
    }
  }
  // refresh past runs list
  try {
    const r = await api("GET", "/echem/runs");
    const table = document.getElementById("ec-runs");
    table.innerHTML = "<tr><th>Run</th><th>Technique</th><th>Params</th><th></th></tr>" +
      r.runs.slice(0, 20).map(run =>
        `<tr><td>${run.run_id}</td><td>${run.technique}${run.aborted ? " (aborted)" : ""}</td>
         <td class="note">${Object.entries(run.params || {}).map(([k, v]) => k + "=" + v).join(", ")}</td>
         <td><button data-run="${run.run_id}" data-tech="${run.technique}">Plot</button></td></tr>`
      ).join("");
    table.querySelectorAll("button").forEach(b =>
      b.addEventListener("click", () => renderEcResult(b.dataset.run, b.dataset.tech)));
  } catch (e) { /* ignore */ }
}

async function renderEcResult(runId, technique) {
  let res;
  try { res = await api("GET", `/echem/result/${runId}`); }
  catch (e) { toast(e.message, "err"); return; }
  const cols = res.columns;
  const p1 = document.getElementById("ec-plot");
  const p2 = document.getElementById("ec-plot2");
  p2.innerHTML = "";

  if (technique === "EIS") {
    const fc = findCol(cols, [/freq/i]);
    const zr = findCol(cols, [/zreal|z'|real/i]);
    const zi = findCol(cols, [/zimag|z''|imag/i]);
    const zm = findCol(cols, [/zmod/i]);
    if (zr && zi) {
      const negZi = res.series[zi].map(v => (v == null ? null : -v));
      linePlot(p1, res.series[zr], [{ ys: negZi, label: "Nyquist" }],
        { xlabel: `${zr} (Ω)`, ylabel: `-${zi} (Ω)`, equal: true });
    }
    if (fc && zm) {
      linePlot(p2, res.series[fc], [{ ys: res.series[zm], label: "|Z|" }],
        { xlabel: "Frequency (Hz)", ylabel: "|Z| (Ω)", logx: true, logy: true });
    }
    return;
  }

  if (technique === "CV") {
    const vf = findCol(cols, [/vf/i]) || cols[1];
    const im = findCol(cols, [/^im/i, /im \(a\)/i]) || cols[3];
    linePlot(p1, res.series[vf], [{ ys: res.series[im], label: "CV" }],
      { xlabel: vf, ylabel: im });
    return;
  }

  // CP / CA / OCP: time series
  const t = findCol(cols, [/time/i]) || cols[0];
  const y = technique === "CA"
    ? (findCol(cols, [/^im/i]) || cols[3])
    : (findCol(cols, [/vf/i]) || cols[1]);
  linePlot(p1, res.series[t], [{ ys: res.series[y], label: technique }],
    { xlabel: t, ylabel: y });
}

// ── Experiment ────────────────────────────────────────────────────────────────

let exLogSeq = 0;

async function setupExperimentTab() {
  const sel = document.getElementById("ex-file");
  try {
    const files = await api("GET", "/experiment/files");
    sel.innerHTML = files.files.map(f =>
      `<option value="${f.path}">${f.path}</option>`).join("");
    sel.addEventListener("change", () => showFileInfo(files.files));
    showFileInfo(files.files);
  } catch (e) { /* ignore */ }

  document.getElementById("ex-start").addEventListener("click", () => {
    const path = sel.value;
    const resume = document.getElementById("ex-resume").checked;
    if (!path) return toast("Select an experiment file", "err");
    confirmAction(
      `Start experiment '${path}'${resume ? " (RESUME previous state)" : ""}? ` +
      `Manual control will be locked until it finishes.`, async () => {
        try {
          const res = await api("POST", "/experiment/start", { experiment_path: path, resume });
          toast(`Experiment started (run ${res.run_id})`, "ok");
          exLogSeq = 0;
          document.getElementById("ex-log").textContent = "";
        } catch (e) { toast(e.message, "err"); }
      });
  });
  document.getElementById("ex-abort-soft").addEventListener("click", () =>
    confirmAction("Abort experiment after the current step completes?", async () => {
      try { await api("POST", "/experiment/abort", { hard: false }); toast("Soft abort requested", "ok"); }
      catch (e) { toast(e.message, "err"); }
    }));
  document.getElementById("ex-abort-hard").addEventListener("click", () =>
    confirmAction("HARD abort: inject KeyboardInterrupt into the running experiment? " +
      "Cannot interrupt a blocking serial operation.", async () => {
      try { await api("POST", "/experiment/abort", { hard: true }); toast("Hard abort requested", "ok"); }
      catch (e) { toast(e.message, "err"); }
    }));
}

function showFileInfo(files) {
  const path = document.getElementById("ex-file").value;
  const f = files.find(x => x.path === path);
  document.getElementById("ex-file-info").innerHTML = f
    ? `<b>${f.experiment_id || ""}</b> ${f.description || ""}<br>Steps: ${f.steps.join(" → ")}`
    : "";
}

function renderExperimentStatus(s) {
  const div = document.getElementById("ex-status");
  if (!s) return;
  if (s.running) {
    div.innerHTML = `<b>Running</b>: ${s.experiment_id || s.experiment_path}<br>` +
      `Step ${s.step_index != null ? s.step_index + 1 : "?"} / ${s.n_steps || "?"}: <b>${s.step || "starting…"}</b>`;
    const pct = s.n_steps ? ((s.step_index + 1) / s.n_steps) * 100 : 0;
    document.getElementById("ex-progress-bar").style.width = pct + "%";
  } else {
    div.innerHTML = s.outcome
      ? `Last run: <b>${s.outcome}</b> (${s.experiment_id || ""})` +
        (s.error ? `<br><span class="note">${String(s.error).split("\n")[0]}</span>` : "")
      : `<span class="note">No experiment running.</span>`;
    if (!s.running) document.getElementById("ex-progress-bar").style.width =
      s.outcome === "completed" ? "100%" : "0";
  }
}

async function pollExperiment() {
  try {
    const s = await api("GET", "/experiment/status");
    renderExperimentStatus(s);
    const log = await api("GET", `/experiment/log?since=${exLogSeq}`);
    if (log.entries.length) {
      const pre = document.getElementById("ex-log");
      const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      for (const e of log.entries) {
        const t = new Date(e.ts * 1000).toLocaleTimeString();
        pre.textContent += `[${t}] ${e.level} ${e.msg}\n`;
      }
      exLogSeq = log.last_seq;
      // Trim displayed log
      const lines = pre.textContent.split("\n");
      if (lines.length > 1500) pre.textContent = lines.slice(-1000).join("\n");
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
  } catch (e) { /* ignore */ }
}

// ── Init ──────────────────────────────────────────────────────────────────────

(async function init() {
  try {
    CONFIG = await api("GET", "/config");
  } catch (e) {
    toast("Failed to load config: " + e.message, "err");
    return;
  }
  // Spectral board dropdown (enabled boards only; kept in sync by pollSpectralBoards)
  document.getElementById("spec-board").innerHTML =
    `<option value="">all boards</option>` +
    CONFIG.boards.filter(b => b.enabled !== false)
      .map(b => `<option>${b.board_id}</option>`).join("");

  buildHolderControls();
  setupRobotTab();
  setupCalibration();
  createSequenceBuilder(document.getElementById("echem-builder"), "echem")
    .catch(e => toast("Echem builder failed: " + e.message, "err"));
  createSequenceBuilder(document.getElementById("procedure-builder"), "procedure")
    .catch(e => toast("Procedure builder failed: " + e.message, "err"));
  setupEchemTab();
  setupExperimentTab();
  pollHeader();
  pollDashboard();
})();
