const D = JSON.parse(document.getElementById("payload").textContent);
const NS = "http://www.w3.org/2000/svg";
const ORDER = ["Rice", "Betts", "Jaquez", "Leger-Walker", "Kneepkens", "Dugalic"];
const byLast = Object.fromEntries(D.players.map(p => [p.last, p]));
const P = ORDER.map(l => byLast[l]);

/* ── dom helpers ─────────────────────────────────────────────────────── */
const el = (t, a = {}, kids = []) => {
  const n = document.createElementNS(NS, t);
  for (const k in a) if (a[k] != null) n.setAttribute(k, a[k]);
  (Array.isArray(kids) ? kids : [kids]).forEach(c =>
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
  return n;
};
const svg = (w, h) => el("svg", {
  viewBox: `0 0 ${w} ${h}`, width: w, height: h,
  role: "img", preserveAspectRatio: "xMinYMin meet"
});
const txt = (x, y, s, cls, extra = {}) =>
  el("text", { x, y, class: cls, ...extra }, String(s));
const fmt = (v, n = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(n);

/* Bars are square where they meet the baseline and rounded only at the data
   end, so the mark stays anchored to zero instead of floating off it. */
const hbar = (x0, x1, y, h, r = 3) => {
  const xs = Math.min(x0, x1), xe = Math.max(x0, x1);
  const rr = Math.max(0, Math.min(r, xe - xs, h / 2));
  return x1 >= x0
    ? `M${xs},${y} H${xe - rr} Q${xe},${y} ${xe},${y + rr} V${y + h - rr} Q${xe},${y + h} ${xe - rr},${y + h} H${xs} Z`
    : `M${xe},${y} H${xs + rr} Q${xs},${y} ${xs},${y + rr} V${y + h - rr} Q${xs},${y + h} ${xs + rr},${y + h} H${xe} Z`;
};
const vbar = (x, w, yTop, yBase, r = 4) => {
  const rr = Math.max(0, Math.min(r, w / 2, yBase - yTop));
  return `M${x},${yBase} V${yTop + rr} Q${x},${yTop} ${x + rr},${yTop} H${x + w - rr} Q${x + w},${yTop} ${x + w},${yTop + rr} V${yBase} Z`;
};

/* ── tooltip ─────────────────────────────────────────────────────────── */
const tip = document.getElementById("tip");
function hover(node, html) {
  const show = e => {
    tip.innerHTML = html;
    tip.classList.add("on");
    const r = tip.getBoundingClientRect();
    let x = e.clientX + 14, y = e.clientY - r.height - 10;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (y < 8) y = e.clientY + 18;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  };
  node.addEventListener("pointerenter", show);
  node.addEventListener("pointermove", show);
  node.addEventListener("pointerleave", () => tip.classList.remove("on"));
  node.setAttribute("tabindex", "0");
  node.addEventListener("focus", () => {
    const b = node.getBoundingClientRect();
    show({ clientX: b.left + b.width / 2, clientY: b.top });
  });
  node.addEventListener("blur", () => tip.classList.remove("on"));
}

/* ── 1. minutes small multiples ──────────────────────────────────────── */
(function minutes() {
  const host = document.getElementById("sm-minutes");
  const MONTHS = ["05", "06", "07", "08"];
  const LBL = { "05": "May", "06": "Jun", "07": "Jul", "08": "Aug" };
  const W = 250, H = 118, m = { t: 10, r: 14, b: 20, l: 26 };
  const maxY = 32;

  P.forEach(p => {
    const rows = MONTHS.map(mo => D.monthly.find(r => r.player === p.name && r.month === mo));
    const box = document.createElement("div");
    box.className = "sm";
    box.innerHTML = `<h4>${p.last}</h4><div class="meta">${p.team} · ${p.gp} games · ${p.minutes} min</div>`;

    const s = svg(W, H);
    const x = i => m.l + i * ((W - m.l - m.r) / (MONTHS.length - 1));
    const y = v => m.t + (1 - v / maxY) * (H - m.t - m.b);

    [0, 16, 32].forEach(v => {
      s.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "gridline" }));
      s.appendChild(txt(m.l - 6, y(v) + 4, v, "tick", { "text-anchor": "end" }));
    });
    MONTHS.forEach((mo, i) => s.appendChild(
      txt(x(i), H - 5, LBL[mo], "tick", { "text-anchor": "middle" })));

    const pts = rows.map((r, i) => (r ? [x(i), y(r.mpg), r] : null)).filter(Boolean);
    s.appendChild(el("polyline", {
      points: pts.map(q => `${q[0]},${q[1]}`).join(" "),
      fill: "none", stroke: "var(--accent)", "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round"
    }));
    pts.forEach(([cx, cy, r]) => {
      const g = el("g");
      // radius carries games played, so a one-appearance month reads as thin
      const rad = 3 + Math.min(r.games, 11) / 11 * 3.5;
      g.appendChild(el("circle", { cx, cy, r: rad, fill: "var(--card)", stroke: "var(--accent)", "stroke-width": 2 }));
      hover(g, `<strong>${p.last} · ${LBL[r.month]}</strong><br>${r.mpg} min/game<br>${r.games} game${r.games === 1 ? "" : "s"}`);
      s.appendChild(g);
    });
    box.appendChild(s);
    host.appendChild(box);
  });
})();

/* ── 2. shot quality vs shot making ──────────────────────────────────── */
(function scatter() {
  const W = 1000, H = 520, m = { t: 22, r: 24, b: 52, l: 62 };
  const xs = D.league_scatter.map(d => d.x).concat(P.map(p => p.sq));
  const ys = D.league_scatter.map(d => d.y).concat(P.map(p => p.making));
  const pad = (a, f) => { const lo = Math.min(...a), hi = Math.max(...a); const s = (hi - lo) * f; return [lo - s, hi + s]; };
  const [x0, x1] = pad(xs, .06), [y0, y1] = pad(ys, .08);
  const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const med = a => { const s = [...a].sort((p, q) => p - q); return s[Math.floor(s.length / 2)]; };
  const mx = med(D.league_scatter.map(d => d.x)), my = med(D.league_scatter.map(d => d.y));

  const s = svg(W, H);
  for (let v = 0.40; v <= 0.62; v += 0.04) {
    s.appendChild(el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: "gridline" }));
    s.appendChild(txt(X(v), H - m.b + 18, v.toFixed(2), "tick", { "text-anchor": "middle" }));
  }
  for (let v = -0.12; v <= 0.13; v += 0.04) {
    s.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: "gridline" }));
    s.appendChild(txt(m.l - 8, Y(v) + 4, fmt(v, 2), "tick", { "text-anchor": "end" }));
  }
  s.appendChild(el("line", { x1: X(mx), x2: X(mx), y1: m.t, y2: H - m.b, class: "zero", "stroke-dasharray": "4 4" }));
  s.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: Y(my), y2: Y(my), class: "zero", "stroke-dasharray": "4 4" }));
  s.appendChild(txt(m.l + 8, m.t + 16, "worse looks, better conversion", "slab", { fill: "var(--ink-faint)" }));
  s.appendChild(txt(W - m.r - 8, H - m.b - 8, "better looks, worse conversion", "slab",
    { "text-anchor": "end", fill: "var(--ink-faint)" }));
  s.appendChild(txt(W / 2, H - 8, "Expected points per shot  →", "slab", { "text-anchor": "middle" }));
  s.appendChild(txt(-H / 2, 16, "Conversion over expectation  →", "slab",
    { "text-anchor": "middle", transform: "rotate(-90)" }));

  D.league_scatter.forEach(d =>
    s.appendChild(el("circle", { cx: X(d.x), cy: Y(d.y), r: 4, fill: "var(--pool)", opacity: .55 })));

  const place = { Rice: [10, -12], Betts: [10, -12], Jaquez: [10, 18], "Leger-Walker": [-10, -12], Kneepkens: [10, 18], Dugalic: [10, 18] };
  P.forEach(p => {
    const g = el("g");
    g.appendChild(el("circle", {
      cx: X(p.sq), cy: Y(p.making), r: 8,
      fill: "var(--accent)", stroke: "var(--card)", "stroke-width": 2
    }));
    const [dx, dy] = place[p.last] || [10, -10];
    g.appendChild(txt(X(p.sq) + dx, Y(p.making) + dy, p.last, "slab", {
      "text-anchor": dx < 0 ? "end" : "start", fill: "var(--ink)", "font-weight": 600
    }));
    hover(g, `<strong>${p.name}</strong><br>shot quality ${p.sq.toFixed(3)} (p${p.pct.sq ?? "—"})<br>` +
      `making ${fmt(p.making, 3)} (p${p.pct.making ?? "—"})<br>TS ${p.ts.toFixed(3)}`);
    s.appendChild(g);
  });
  document.getElementById("fig-scatter").appendChild(s);
})();

/* ── 3. offensive / defensive RAPM ───────────────────────────────────── */
(function rapm() {
  const W = 1000, H = 330, m = { t: 18, r: 26, b: 40, l: 128 };
  const lim = 4.4, band = (H - m.t - m.b) / P.length;
  const X = v => m.l + (v + lim) / (2 * lim) * (W - m.l - m.r);
  const s = svg(W, H);

  for (let v = -4; v <= 4; v += 2) {
    s.appendChild(el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: "gridline" }));
    s.appendChild(txt(X(v), H - m.b + 18, fmt(v, 0), "tick", { "text-anchor": "middle" }));
  }
  s.appendChild(el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, class: "zero" }));
  s.appendChild(txt(W / 2, H - 6, "points per 100 possessions vs league average", "slab", { "text-anchor": "middle" }));

  P.forEach((p, i) => {
    const top = m.t + i * band;
    s.appendChild(txt(m.l - 12, top + band / 2 + 4, p.last, "slab",
      { "text-anchor": "end", fill: "var(--ink)", "font-weight": 600 }));
    [["o_rapm", "var(--accent)", "Offence"], ["d_rapm", "var(--counter)", "Defence"]]
      .forEach(([k, col, lab], j) => {
        const v = p[k], h = 13, y = top + band / 2 - h - 2 + j * (h + 2);
        const g = el("g");
        g.appendChild(el("path", { d: hbar(X(0), X(v), y, h), fill: col }));
        hover(g, `<strong>${p.name}</strong><br>${lab} ${fmt(v, 2)} per 100<br>${p.poss} possessions`);
        s.appendChild(g);
      });
  });
  document.getElementById("fig-rapm").appendChild(s);

  document.getElementById("tbl-rapm").innerHTML =
    `<thead><tr><th>Player</th><th>Team</th><th>Poss</th><th>Offence</th><th>Defence</th>
     <th>Net</th><th>Pctile</th><th>WAA</th></tr></thead><tbody>` +
    P.map(p => `<tr><td class="name">${p.name}</td><td>${p.team}</td><td>${p.poss.toLocaleString()}</td>
      <td>${fmt(p.o_rapm, 2)}</td><td>${fmt(p.d_rapm, 2)}</td><td>${fmt(p.rapm, 2)}</td>
      <td>${p.rapm_pctile}</td><td>${fmt(p.waa, 2)}</td></tr>`).join("") + "</tbody>";
})();

/* ── 4. Rice return minutes ──────────────────────────────────────────── */
(function rice() {
  const g = D.rice.minutes, W = 1000, H = 300, m = { t: 20, r: 24, b: 46, l: 46 };
  const bw = (W - m.l - m.r) / g.length, maxY = 34;
  const Y = v => m.t + (1 - v / maxY) * (H - m.t - m.b);
  const s = svg(W, H);

  s.appendChild(el("rect", {
    x: m.l, y: m.t, width: bw * 5, height: H - m.t - m.b,
    fill: "var(--shade)"
  }));
  s.appendChild(txt(m.l + bw * 2.5, m.t + 16, "five-game re-integration", "slab",
    { "text-anchor": "middle", fill: "var(--ink-soft)" }));

  [0, 10, 20, 30].forEach(v => {
    s.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: "gridline" }));
    s.appendChild(txt(m.l - 8, Y(v) + 4, v, "tick", { "text-anchor": "end" }));
  });

  const barW = Math.min(46, bw - 10);
  g.forEach((d, i) => {
    const x = m.l + i * bw + (bw - barW) / 2, w = barW;
    const grp = el("g");
    grp.appendChild(el("path", {
      d: vbar(x, w, Y(d.min), Y(0)),
      fill: i < 5 ? "var(--counter)" : "var(--accent)"
    }));
    grp.appendChild(txt(x + w / 2, Y(d.min) - 7, d.min.toFixed(1), "tick",
      { "text-anchor": "middle", fill: "var(--ink-mid)" }));
    grp.appendChild(txt(x + w / 2, H - m.b + 18, "g" + d.g, "tick", { "text-anchor": "middle" }));
    hover(grp, `<strong>Game ${d.g}</strong><br>${d.min.toFixed(1)} minutes<br>` +
      (i < 5 ? "restriction window" : "unrestricted"));
    s.appendChild(grp);
  });
  s.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), class: "axis" }));
  document.getElementById("fig-rice").appendChild(s);

  const b = D.rice.blocks;
  document.getElementById("tbl-rice").innerHTML =
    `<thead><tr><th>Window</th><th>Games</th><th>Min/game</th><th>Pts/75</th>
      <th>TS%</th><th>Rim acc.</th><th>TOV/75</th></tr></thead><tbody>` +
    b.map(r => `<tr><td class="name">${r.block}</td><td>${r.games}</td><td>${r.mpg}</td>
      <td>${r.pts75}</td><td>${r.ts.toFixed(3)}</td><td>${(r.rim_acc * 100).toFixed(0)}%</td>
      <td>${r.tov75}</td></tr>`).join("") + "</tbody>";
})();

/* ── 5. duo dumbbell ─────────────────────────────────────────────────── */
(function duos() {
  const d = D.duos.map(r => ({ ...r, gap: r.together - r.best_other_net }));
  const W = 1000, H = 320, m = { t: 30, r: 132, b: 46, l: 190 };
  const lim = 24, band = (H - m.t - m.b) / d.length;
  const X = v => m.l + (v + lim) / (2 * lim) * (W - m.l - m.r);
  const s = svg(W, H);

  s.appendChild(txt(W - m.r + 10, m.t - 10, "gap", "tick",
    { "text-anchor": "start", fill: "var(--ink-faint)" }));

  for (let v = -20; v <= 20; v += 10) {
    s.appendChild(el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: "gridline" }));
    s.appendChild(txt(X(v), H - m.b + 18, fmt(v, 0), "tick", { "text-anchor": "middle" }));
  }
  s.appendChild(el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, class: "zero" }));

  d.forEach((r, i) => {
    const y = m.t + i * band + band / 2;
    s.appendChild(txt(m.l - 12, y + 4, r.pair, "slab",
      { "text-anchor": "end", fill: "var(--ink)", "font-weight": 600 }));
    s.appendChild(el("line", {
      x1: X(r.best_other_net), x2: X(r.together), y1: y, y2: y,
      stroke: "var(--rule-firm)", "stroke-width": 2
    }));
    const a = el("g");
    a.appendChild(el("circle", { cx: X(r.best_other_net), cy: y, r: 6, fill: "var(--pool)", stroke: "var(--card)", "stroke-width": 2 }));
    hover(a, `<strong>${r.pair}</strong><br>best alternative (${r.best_other} on)<br>${fmt(r.best_other_net, 1)} per 100`);
    s.appendChild(a);
    const b = el("g");
    b.appendChild(el("circle", { cx: X(r.together), cy: y, r: 8, fill: "var(--accent)", stroke: "var(--card)", "stroke-width": 2 }));
    hover(b, `<strong>${r.pair} together</strong><br>${fmt(r.together, 1)} per 100<br>${r.poss} possessions`);
    s.appendChild(b);
    const clears = Math.abs(r.gap) >= 15;
    // when the two states nearly coincide the markers overlap, so clear the
    // label past both of them instead of tucking it against the near one
    const tight = Math.abs(X(r.together) - X(r.best_other_net)) < 26;
    const left = tight ? true : r.together < r.best_other_net;
    const off = tight ? Math.abs(X(r.together) - X(r.best_other_net)) + 20 : 14;
    s.appendChild(txt(X(r.together) + (left ? -off : off), y + 4,
      fmt(r.together, 1), "tick",
      { "text-anchor": left ? "end" : "start", fill: "var(--ink-mid)" }));
    s.appendChild(txt(W - m.r + 10, y + 4, fmt(r.gap, 1), "tick", {
      "text-anchor": "start", fill: clears ? "var(--ink)" : "var(--ink-faint)",
      "font-weight": clears ? 600 : 400
    }));
    s.appendChild(txt(W - m.r + 58, y + 4, clears ? "clears" : "noise", "tick", {
      "text-anchor": "start", fill: clears ? "var(--accent)" : "var(--ink-faint)"
    }));
  });
  s.appendChild(txt((m.l + W - m.r) / 2, H - 6, "net rating per 100 possessions", "slab", { "text-anchor": "middle" }));
  document.getElementById("fig-duo").appendChild(s);
})();

/* ── 6. on/off swing ─────────────────────────────────────────────────── */
(function swing() {
  const W = 1000, H = 250, m = { t: 34, r: 30, b: 44, l: 128 };
  const lim = 24, band = (H - m.t - m.b) / P.length;
  const X = v => m.l + (v + lim) / (2 * lim) * (W - m.l - m.r);
  const s = svg(W, H);

  D.league_swing.forEach(v => {
    if (v < -lim || v > lim) return;
    s.appendChild(el("line", {
      x1: X(v), x2: X(v), y1: m.t - 22, y2: m.t - 6,
      stroke: "var(--pool)", "stroke-width": 1.5, opacity: .5
    }));
  });
  s.appendChild(txt(m.l - 12, m.t - 11, "league", "tick", { "text-anchor": "end" }));

  for (let v = -20; v <= 20; v += 10) {
    s.appendChild(el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: "gridline" }));
    s.appendChild(txt(X(v), H - m.b + 18, fmt(v, 0), "tick", { "text-anchor": "middle" }));
  }
  s.appendChild(el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, class: "zero" }));

  P.forEach((p, i) => {
    const y = m.t + i * band + band / 2;
    s.appendChild(txt(m.l - 12, y + 4, p.last, "slab",
      { "text-anchor": "end", fill: "var(--ink)", "font-weight": 600 }));
    const g = el("g");
    g.appendChild(el("path", { d: hbar(X(0), X(p.swing), y - 6, 12), fill: "var(--accent)" }));
    hover(g, `<strong>${p.name}</strong><br>on ${fmt(p.on_net, 1)} · off ${fmt(p.off_net, 1)}<br>` +
      `swing ${fmt(p.swing, 1)} per 100<br>${p.on_poss} on-court possessions`);
    s.appendChild(g);
    s.appendChild(txt(X(p.swing) + (p.swing < 0 ? -10 : 10), y + 4, fmt(p.swing, 1), "tick",
      { "text-anchor": p.swing < 0 ? "end" : "start", fill: "var(--ink-mid)" }));
  });
  s.appendChild(txt(W / 2, H - 6, "on-court minus off-court net rating, per 100", "slab", { "text-anchor": "middle" }));
  document.getElementById("fig-swing").appendChild(s);
})();

/* ── 7. cards + full table ───────────────────────────────────────────── */
(function cards() {
  const READ = {
    Rice: "The only one of the six whose team was clearly better with her on the floor, and the only positive wins-above-average. Sixteen games lost to injury and a five-game ramp back keep the sample thin.",
    Betts: "The widest two-way split in the cohort: best defensive impact of the six, near-worst offensive. Zero three-point attempts all season. Her efficiency and foul rate both improved every month.",
    Jaquez: "Best shot quality of the six and the worst conversion against it. Minutes fell every month, from 28.3 in May to 11.8 in August.",
    "Leger-Walker": "Played the most possessions of the six, which magnifies a negative rate into the cohort's lowest wins-above-average. Genuine passing volume at 5.6 assists per 75.",
    Kneepkens: "Never cleared the league's 250-minute reference threshold, so most percentiles are unavailable. The highest three-point share of the six on the smallest sample.",
    Dugalic: "The clearest negative in the cohort on both ends, and the other half of Washington's problem pairing. Minutes collapsed to 3.3 a game by August."
  };
  const METRICS = [
    ["Minutes", "mpg"], ["Scoring", "pts75"], ["True shooting", "ts"],
    ["Shot quality", "sq"], ["Shot-making", "making"], ["Playmaking", "ast75"], ["Stocks", "stocks75"]
  ];
  const host = document.getElementById("cards");
  P.forEach(p => {
    const c = document.createElement("div");
    c.className = "card";
    const bars = METRICS.map(([lab, k]) => {
      const v = p.pct[k];
      return `<div class="bar"><span>${lab}</span>
        <span class="track">${v == null ? "" : `<span class="fill" style="width:${v}%"></span>`}</span>
        <span class="v">${v == null ? "—" : v}</span></div>`;
    }).join("");
    c.innerHTML =
      `<div class="top"><h3>${p.name}</h3><span class="team">${p.team}</span></div>
       <div class="line">${p.gp} games · ${p.mpg} min · ${p.minutes} total</div>
       <p>${READ[p.last]}</p>
       <div class="bars">${bars}</div>
       <div class="line" style="margin-top:.2rem">league percentile, 250+ min pool</div>`;
    host.appendChild(c);
  });

  document.getElementById("tbl-all").innerHTML =
    `<thead><tr><th>Player</th><th>Tm</th><th>G</th><th>Min</th><th>MPG</th><th>Usage</th>
      <th>Pts/75</th><th>TS%</th><th>SQ</th><th>Making</th><th>Ast/75</th><th>TOV/75</th>
      <th>3PA sh.</th><th>RAPM</th><th>WAA</th><th>On/off</th></tr></thead><tbody>` +
    P.map(p => `<tr><td class="name">${p.name}</td><td>${p.team}</td><td>${p.gp}</td>
      <td>${p.minutes}</td><td>${p.mpg}</td><td>${p.usage}</td><td>${p.pts75}</td>
      <td>${p.ts.toFixed(3)}</td><td>${p.sq.toFixed(3)}</td><td>${fmt(p.making, 3)}</td>
      <td>${p.ast75}</td><td>${p.tov75}</td><td>${p.three_share.toFixed(2)}</td>
      <td>${fmt(p.rapm, 2)}</td><td>${fmt(p.waa, 2)}</td><td>${fmt(p.swing, 1)}</td></tr>`).join("") +
    "</tbody>";
})();

/* ── 8. inline figures ───────────────────────────────────────────────── */
(function fill() {
  const c = D.coverage, r = D.reliability;
  const set = (id, v) => { const n = document.getElementById(id); if (n) n.textContent = v; };
  set("cv-games", c.games); set("cv-games-2", c.games);
  set("cv-date", c.through); set("cv-date-2", c.through);
  set("cv-poss", c.possessions.toLocaleString()); set("cv-poss-2", c.possessions.toLocaleString());
  set("cv-pool", c.league_pool); set("cv-pool-2", c.league_pool);
  set("rel-1", r.r200.toFixed(2)); set("rel-2", r.r200.toFixed(2));
  set("ext-n", r.ext_matched); set("ext-hit", r.ext_in_band);
  set("ext-se", r.ext_se.toFixed(2)); set("ext-span", r.ext_span.toFixed(2));
})();
