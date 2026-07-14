/* builder.js — drag/drop sequence builder used by the Electrochemistry and
   Experiment tabs. Self-contained; depends on api()/toast()/confirmAction()
   from app.js and the global CONFIG for location pickers.

   createSequenceBuilder(rootEl, kind) where kind = "echem" | "procedure".
   Model: steps = [ {action, params} | {action:"loop", count, steps:[...]} ]
*/
"use strict";

async function createSequenceBuilder(root, kind) {
  const reg = (await api("GET", `/sequences/actions?kind=${kind}`)).actions;
  const model = { name: "", data_dir: "", steps: [] };
  let statusTimer = null;

  // ── Skeleton ────────────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="builder">
      <div class="b-palette">
        <h3>Blocks</h3>
        <div class="b-blocks"></div>
      </div>
      <div class="b-main">
        <div class="row wrap">
          <label>Name <input class="b-name" placeholder="my-sequence" style="width:11em"></label>
          ${kind === "echem"
            ? `<label>Data folder <input class="b-datadir" placeholder="(default data/echem)" style="width:11em" title="subfolder under data/echem for this sequence's results"></label>`
            : ""}
          <select class="b-saved"><option value="">— saved sequences —</option></select>
          <button class="b-load">Load</button>
          <button class="b-save">Save</button>
          <button class="b-delete">Delete</button>
        </div>
        <div class="b-drop b-seq" data-path="root"></div>
        <div class="row">
          <button class="b-run primary">▶ Run sequence</button>
          <button class="b-abort danger">Abort</button>
          <span class="b-est note"></span>
          <span class="b-status note"></span>
        </div>
        <div class="progress"><div class="b-progress"></div></div>
        <div class="b-analysis">
          <h3>Analysis</h3>
          <div class="row">
            <select class="b-reports"><option value="">— sequence reports —</option></select>
            <button class="b-report-show">Show</button>
            <span class="note">Reports are generated automatically when a sequence with echem steps finishes.</span>
          </div>
          <div class="b-report"></div>
        </div>
      </div>
    </div>`;

  const seqEl = root.querySelector(".b-seq");
  attachDropZone(seqEl, "root");  // once — seqEl persists across renders, so re-attaching stacks duplicate drop handlers

  // ── Palette ────────────────────────────────────────────────────────────────
  const groups = {};
  for (const [name, spec] of Object.entries(reg))
    (groups[spec.group] = groups[spec.group] || []).push([name, spec]);
  const blocksEl = root.querySelector(".b-blocks");
  const groupOrder = ["echem", "flow", "robot", "testcell", "pumps", "spectral"];
  for (const g of groupOrder) {
    if (!groups[g]) continue;
    const h = document.createElement("div");
    h.className = "b-group";
    h.textContent = g;
    blocksEl.appendChild(h);
    for (const [name, spec] of groups[g])
      blocksEl.appendChild(makePaletteBlock(name, spec.label));
  }
  const lh = document.createElement("div");
  lh.className = "b-group";
  lh.textContent = "control";
  blocksEl.appendChild(lh);
  blocksEl.appendChild(makePaletteBlock("loop", "Loop (repeat N×)"));

  function makePaletteBlock(action, label) {
    const el = document.createElement("div");
    el.className = "b-block";
    el.draggable = true;
    el.textContent = label;
    el.title = "drag into the sequence, or click to append";
    el.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", JSON.stringify({ src: "palette", action }));
    });
    el.addEventListener("click", () => { insertStep(newStep(action), "root", model.steps.length); });
    return el;
  }

  function newStep(action) {
    if (action === "loop") return { action: "loop", count: 3, steps: [] };
    const params = {};
    for (const p of reg[action].params) {
      if (p.type === "location") params[p.name] = { type: "holder", id: (CONFIG.sample_holders[0] || {}).holder_id, col: 0, row: 0 };
      else params[p.name] = p.default;
    }
    return { action, params };
  }

  // ── Model ops (paths: "root" or "loop:<index>") ────────────────────────────
  function containerOf(path) {
    if (path === "root") return model.steps;
    const idx = parseInt(path.split(":")[1]);
    return model.steps[idx].steps;
  }
  function insertStep(step, path, index) {
    if (path !== "root" && step.action === "loop") {
      toast("Loops cannot be nested", "err");
      return;
    }
    containerOf(path).splice(index, 0, step);
    render();
  }
  function removeStep(path, index) {
    containerOf(path).splice(index, 1);
    render();
  }
  function moveStep(fromPath, fromIndex, toPath, toIndex) {
    const src = containerOf(fromPath);
    const step = src[fromIndex];
    if (toPath !== "root" && step.action === "loop") {
      toast("Loops cannot be nested", "err");
      return;
    }
    src.splice(fromIndex, 1);
    if (fromPath === toPath && toIndex > fromIndex) toIndex--;
    containerOf(toPath).splice(toIndex, 0, step);
    render();
  }

  // ── Duration estimate (while building) ─────────────────────────────────────
  let estTimer = null;
  function scheduleEstimate() {
    clearTimeout(estTimer);
    estTimer = setTimeout(updateEstimate, 600);
  }
  async function updateEstimate() {
    const el = root.querySelector(".b-est");
    if (!model.steps.length) { el.textContent = ""; return; }
    try {
      const r = await api("POST", "/sequences/estimate", { kind, sequence: serialize() });
      el.textContent = r.total_s != null ? `est. duration ≈ ${fmtDur(r.total_s)}` : "";
    } catch (e) { el.textContent = ""; }
  }
  function fmtDur(s) {
    s = Math.max(0, Math.round(s));
    if (s < 90) return s + " s";
    if (s < 5400) return Math.round(s / 60) + " min";
    return (s / 3600).toFixed(1) + " h";
  }

  // ── Rendering ───────────────────────────────────────────────────────────────
  function render() {
    seqEl.innerHTML = "";
    if (!model.steps.length)
      seqEl.innerHTML = `<div class="note b-empty">Drag blocks here (or click them in the palette)</div>`;
    model.steps.forEach((step, i) => seqEl.appendChild(renderStep(step, "root", i)));
    scheduleEstimate();
  }

  function renderStep(step, path, index) {
    const el = document.createElement("div");
    el.className = "b-step" + (step.action === "loop" ? " b-loop" : "");
    el.draggable = true;
    el.addEventListener("dragstart", e => {
      e.stopPropagation();
      e.dataTransfer.setData("text/plain", JSON.stringify({ src: "seq", path, index }));
    });

    const head = document.createElement("div");
    head.className = "b-step-head";
    const title = step.action === "loop" ? "Loop" : (reg[step.action] || {}).label || step.action;
    head.innerHTML = `<span class="b-grip">⠿</span><b>${title}</b>`;
    const del = document.createElement("button");
    del.className = "b-del";
    del.textContent = "✕";
    del.addEventListener("click", () => removeStep(path, index));
    head.appendChild(del);
    el.appendChild(head);

    if (step.action === "loop") {
      const cnt = document.createElement("div");
      cnt.className = "row";
      cnt.innerHTML = `<label>Repeat <input type="number" min="1" max="500" value="${step.count}" style="width:5em"> times</label>`;
      cnt.querySelector("input").addEventListener("change", e => {
        step.count = Math.max(1, parseInt(e.target.value) || 1);
        scheduleEstimate();
      });
      el.appendChild(cnt);
      const body = document.createElement("div");
      body.className = "b-drop b-loop-body";
      const loopPath = `loop:${index}`;
      if (!step.steps.length)
        body.innerHTML = `<div class="note b-empty">drop steps to repeat</div>`;
      step.steps.forEach((s, j) => body.appendChild(renderStep(s, loopPath, j)));
      attachDropZone(body, loopPath);
      el.appendChild(body);
    } else {
      el.appendChild(renderParams(step));
    }
    return el;
  }

  function renderParams(step) {
    const spec = reg[step.action];
    const div = document.createElement("div");
    div.className = "b-params";
    for (const p of spec.params) {
      const lab = document.createElement("label");
      lab.textContent = p.label;
      div.appendChild(lab);
      if (p.type === "location") {
        div.appendChild(locationEditor(step.params[p.name]));
      } else if (p.type === "select") {
        // Options are plain strings or {value, label} objects (e.g. Gamry
        // range steps, where the value is numeric and the label human-readable)
        const sel = document.createElement("select");
        const opts = (p.options || []).map(o =>
          (o && typeof o === "object") ? o : { value: o, label: o });
        const cur = step.params[p.name];
        let html = opts.map(o =>
          `<option value="${o.value}"${String(o.value) === String(cur) ? " selected" : ""}>${o.label}</option>`).join("");
        if (cur != null && !opts.some(o => String(o.value) === String(cur)))
          html += `<option value="${cur}" selected>${cur} (legacy)</option>`;
        sel.innerHTML = html;
        sel.addEventListener("change", () => { step.params[p.name] = sel.value; scheduleEstimate(); });
        div.appendChild(sel);
      } else {
        const inp = document.createElement("input");
        inp.type = "number";
        inp.step = "any";
        inp.value = step.params[p.name];
        inp.addEventListener("change", () => {
          step.params[p.name] = p.type === "int" ? parseInt(inp.value) : parseFloat(inp.value);
          scheduleEstimate();
        });
        if (p.ref_select) {
          // Voltage setpoint: per-param reference override (vs_<name>).
          // Empty = use the block-level "Voltages vs (default)".
          const wrap = document.createElement("span");
          wrap.className = "refpick";
          const sel = document.createElement("select");
          sel.title = "Reference for this setpoint (empty = block default)";
          sel.innerHTML = `<option value="">(default)</option>` +
            ["Ref", "OCV", "previous endpoint"]
              .map(o => `<option${o === step.params["vs_" + p.name] ? " selected" : ""}>${o}</option>`).join("");
          sel.addEventListener("change", () => {
            if (sel.value) step.params["vs_" + p.name] = sel.value;
            else delete step.params["vs_" + p.name];
            scheduleEstimate();
          });
          wrap.append(inp, sel);
          div.appendChild(wrap);
        } else {
          div.appendChild(inp);
        }
      }
    }
    return div;
  }

  function locationEditor(loc) {
    const wrap = document.createElement("span");
    wrap.className = "locpick";
    const sel = document.createElement("select");
    sel.innerHTML =
      CONFIG.sample_holders.map(h => `<option value="holder:${h.holder_id}">${h.holder_id}</option>`).join("") +
      CONFIG.sensing_stations.map(s => `<option value="pcb:${s.id}">${s.id}</option>`).join("") +
      `<option value="test_cell:">test cell</option>`;
    sel.value = `${loc.type}:${loc.id || ""}`;
    const col = document.createElement("input");
    col.type = "number"; col.min = 0; col.value = loc.col || 0; col.style.width = "4em";
    const row = document.createElement("input");
    row.type = "number"; row.min = 0; row.value = loc.row || 0; row.style.width = "4em";
    const sync = () => {
      const [type, id] = sel.value.split(":");
      loc.type = type; loc.id = id || undefined;
      loc.col = parseInt(col.value) || 0; loc.row = parseInt(row.value) || 0;
      col.disabled = row.disabled = type === "test_cell";
    };
    sel.addEventListener("change", sync);
    col.addEventListener("change", sync);
    row.addEventListener("change", sync);
    sync();
    wrap.append(sel, document.createTextNode(" c"), col, document.createTextNode(" r"), row);
    return wrap;
  }

  // ── Drag/drop ───────────────────────────────────────────────────────────────
  function attachDropZone(zone, path) {
    zone.addEventListener("dragover", e => { e.preventDefault(); e.stopPropagation(); zone.classList.add("b-over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("b-over"));
    zone.addEventListener("drop", e => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove("b-over");
      let data;
      try { data = JSON.parse(e.dataTransfer.getData("text/plain")); } catch (_) { return; }
      // Insert index: before the step element under the cursor, else at end
      const after = [...zone.children].filter(c => c.classList.contains("b-step"));
      let idx = after.length;
      for (let k = 0; k < after.length; k++) {
        const r = after[k].getBoundingClientRect();
        if (e.clientY < r.top + r.height / 2) { idx = k; break; }
      }
      if (data.src === "palette") insertStep(newStep(data.action), path, idx);
      else if (data.src === "seq") moveStep(data.path, data.index, path, idx);
    });
  }

  // ── Save / load / run ──────────────────────────────────────────────────────
  function serialize() {
    return {
      name: root.querySelector(".b-name").value || "unnamed",
      data_dir: kind === "echem" ? (root.querySelector(".b-datadir").value || null) : null,
      steps: model.steps,
    };
  }

  async function refreshSaved() {
    try {
      const r = await api("GET", `/sequences/list?kind=${kind}`);
      const sel = root.querySelector(".b-saved");
      const prev = sel.value;
      sel.innerHTML = `<option value="">— saved sequences —</option>` +
        r.names.map(n => `<option>${n}</option>`).join("");
      sel.value = prev;
    } catch (e) { /* ignore */ }
  }
  refreshSaved();

  bindBusy(root.querySelector(".b-save"), async () => {
    const seq = serialize();
    if (!root.querySelector(".b-name").value) throw new Error("Give the sequence a name first");
    const r = await api("POST", "/sequences/save", { kind, name: seq.name, sequence: seq });
    toast(`Saved '${r.name}'`, "ok");
    refreshSaved();
  });

  bindBusy(root.querySelector(".b-load"), async () => {
    const name = root.querySelector(".b-saved").value;
    if (!name) throw new Error("Pick a saved sequence");
    const r = await api("GET", `/sequences/load?kind=${kind}&name=${encodeURIComponent(name)}`);
    model.steps = r.sequence.steps || [];
    root.querySelector(".b-name").value = r.sequence.name || name;
    if (kind === "echem")
      root.querySelector(".b-datadir").value = r.sequence.data_dir || "";
    render();
    toast(`Loaded '${name}'`, "ok");
  });

  root.querySelector(".b-delete").addEventListener("click", () => {
    const name = root.querySelector(".b-saved").value;
    if (!name) return toast("Pick a saved sequence", "err");
    confirmAction(`Delete saved sequence '${name}'?`, async () => {
      try {
        await api("DELETE", `/sequences/${kind}/${encodeURIComponent(name)}`);
        toast(`Deleted '${name}'`, "ok");
        refreshSaved();
      } catch (e) { toast(e.message, "err"); }
    });
  });

  root.querySelector(".b-run").addEventListener("click", () => {
    const seq = serialize();
    if (!seq.steps.length) return toast("Sequence is empty", "err");
    confirmAction(
      `Run sequence '${seq.name}' (${seq.steps.length} top-level steps)? ` +
      `Manual control is locked while it runs.`, async () => {
        try {
          await api("POST", "/sequences/run", { kind, sequence: seq });
          toast("Sequence started", "ok");
          startStatusPoll();
        } catch (e) { toast(e.message, "err"); }
      });
  });

  bindBusy(root.querySelector(".b-abort"), async () => {
    await api("POST", "/sequences/abort");
    toast("Sequence abort requested (stops after current step)", "ok");
  });

  // ── Analysis reports ────────────────────────────────────────────────────────
  let lastReportShown = null;

  async function refreshReports() {
    try {
      const r = await api("GET", "/sequences/reports");
      const sel = root.querySelector(".b-reports");
      const prev = sel.value;
      sel.innerHTML = `<option value="">— sequence reports —</option>` +
        r.reports.map(x =>
          `<option value="${x.run_id}">${x.sequence || "unnamed"} — ${x.run_id} (${x.n_measurements} meas.)</option>`
        ).join("");
      sel.value = prev;
    } catch (e) { /* ignore */ }
  }
  refreshReports();

  bindBusy(root.querySelector(".b-report-show"), async () => {
    const id = root.querySelector(".b-reports").value;
    if (!id) throw new Error("Pick a report first");
    await showReport(id);
  });

  async function showReport(runId) {
    const rep = await api("GET", `/sequences/report/${encodeURIComponent(runId)}`);
    lastReportShown = runId;
    renderReport(rep);
  }

  function renderReport(rep) {
    const box = root.querySelector(".b-report");
    box.innerHTML = "";
    const head = document.createElement("p");
    head.className = "note";
    head.textContent = `'${rep.sequence || "unnamed"}' — run ${rep.sequence_run_id}, ` +
      `${rep.n_measurements} measurement(s), generated ${rep.generated_at}`;
    box.appendChild(head);
    for (const g of rep.groups || []) {
      const h = document.createElement("h4");
      h.textContent = g.technique;
      box.appendChild(h);

      const row = document.createElement("div");
      row.className = "row wrap";
      for (const p of g.plots || []) {
        const cell = document.createElement("div");
        cell.className = "b-report-plot";
        const t = document.createElement("div");
        t.className = "note";
        t.textContent = p.title;
        const pb = document.createElement("div");
        pb.className = "plot-box";
        cell.append(t, pb);
        row.appendChild(cell);
        const multi = (p.series || []).length > 1;
        linePlot(pb, (p.series[0] || {}).x || [],
          p.series.map(s => ({ xs: s.x, ys: s.y, label: multi ? s.label : null })),
          { xlabel: p.xlabel, ylabel: p.ylabel, logx: p.logx, logy: p.logy,
            equal: p.equal });
      }
      box.appendChild(row);

      // Metrics table: one row per measurement, union of metric keys as columns
      const keys = [];
      for (const m of g.measurements || [])
        for (const k of Object.keys(m.metrics || {}))
          if (!keys.includes(k)) keys.push(k);
      // Reference columns only when a non-default voltage reference was used
      const anyVs = (g.measurements || []).some(m => m.vs && m.vs !== "Ref");
      const wrap = document.createElement("div");
      wrap.className = "scroll-x";
      const tbl = document.createElement("table");
      tbl.innerHTML =
        `<tr><th>#</th><th>Run</th><th>Sample</th>` +
        (anyVs ? `<th>Voltages vs</th><th>Ref offset (V)</th>` : "") +
        `${keys.map(k => `<th>${k}</th>`).join("")}</tr>` +
        (g.measurements || []).map((m, i) =>
          `<tr><td>${i + 1}</td><td>${m.run_id || ""}${m.aborted ? " (aborted)" : ""}</td>` +
          `<td>${m.sample_id || ""}</td>` +
          (anyVs ? `<td>${m.vs || "Ref"}</td><td>${m.reference_v != null ? m.reference_v : ""}</td>` : "") +
          keys.map(k => `<td>${m.metrics && m.metrics[k] != null ? m.metrics[k] : ""}</td>`).join("") +
          `</tr>`).join("");
      wrap.appendChild(tbl);
      box.appendChild(wrap);
    }
  }

  // ── Status polling (only while running) ─────────────────────────────────────
  async function pollStatus() {
    let s;
    try { s = await api("GET", "/sequences/status"); } catch (e) { return; }
    const el = root.querySelector(".b-status");
    const bar = root.querySelector(".b-progress");
    if (s.running) {
      let eta = "";
      if (s.est_total_s && s.started_at) {
        const remaining = s.est_total_s - (Date.now() / 1000 - s.started_at);
        eta = remaining > 0 ? ` — ≈ ${fmtDur(remaining)} left` : " — overdue";
      }
      el.textContent = `Running '${s.name}': ${s.step || "starting…"} (${s.step_index}/${s.n_steps})${eta}`;
      bar.style.width = s.n_steps ? (100 * s.step_index / s.n_steps) + "%" : "0";
      bar.style.background = "#1565c0";
      if (!statusTimer) statusTimer = setInterval(pollStatus, 2000);
    } else {
      if (s.outcome) {
        el.textContent = `Last run: ${s.outcome}` + (s.error ? ` — ${String(s.error).split("\n")[0]}` : "");
        bar.style.width = s.outcome === "completed" ? "100%" : bar.style.width;
        bar.style.background = s.outcome === "completed" ? "#2e7d32" : "#c62828";
      } else {
        el.textContent = "";
      }
      // Auto-display the analysis report generated for the finished run
      if (s.report && s.report !== lastReportShown) {
        lastReportShown = s.report;
        showReport(s.report).catch(() => {});
        refreshReports();
      }
      stopStatusPoll();
    }
  }
  function startStatusPoll() {
    if (!statusTimer) statusTimer = setInterval(pollStatus, 2000);
    pollStatus();
  }
  function stopStatusPoll() {
    if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
  }
  pollStatus();   // resumes live updates if a sequence is already running
  render();

  return { pollStatus, startStatusPoll };
}
