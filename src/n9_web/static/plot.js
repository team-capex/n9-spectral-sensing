/* plot.js — tiny self-contained SVG plotting (no external libs).
   linePlot(el, xs, seriesArr, opts) — seriesArr: [{ys, label, color}]
   barPlot(el, labels, values, colors, opts)
*/
"use strict";

const PLOT_COLORS = ["#1565c0", "#c62828", "#2e7d32", "#f9a825", "#6a1b9a", "#00838f"];

function _extent(arr) {
  let lo = Infinity, hi = -Infinity;
  for (const v of arr) {
    if (v == null || !isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (lo === Infinity) { lo = 0; hi = 1; }
  if (lo === hi) { lo -= 0.5; hi += 0.5; }
  return [lo, hi];
}

function _fmt(v) {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 10000 || a < 0.001) return v.toExponential(1);
  if (a >= 100) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(4);
}

/* Ticks at "nice" round values (1/2/5 × 10^n). For log axes: integer decades
   when the range spans at least one, else nice ticks in log space.
   Returns { ticks: [...], fmt: v => label } with v in AXIS (transformed) space. */
function _axisTicks(t0, t1, isLog) {
  if (isLog) {
    const lo = Math.ceil(t0 - 1e-9), hi = Math.floor(t1 + 1e-9);
    if (hi - lo >= 1) {
      const stride = Math.max(1, Math.ceil((hi - lo + 1) / 6));
      const ticks = [];
      for (let e = lo; e <= hi; e += stride) ticks.push(e);
      return { ticks, fmt: v => _fmt(Math.pow(10, v)) };
    }
  }
  const span = (t1 - t0) || 1;
  const raw = span / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw))));
  const norm = raw / mag;
  // √-based thresholds (as in d3) keep 4-7 ticks for any span
  const step = (norm >= 7.07 ? 10 : norm >= 3.16 ? 5 : norm >= 1.41 ? 2 : 1) * mag;
  const ticks = [];
  for (let v = Math.ceil(t0 / step) * step; v <= t1 + step * 1e-6; v += step)
    ticks.push(v);
  const dec = Math.max(0, Math.min(6, -Math.floor(Math.log10(step) + 1e-9)));
  const fmt = isLog
    ? (v => _fmt(Math.pow(10, v)))
    : (v => {
        if (Math.abs(v) < step * 1e-6) return "0";
        const a = Math.abs(v);
        if (a >= 1e5 || a < 1e-4) return v.toExponential(1);
        return v.toFixed(dec);
      });
  return { ticks, fmt };
}

function linePlot(el, xs, seriesArr, opts = {}) {
  const W = opts.width || 560, H = opts.height || 300;
  const m = { l: 62, r: 12, t: 12, b: 42 };
  const logx = !!opts.logx, logy = !!opts.logy;

  const tx = v => (logx ? Math.log10(Math.max(v, 1e-12)) : v);
  const ty = v => (logy ? Math.log10(Math.max(v, 1e-12)) : v);

  // Each series may carry its own x array (s.xs); otherwise the shared xs is used.
  const allX = [], allY = [];
  for (const s of seriesArr) {
    for (const v of (s.xs || xs)) if (v != null) allX.push(tx(v));
    for (const v of s.ys) if (v != null) allY.push(ty(v));
  }
  let [x0, x1] = _extent(allX);
  let [y0, y1] = _extent(allY);

  // Equal scale (units per pixel identical on both axes) — e.g. Nyquist
  // plots, where a semicircle must look like a semicircle.
  if (opts.equal && !logx && !logy) {
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const scale = Math.max((x1 - x0) / pw, (y1 - y0) / ph);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    x0 = cx - scale * pw / 2; x1 = cx + scale * pw / 2;
    y0 = cy - scale * ph / 2; y1 = cy + scale * ph / 2;
  }

  const X = v => m.l + ((tx(v) - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = v => H - m.b - ((ty(v) - y0) / (y1 - y0)) * (H - m.t - m.b);

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  svg += `<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="#fafcfe" stroke="#dde3ea"/>`;

  // Grid + ticks at nice round values (decades on log axes)
  const xa = _axisTicks(x0, x1, logx);
  const ya = _axisTicks(y0, y1, logy);
  for (const t of xa.ticks) {
    const px = m.l + ((t - x0) / (x1 - x0)) * (W - m.l - m.r);
    svg += `<line x1="${px.toFixed(1)}" y1="${m.t}" x2="${px.toFixed(1)}" y2="${H - m.b}" stroke="#eef2f6"/>`;
    svg += `<text x="${px.toFixed(1)}" y="${H - m.b + 16}" font-size="10" text-anchor="middle" fill="#607d8b">${xa.fmt(t)}</text>`;
  }
  for (const t of ya.ticks) {
    const py = H - m.b - ((t - y0) / (y1 - y0)) * (H - m.t - m.b);
    svg += `<line x1="${m.l}" y1="${py.toFixed(1)}" x2="${W - m.r}" y2="${py.toFixed(1)}" stroke="#eef2f6"/>`;
    svg += `<text x="${m.l - 6}" y="${(py + 3).toFixed(1)}" font-size="10" text-anchor="end" fill="#607d8b">${ya.fmt(t)}</text>`;
  }

  seriesArr.forEach((s, si) => {
    const color = s.color || PLOT_COLORS[si % PLOT_COLORS.length];
    const sx = s.xs || xs;
    let d = "", pen = false;
    for (let i = 0; i < sx.length; i++) {
      const yv = s.ys[i];
      if (yv == null || !isFinite(yv) || sx[i] == null) { pen = false; continue; }
      const px = X(sx[i]).toFixed(1), py = Y(yv).toFixed(1);
      d += (pen ? "L" : "M") + px + " " + py;
      pen = true;
    }
    svg += `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"/>`;
    if (s.label && si < 12) {
      svg += `<rect x="${W - m.r - 130}" y="${m.t + 6 + si * 16}" width="10" height="3" fill="${color}"/>`;
      svg += `<text x="${W - m.r - 115}" y="${m.t + 11 + si * 16}" font-size="10" fill="#455a64">${s.label}</text>`;
    }
  });

  if (opts.xlabel) svg += `<text x="${(m.l + W - m.r) / 2}" y="${H - 6}" font-size="11" text-anchor="middle" fill="#455a64">${opts.xlabel}</text>`;
  if (opts.ylabel) svg += `<text x="14" y="${(m.t + H - m.b) / 2}" font-size="11" text-anchor="middle" fill="#455a64" transform="rotate(-90 14 ${(m.t + H - m.b) / 2})">${opts.ylabel}</text>`;
  svg += "</svg>";
  el.innerHTML = svg;
}

function barPlot(el, labels, values, colors, opts = {}) {
  const W = opts.width || 560, H = opts.height || 240;
  const m = { l: 52, r: 10, t: 10, b: 40 };
  const [ , vmaxRaw] = _extent(values);
  const vmax = opts.max != null ? opts.max : vmaxRaw;
  const n = labels.length;
  const bw = (W - m.l - m.r) / n;

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  svg += `<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="#fafcfe" stroke="#dde3ea"/>`;
  for (let i = 0; i <= 4; i++) {
    const v = (vmax * i) / 4;
    const py = H - m.b - (i / 4) * (H - m.t - m.b);
    svg += `<line x1="${m.l}" y1="${py}" x2="${W - m.r}" y2="${py}" stroke="#eef2f6"/>`;
    svg += `<text x="${m.l - 6}" y="${py + 3}" font-size="10" text-anchor="end" fill="#607d8b">${_fmt(v)}</text>`;
  }
  values.forEach((v, i) => {
    const h = vmax > 0 ? (Math.max(v, 0) / vmax) * (H - m.t - m.b) : 0;
    const x = m.l + i * bw + bw * 0.15;
    svg += `<rect x="${x.toFixed(1)}" y="${(H - m.b - h).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${h.toFixed(1)}" fill="${colors ? colors[i] : PLOT_COLORS[0]}" stroke="#607d8b" stroke-width="0.4"/>`;
    svg += `<text x="${(m.l + i * bw + bw / 2).toFixed(1)}" y="${H - m.b + 14}" font-size="9.5" text-anchor="middle" fill="#607d8b">${labels[i]}</text>`;
  });
  if (opts.xlabel) svg += `<text x="${(m.l + W - m.r) / 2}" y="${H - 4}" font-size="11" text-anchor="middle" fill="#455a64">${opts.xlabel}</text>`;
  svg += "</svg>";
  el.innerHTML = svg;
}

function sparkline(el, ys, opts = {}) {
  const W = opts.width || 220, H = opts.height || 44;
  const [y0, y1] = _extent(ys);
  let d = "", pen = false;
  ys.forEach((v, i) => {
    if (v == null || !isFinite(v)) { pen = false; return; }
    const px = (i / Math.max(ys.length - 1, 1)) * (W - 4) + 2;
    const py = H - 3 - ((v - y0) / (y1 - y0)) * (H - 6);
    d += (pen ? "L" : "M") + px.toFixed(1) + " " + py.toFixed(1);
    pen = true;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">` +
    `<path d="${d}" fill="none" stroke="#1565c0" stroke-width="1.4"/></svg>`;
}
