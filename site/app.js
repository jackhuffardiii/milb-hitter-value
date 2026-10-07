/* MiLB Hitter Value: vanilla JS, no dependencies. Pages: index, player, method (body[data-page]). */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  /* ---------- helpers ---------- */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (attrs[k] == null || attrs[k] === false) continue;
      if (k === "class") el.className = attrs[k]; else if (k === "text") el.textContent = attrs[k]; else el.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(el, x); });
    else el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  function s(tag, attrs) {
    var el = document.createElementNS(NS, tag);
    for (var k in attrs) if (k === "text") el.textContent = attrs[k]; else el.setAttribute(k, attrs[k]);
    for (var i = 2; i < arguments.length; i++) if (arguments[i]) el.appendChild(arguments[i]);
    return el;
  }
  var MINUS = "−";
  function sgn(x, str) { return x < 0 ? MINUS + str.replace("-", "") : str; }
  function num(x, d) { return x == null ? "n/a" : sgn(x, x.toFixed(d == null ? 1 : d)); }
  function rate(x) { return x == null ? "n/a" : sgn(x, x.toFixed(3)).replace(/^(−?)0\./, "$1."); }
  function pct(x, d) { return x == null ? "n/a" : (x * 100).toFixed(d == null ? 1 : d) + "%"; }
  function usd(x, d) { return x == null ? "n/a" : (x < 0 ? MINUS : "") + "$" + Math.abs(x).toFixed(d == null ? 1 : d) + "M"; }
  function load(path) {
    return fetch(path).then(function (r) { if (!r.ok) throw new Error(path + " returned " + r.status); return r.json(); });
  }
  function fail(msg) {
    var m = document.getElementById("main");
    m.appendChild(h("div", { class: "err", role: "alert" }, h("b", { text: "Could not load data. " }), msg,
      " Serve the site folder over HTTP (for example python3 -m http.server) rather than opening the file directly."));
  }
  var LEVELS = { aaa: "AAA", aa: "AA", "a+": "High-A", a: "Low-A", "a-": "Short-A", rk: "Rookie" };
  var LV = function (x) { return LEVELS[x] || x; };
  var POSS = { C: "C", "1B": "1B", "2B": "2B", "3B": "3B", SS: "SS", LF: "LF", CF: "CF", RF: "RF", DH: "DH" };

  function table(headers, rows, opts) {
    opts = opts || {};
    var thead = h("tr", null, headers.map(function (x) {
      var o = typeof x === "string" ? { t: x } : x;
      return h("th", { scope: "col", class: o.n ? "n" : null, title: o.title }, o.t);
    }));
    var body = rows.map(function (r) {
      return h("tr", null, r.map(function (c, i) {
        var o = c && typeof c === "object" && !(c instanceof Node) && !Array.isArray(c) ? c : { v: c };
        var hd = headers[i]; var isN = (typeof hd === "object" && hd.n);
        return h(i === 0 && opts.rowHeader ? "th" : "td", { scope: i === 0 && opts.rowHeader ? "row" : null, class: (isN ? "n" : "") + (o.cls ? " " + o.cls : "") }, o.v);
      }));
    });
    return h("div", { class: "tbl-wrap", role: "region", tabindex: "0", "aria-label": opts.label || "Data table" },
      h("table", null, opts.caption ? h("caption", { text: opts.caption }) : null, h("thead", null, thead), h("tbody", null, body)));
  }

  function chrome(page, runDate, through) {
    var head = h("header", { class: "site-head" }, h("div", { class: "wrap" },
      h("a", { class: "brand", href: "index.html", text: "MiLB Hitter Value" }),
      h("span", { class: "muted", text: "Surplus dollars for every A to AAA hitter" }),
      h("nav", { "aria-label": "Main" },
        h("a", { href: "index.html", "aria-current": page === "index" ? "page" : null, text: "Leaderboard" }),
        h("a", { href: "method.html", "aria-current": page === "method" ? "page" : null, text: "Methodology" }))));
    document.body.insertBefore(head, document.body.firstChild);
    document.body.insertBefore(h("a", { class: "skip", href: "#main", text: "Skip to content" }), document.body.firstChild);
    var L = function (u, t) { return h("a", { href: u, rel: "noopener" }, t); };
    document.body.appendChild(h("footer", { class: "site-foot" }, h("div", { class: "wrap" },
      h("p", null, "Stats-only model by Jack Huffard; not affiliated with MLB. Run date: ", h("span", { class: "num", text: runDate || "unknown" }), through ? "; data through " : "", through ? h("span", { class: "num", text: through }) : "", "."),
      h("p", null, "Data sources:"),
      h("ul", null,
        h("li", null, L("https://github.com/armstjc/milb-data-repository", "armstjc/milb-data-repository"), " (MiLB season batting 2005 to 2024)"),
        h("li", null, L("https://statsapi.mlb.com", "MLB Stats API"), " (2025 to 2026 MiLB, MLB seasons, bios, draft, park splits)"),
        h("li", null, L("https://baseballsavant.mlb.com/statcast_search/minors", "Baseball Savant minors Statcast"), " (batted-ball context)"),
        h("li", null, L("https://www.baseball-reference.com/data/", "Baseball-Reference bWAR"), " (validation only)"),
        h("li", null, L("https://www.mlb.com/prospects", "MLB Pipeline preseason Top 100 lists"), " (backtest benchmark)"),
        h("li", null, L("https://blogs.fangraphs.com/what-are-teams-paying-for-a-win-in-free-agency-2026-edition/", "FanGraphs $/WAR"), " (dollar model)")))));
  }

  /* ---------- charts ---------- */
  var cssv = function (n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); };

  /* horizontal range strip: q10 q50 q90 with optional mean marker. fmt formats ticks. */
  /* chart width in CSS px from the page column, so text stays 12px at every viewport (C7) */
  function cw() { var e = document.querySelector("main .wrap") || document.body; return Math.max(280, Math.min(640, Math.round(e.clientWidth - 32))); }

  function rangeStrip(o) {
    var W = cw(), H = 78, pad = 30;
    var lo = Math.min(o.q10, o.mean == null ? o.q10 : o.mean, 0), hi = Math.max(o.q90, o.mean == null ? o.q90 : o.mean);
    if (hi === lo) hi = lo + 1;
    var span = hi - lo; lo -= span * .04; hi += span * .04;
    var x = function (v) { return pad + (v - lo) / (hi - lo) * (W - 2 * pad); };
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, class: "chart fixed", role: "img", "aria-label": o.label });
    svg.appendChild(s("line", { x1: x(0), x2: x(0), y1: 14, y2: 50, class: "axis", "stroke-width": 1.5 }));
    if (Math.abs(x(0) - x(o.q10)) > 36) svg.appendChild(s("text", { x: x(0), y: 62, "text-anchor": "middle", text: "0" }));
    svg.appendChild(s("rect", { x: x(o.q10), y: 26, width: Math.max(1, x(o.q90) - x(o.q10)), height: 14, fill: cssv("--accent"), opacity: .28 }));
    svg.appendChild(s("line", { x1: x(o.q50), x2: x(o.q50), y1: 20, y2: 46, stroke: cssv("--accent"), "stroke-width": 3 }));
    if (o.mean != null) svg.appendChild(s("path", { d: "M" + x(o.mean) + " 22 l-6 -10 h12 z", fill: cssv("--ink") }));
    // value labels under the bar
    svg.appendChild(s("text", { x: x(o.q10), y: 62, "text-anchor": "middle", text: o.fmt(o.q10) }));
    svg.appendChild(s("text", { x: x(o.q90), y: 62, "text-anchor": "middle", text: o.fmt(o.q90) }));
    svg.appendChild(s("text", { x: x(o.q50), y: 76, "text-anchor": "middle", class: "strong", text: "median " + o.fmt(o.q50) }));
    if (o.mean != null) svg.appendChild(s("text", { x: x(o.mean) + 9, y: 20, text: "mean " + o.fmt(o.mean), class: "strong" }));
    return svg;
  }

  function barChart(items, label, o) { /* vertical bars: items [{k, v}] */
    o = o || {};
    var W = cw(), H = 170, padL = 34, padB = 28, padT = 14, n = items.length;
    var max = Math.max.apply(null, items.map(function (i) { return i.v; })) || 1;
    var bw = (W - padL - 8) / n;
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, class: "chart fixed", role: "img", "aria-label": label });
    svg.appendChild(s("line", { x1: padL, x2: W - 8, y1: H - padB, y2: H - padB, class: "axis" }));
    [0, max / 2, max].forEach(function (t) {
      var y = H - padB - t / max * (H - padB - padT);
      svg.appendChild(s("text", { x: padL - 4, y: y + 4, "text-anchor": "end", text: Math.round(t * 100) + "%" }));
    });
    items.forEach(function (it, i) {
      var bh = it.v / max * (H - padB - padT), x = padL + i * bw + bw * .15;
      svg.appendChild(s("rect", { x: x, y: H - padB - bh, width: bw * .7, height: Math.max(bh, 0.5), fill: cssv("--accent"), opacity: .85 }));
      svg.appendChild(s("text", { x: x + bw * .35, y: H - padB + 15, "text-anchor": "middle", text: it.k }));
      if (it.v >= 0.01) svg.appendChild(s("text", { x: x + bw * .35, y: H - padB - bh - 3, "text-anchor": "middle", class: "strong", text: Math.round(it.v * 100) + "%" }));
    });
    return svg;
  }

  function divBar(v, max) { /* one diverging bar, centered at zero */
    var W = 300, H = 12, c = W / 2, w = Math.abs(v) / max * (c - 2);
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, class: "chart", "aria-hidden": "true", style: "max-height:14px" });
    svg.appendChild(s("line", { x1: c, x2: c, y1: 0, y2: H, class: "axis" }));
    svg.appendChild(s("rect", { x: v >= 0 ? c : c - w, y: 1, width: Math.max(w, 1), height: H - 2, fill: v >= 0 ? cssv("--pos") : cssv("--neg") }));
    return svg;
  }

  /* ---------- leaderboard ---------- */
  function initIndex() {
    var main = document.getElementById("main");
    load("data/leaderboard.json").then(function (d) {
      chrome("index", d.run_date, d.data_through);
      var rows = d.rows, state = { key: "ev", dir: -1, shown: 100 };
      var uniq = function (k) { return Array.from(new Set(rows.map(function (r) { return r[k]; }).filter(Boolean))).sort(); };
      var sel = function (id, label, opts, fmtv) {
        return h("label", { for: id }, label, h("select", { id: id },
          h("option", { value: "", text: "All" }), opts.map(function (o) { return h("option", { value: o, text: fmtv ? fmtv(o) : o }); })));
      };
      var order = ["aaa", "aa", "a+", "a", "rk"];
      var q = h("input", { type: "search", id: "q", placeholder: "Search by name", autocomplete: "off" });
      var ctrl = h("div", { class: "controls", role: "search" },
        h("label", { for: "q" }, "Name", q),
        sel("f-level", "Level", order.filter(function (x) { return uniq("level").indexOf(x) >= 0; }), LV),
        sel("f-pos", "Position", uniq("pos")),
        sel("f-org", "Organization", uniq("org")),
        sel("f-group", "Group", ["stat", "prior"], function (g) { return g === "stat" ? "Stat-based" : "Draft prior (low confidence)"; }),
        h("label", { class: "chk" }, h("input", { type: "checkbox", id: "f-conf" }), "Hide low confidence"));
      var count = h("p", { class: "count", "aria-live": "polite" });
      var cols = [
        ["rank", "#", 1], ["name", "Player", 0], ["org", "Organization", 0], ["level", "Level", 0], ["age", "Age", 1], ["pos", "Pos", 0],
        ["mlb_pos", "Proj. MLB pos", 0], ["p_mlb", "P(MLB)", 1], ["war", "WAR (6 yr)", 1], ["eta", "ETA (yrs)", 1], ["ev", "Expected surplus", 1], ["q10", "10th (if MLB)", 1], ["q90", "90th (if MLB)", 1]
      ];
      var thead = h("tr", null), tbody = h("tbody");
      var ths = {};
      cols.forEach(function (c) {
        var b = h("button", { type: "button", text: c[1], title: "Sort by " + c[1] });
        b.addEventListener("click", function () {
          if (state.key === c[0]) state.dir *= -1; else { state.key = c[0]; state.dir = (c[0] === "name" || c[0] === "org" || c[0] === "rank" || c[0] === "level" || c[0] === "pos" || c[0] === "mlb_pos") ? 1 : -1; }
          draw();
        });
        var th = h("th", { scope: "col", class: c[2] ? "n" : null }, b); ths[c[0]] = th; thead.appendChild(th);
      });
      var more = h("div", { class: "more" });
      var tbl = h("div", { class: "tbl-wrap", role: "region", tabindex: "0", "aria-label": "Leaderboard table" },
        h("table", null, h("caption", { text: "2026 hitters, A through AAA, including rookie-eligible players who already debuted. Expected surplus is P(MLB) times the surplus if he reaches MLB, in millions of dollars." }), h("thead", null, thead), tbody));
      main.appendChild(h("div", { class: "wrap" },
        h("h1", { style: "margin-top:24px", text: "2026 leaderboard" }),
        h("p", { class: "lede" }, "Every A through AAA hitter, ranked by expected surplus dollars over six years of team control. Open a player for the full trace from minor league line to dollars. ",
          h("a", { href: "method.html", text: "How this works, and where it fails." })),
        ctrl, count, tbl, more));
      var val = function (id) { return document.getElementById(id).value; };
      function filtered() {
        var t = q.value.trim().toLowerCase(), lv = val("f-level"), ps = val("f-pos"), og = val("f-org"), gp = val("f-group"), hide = document.getElementById("f-conf").checked;
        return rows.filter(function (r) {
          return (!t || r.name.toLowerCase().indexOf(t) >= 0) && (!lv || r.level === lv) && (!ps || r.pos === ps) && (!og || r.org === og) && (!gp || r.group === gp) && (!hide || !r.low_conf);
        });
      }
      function draw() {
        var f = filtered(), k = state.key, dir = state.dir;
        f.sort(function (a, b) {
          var x = a[k], y = b[k];
          if (x == null) return 1; if (y == null) return -1;
          if (typeof x === "string") return dir * x.localeCompare(y) || a.rank - b.rank;
          return dir * (x - y) || a.rank - b.rank;
        });
        for (var c in ths) { if (c === k) ths[c].setAttribute("aria-sort", dir > 0 ? "ascending" : "descending"); else ths[c].removeAttribute("aria-sort"); }
        tbody.textContent = "";
        var frag = document.createDocumentFragment();
        f.slice(0, state.shown).forEach(function (r) {
          var tr = h("tr", { class: r.low_conf ? "low" : null },
            h("td", { class: "n", text: r.rank }),
            h("td", null, h("a", { href: "player.html?id=" + r.id, text: r.name }), r.low_conf ? h("span", { class: "tag", title: "Draft-based prior, low confidence" }, "prior") : null,
              r.in_mlb ? h("span", { class: "tag", title: "Already debuted, still rookie-eligible: P(MLB) is 1 and his control clock is running" }, "in MLB") : null),
            h("td", { text: r.org || "" }), h("td", { text: LV(r.level) }), h("td", { class: "n", text: num(r.age, 1) }), h("td", { text: r.pos || "" }), h("td", { text: r.mlb_pos || "" }),
            h("td", { class: "n", text: pct(r.p_mlb, 0) }), h("td", { class: "n", text: num(r.war, 1) }), h("td", { class: "n", text: r.in_mlb ? "in MLB" : num(r.eta, 1) }),
            h("td", { class: "n" + (r.ev < 0 ? " neg" : ""), text: usd(r.ev) }), h("td", { class: "n" + (r.q10 < 0 ? " neg" : ""), text: usd(r.q10) }), h("td", { class: "n", text: usd(r.q90) }));
          frag.appendChild(tr);
        });
        tbody.appendChild(frag);
        count.textContent = f.length.toLocaleString() + " of " + rows.length.toLocaleString() + " players" + (f.length > state.shown ? ", showing the first " + state.shown : "") + ".";
        more.textContent = "";
        if (f.length > state.shown) {
          var b = h("button", { class: "btn", type: "button", text: "Show 200 more" });
          b.addEventListener("click", function () { state.shown += 200; draw(); b.focus(); });
          more.appendChild(b);
        }
        if (!f.length) tbody.appendChild(h("tr", null, h("td", { colspan: cols.length, text: "No players match these filters. Clear a filter or the search box." })));
      }
      ctrl.addEventListener("input", function () { state.shown = 100; draw(); });
      draw();
    }).catch(function (e) { chrome("index"); fail(e.message); });
  }

  /* ---------- player card ---------- */
  function sec(id, title, explain) {
    return h("section", { "aria-labelledby": id }, h("h2", { id: id, text: title }), h("p", { class: "explain", text: explain }));
  }
  var COMP = { K: "Strikeout rate", BB: "Walk rate", ISO: "Isolated power", BABIP: "BABIP" };

  function initPlayer() {
    var main = document.getElementById("main");
    var id = new URLSearchParams(location.search).get("id");
    if (!/^\d+$/.test(id || "")) { chrome("player"); main.appendChild(h("div", { class: "wrap" }, h("div", { class: "err" }, "No player selected. ", h("a", { href: "index.html", text: "Pick one from the leaderboard." })))); return; }
    load("data/players/" + id + ".json").then(function (p) {
      return [p, p];
    }).then(function (pm) {
      var p = pm[0];
      chrome("player", p.run_date, p.data_through);
      document.title = p.name + " | MiLB Hitter Value";
      var w = h("div", { class: "wrap" }); main.appendChild(w);
      var b = p.bio;
      var ht = b.height_in ? Math.floor(b.height_in / 12) + "'" + (b.height_in % 12) + '"' : null;
      w.appendChild(h("div", { class: "card-head" }, h("h1", { text: p.name }), h("span", { class: "muted" }, "Rank " + p.rank + " of " + p.n_ranked.toLocaleString())));
      w.appendChild(h("p", { class: "sub" }, [p.org, p.team, LV(p.level), "age " + num(p.age, 1), b.pos ? "plays " + b.pos : null, b.bats ? "bats " + b.bats : null, ht].filter(Boolean).join(", ")));
      if (p.low_conf) w.appendChild(h("p", { class: "note", role: "note" }, h("b", { text: "Low confidence. " }),
        "This player has too little A-or-above playing time for the stat model, so the numbers come from a draft-based prior (draft round, pick, age, level, plate appearances)" +
        (b.international ? "; with no draft record he gets a generic international-signee prior with no bonus data." : ".") + " Treat the range as wide and the middle as soft."));

      if (p.in_mlb) w.appendChild(h("p", { class: "note", role: "note" }, h("b", { text: "Already in MLB. " }),
        "He debuted on " + p.in_mlb.debut + " and is still rookie-eligible, so P(MLB) is 1 and his six-year control clock started at his debut. " +
        p.in_mlb.control_years_left + " control year" + (p.in_mlb.control_years_left === 1 ? "" : "s") + " remain from 2027; seasons already played are not counted. His MLB sample is too small to use as an input, so the projection still comes from his minor league record."));

      /* 1. answer */
      var s_ = p.surplus;
      var a = h("section", { class: "answer", "aria-labelledby": "h-answer" },
        h("h2", { id: "h-answer", style: "margin:0 0 8px;font-size:15px;font-family:var(--sans);font-weight:600", text: "Expected surplus value" }),
        h("div", { class: "big num" }, usd(s_.ev), h("small", { text: p.in_mlb ? "already in MLB; remaining control years only" : "P(MLB) " + pct(p.p_mlb, 0) + " times " + usd(s_.if_mlb) + " if he reaches MLB" })),
        h("p", { class: "explain", style: "margin-top:8px" }, "Dollars of value above what the team pays, over six years of control, discounted to 2026. Each year's surplus floors at zero, since a team can option, release or non-tender a player who does not produce, so a wider range of outcomes adds value. " + (p.in_mlb ? "Over his remaining control years" : "If he reaches MLB") + " the 10th to 90th percentile range is " + usd(s_.q10) + " to " + usd(s_.q90) + "; the median is " + usd(s_.q50) + "."),
        rangeStrip({ q10: s_.q10, q50: s_.q50, q90: s_.q90, mean: s_.if_mlb, label: "Surplus if he reaches MLB: 10th " + usd(s_.q10) + ", median " + usd(s_.q50) + ", 90th " + usd(s_.q90) + ", mean " + usd(s_.if_mlb), fmt: function (v) { return usd(v, 0); } }),
        h("p", { class: "legend" }, "Range is conditional on reaching MLB. The triangle is the mean; the bar is the 10th to 90th range and the tick is the median. Outcomes are right-skewed, so the median sits below the mean."));
      w.appendChild(a);

      /* 2. P(MLB) and WAR */
      var s2 = sec("h-war", "Reach probability and production", "The odds he plays in the majors, and how many wins above replacement (our WAR, with MLB fielding from Baseball-Reference) he adds over his first six MLB seasons if he does.");
      s2.appendChild(h("dl", { class: "kv" },
        h("div", null, h("dt", { text: "P(MLB)" }), h("dd", { class: "num", text: pct(p.p_mlb, 1) })),
        h("div", null, h("dt", { text: "6-year WAR, mean" }), h("dd", { class: "num", text: num(p.war.mean, 1) })),
        h("div", null, h("dt", { text: "6-year WAR, median" }), h("dd", { class: "num", text: num(p.war.q50, 1) })),
        h("div", null, h("dt", { text: "ETA, mean" }), h("dd", { class: "num" }, p.eta ? [num(p.eta.mean, 1), h("small", { text: " yrs" })] : "in MLB"))));
      s2.appendChild(rangeStrip({ q10: p.war.q10, q50: p.war.q50, q90: p.war.q90, mean: p.war.mean, label: "6-year WAR if he reaches MLB: 10th " + num(p.war.q10) + ", median " + num(p.war.q50) + ", 90th " + num(p.war.q90), fmt: function (v) { return num(v, 1); } }));
      s2.appendChild(h("p", { class: "legend", text: "WAR range is conditional on reaching MLB. The mean is the central estimate; the median is lower because outcomes are right-skewed. Negative WAR means below replacement." }));
      w.appendChild(s2);

      /* 3. ETA */
      var s3 = sec("h-eta", "Debut timing", "When he is expected to debut, if he does. Bars are the probability of a first MLB game in each calendar year.");
      if (p.eta) {
        var items = Object.keys(p.eta.debut).sort().map(function (y) { return { k: y, v: p.eta.debut[y] }; });
        s3.appendChild(barChart(items, "Probability of debut by year: " + items.map(function (i) { return i.k + " " + Math.round(i.v * 100) + "%"; }).join(", ")));
        s3.appendChild(h("p", { class: "legend", text: "Mean ETA " + num(p.eta.mean, 1) + " years from the 2026 snapshot, if he debuts; 10th to 90th percentile " + num(p.eta.q10, 0) + " to " + num(p.eta.q90, 0) + " years. Bars come from the debut hazard model (the chance of debuting each year given he has not yet), so they sum to his P(MLB)." }));
      } else s3.appendChild(h("p", { class: "muted", text: "He has already debuted (" + p.in_mlb.debut + ")." }));
      w.appendChild(s3);

      /* 4. drivers */
      var s4 = sec("h-drv", "What drives the projection", "The model's inputs grouped into families. Blue pushes the projection up, orange pushes it down, sorted by size. Linear terms overlap, so read the family total, not single features. Italic phrases carry no direction: the family total also reflects trend and regressed values.");
      var two = h("div", { class: "two" });
      [["p_mlb", "Reach probability (log-odds)", "log-odds"], ["war", "Six-year WAR if he reaches (wins)", "wins"]].forEach(function (t) {
        var L = p.drivers[t[0]], mx = Math.max.apply(null, L.map(function (x) { return Math.abs(x.c); }).concat([0.001]));
        two.appendChild(h("div", null, h("h3", { text: t[1] }), L.length ? h("ol", { class: "drv", "aria-label": t[1] + " drivers" }, L.map(function (x) {
          return h("li", null, h("div", { class: "fam" }, h("span", { text: x.family }), h("span", { class: "num " + (x.c < 0 ? "neg" : ""), text: (x.c > 0 ? "+" : "") + num(x.c, 2) })),
            divBar(x.c, mx), h("div", { class: "ph", style: x.sup ? "font-style:italic" : null, text: x.phrase }));
        })) : h("p", { class: "muted", text: "No drivers available." })));
      });
      s4.appendChild(two);
      w.appendChild(s4);

      /* 5. chain */
      var s5 = sec("h-chain", "From the box score to the model input", "Each rate goes through four steps: the raw 2026 line, adjusted for the home park, translated to an MLB-equivalent (MLE), then regressed toward his league's average by sample size. Park factor 1.00 is neutral. BABIP is shown for context only; it is not a model input.");
      if (p.chain.length) {
        var rows = [];
        p.chain.forEach(function (c) {
          ["K", "BB", "ISO", "BABIP"].forEach(function (k, i) {
            var pf = c.park ? (k === "K" ? c.park.SO : k === "BB" ? c.park.BB : k === "BABIP" ? c.park.BABIP : "2B/3B " + num(c.park.B2B3B, 2) + ", HR " + num(c.park.HR, 2)) : null;
            var f = k === "ISO" || k === "BABIP" ? rate : function (x) { return pct(x, 1); };
            rows.push([{ v: i === 0 ? LV(c.level) : "", cls: "lvl" }, COMP[k], i === 0 ? c.PA : "", c[k].map(f)[0], f(c[k][1]), f(c[k][2]), f(c[k][3]), typeof pf === "number" ? num(pf, 2) : (pf || "n/a")]);
          });
        });
        s5.appendChild(table(["Level", "Rate", { t: "PA", n: 1 }, { t: "Raw", n: 1 }, { t: "Park-neutral", n: 1 }, { t: "MLE", n: 1 }, { t: "Regressed", n: 1 }, "Park factor"].map(function (x, i) { return i >= 2 && i <= 6 ? x : x; }),
          rows.map(function (r) { return r.map(function (c, i) { return i >= 3 && i <= 6 ? { v: c } : c; }); }), { label: "Rate chain by level", caption: "2026 rates by level. MLE and regressed are on the MLB scale." }));
        if (p.blend) {
          s5.appendChild(h("p", { class: "explain" }, "Model input across levels (3:2 weighted blend of 2026 and 2025 regressed MLEs, 2026 alone when 2025 is missing): K " + pct(p.blend.K) + ", BB " + pct(p.blend.BB) + ", ISO " + rate(p.blend.ISO) + ". Single-season regressed (across levels): K " + pct(p.blend.reg_K) + ", BB " + pct(p.blend.reg_BB) + ", ISO " + rate(p.blend.reg_ISO) + "." + (p.blend.contact != null ? " Contact rate (1 minus whiffs per swing, A to AAA): " + pct(p.blend.contact) + "." : "")));
        }
      } else s5.appendChild(h("p", { class: "muted", text: "No A through AAA rate chain for 2026 (Rookie-level or too few plate appearances). The projection comes from the prior." }));
      var hist = p.hist.map(function (x) { return [String(x.season), LV(x.level), x.G, x.PA, rate(x.AVG), rate(x.OBP), rate(x.SLG), pct(x.K), pct(x.BB), rate(x.ISO), rate(x.BABIP)]; });
      s5.appendChild(h("h3", { text: "Last three seasons, as played" }));
      s5.appendChild(table(["Season", "Level", { t: "G", n: 1 }, { t: "PA", n: 1 }, { t: "AVG", n: 1 }, { t: "OBP", n: 1 }, { t: "SLG", n: 1 }, { t: "K%", n: 1 }, { t: "BB%", n: 1 }, { t: "ISO", n: 1 }, { t: "BABIP", n: 1 }],
        hist, { label: "Level history", caption: "Unadjusted stat lines (recomputed from counting stats)." }));
      w.appendChild(s5);

      /* 6. batted ball */
      var s6 = sec("h-bb", "Batted-ball context", "Exit velocity and launch angle from Baseball Savant, tracked at AAA and Low-A Florida State League parks only. Display only: it does not change the projection.");
      if (p.batted.length) {
        s6.appendChild(table(["Season", "Level", { t: "Tracked BIP", n: 1 }, { t: "Avg EV", n: 1 }, { t: "EV90", n: 1 }, { t: "Hard-hit%", n: 1 }, { t: "Avg LA", n: 1 }, { t: "Sweet-spot%", n: 1 }, { t: "Barrel%", n: 1 }],
          p.batted.map(function (x) { return [String(x.season), LV(x.level), x.n, num(x.ev, 1) + " mph", num(x.ev90, 1) + " mph", pct(x.hh), num(x.la, 1) + "°", pct(x.sweet), pct(x.barrel)]; }), { label: "Batted-ball metrics" }));
      } else s6.appendChild(h("p", { class: "muted", text: "Not tracked: this player has no batted balls at AAA or Low-A Florida State League parks in 2025 or 2026." }));
      s6.appendChild(h("p", { class: "legend", text: "An adjustment that swaps observed ISO and BABIP for expected values from these metrics (S14) was tested and not applied; it failed its test (see methodology). S14 applied to this card: " + (p.s14_applied ? "yes" : "no") + "." }));
      w.appendChild(s6);

      /* 7. positions */
      var s7 = sec("h-pos", "Projected MLB position", "Where players with his current position and level have ended up in the majors, from the 2005 to 2017 historical transition matrix. Position feeds the positional adjustment in WAR.");
      s7.appendChild(h("ul", { class: "drv", "aria-label": "Position probabilities" }, p.pos_probs.map(function (x) {
        var svg = s("svg", { viewBox: "0 0 300 12", class: "chart", "aria-hidden": "true", style: "max-height:14px" });
        svg.appendChild(s("rect", { x: 0, y: 1, width: Math.max(1, x[1] * 300), height: 10, fill: cssv("--accent") }));
        return h("li", null, h("div", { class: "fam" }, h("span", { text: POSS[x[0]] || x[0] }), h("span", { class: "num", text: pct(x[1], 0) })), svg);
      })));
      w.appendChild(s7);

      /* 8. bio */
      var s8 = sec("h-bio", "Bio and acquisition", "Context only. Height enters the model; weight is shown for display and has no model role because current listed weight leaks information from after the snapshot (see methodology).");
      s8.appendChild(h("dl", { class: "kv" },
        h("div", null, h("dt", { text: "Bats" }), h("dd", { text: b.bats || "n/a" })),
        h("div", null, h("dt", { text: "Height (model input)" }), h("dd", { class: "num", text: b.height_in ? b.height_in + " in" : "n/a" })),
        h("div", null, h("dt", { text: "Weight (display only)" }), h("dd", { class: "num", text: b.weight_lb ? b.weight_lb + " lb" : "n/a" })),
        h("div", null, h("dt", { text: "Age vs level average" }), h("dd", { class: "num", text: (b.age_vs_level > 0 ? "+" : "") + num(b.age_vs_level, 1) + " yrs" })),
        h("div", null, h("dt", { text: "Draft" }), h("dd", { class: "num" }, b.draft ? b.draft.year + " rd " + b.draft.round + " pick " + b.draft.pick : (b.international ? "No draft record" : "n/a"),
          b.draft && b.draft.bonus ? h("small", { text: " bonus " + usd(b.draft.bonus / 1e6, 2) }) : null))));
      w.appendChild(s8);
      w.appendChild(h("p", { class: "explain", style: "margin-top:24px" }, h("a", { href: "index.html", text: "Back to leaderboard" }), " or read the ", h("a", { href: "method.html", text: "methodology" }), "."));
    }).catch(function (e) { chrome("player"); fail(e.message); });
  }

  /* ---------- methodology ---------- */
  function initMethod() {
    var main = document.getElementById("main");
    load("data/method.json").then(function (M) {
      chrome("method", M.run_date, M.data_through);
      var w = h("div", { class: "wrap narrow prose" }); main.appendChild(w);
      var P = function (t) { return h("p", null, t); };
      var S = function (id, t) { var e = h("h2", { id: id, text: t }); return e; };
      var f2 = function (x) { return x.toFixed(2); }, f3 = function (x) { return x.toFixed(3); };
      var C1 = M.C1, C2 = M.C2.primary_excl_censored, C3 = M.C3.primary_excl_censored, C4 = M.C4, C8 = M.C8, C9 = M.C9, C12 = M.C12;
      var hs = M.holdout.stat_backtest.all, hp = M.holdout.prior_backtest.all, hs12 = M.holdout.stat_fit2017.all;
      var pool = C2.pooled, ci = pool.diff_ci90_boot2000;
      var L12 = C12.lists_2019_2020_vs_war_thru_2026, pool12 = L12.pooled, ci12 = pool12.diff_ci90_boot2000;
      var failDec = C4.deciles.filter(function (d) { return !d.pass; });
      var dec12 = C12.p_mlb.all.calibration.map(function (d) { return Object.assign({}, d, { pass: Math.abs(d.gap) <= 0.05 }); });
      var fail12 = dec12.filter(function (d) { return !d.pass; });
      var verdict = function (c) { return c[1] < 0 ? "loses to" : c[0] > 0 ? "beats" : "cannot be separated from"; };
      var s14 = C8.s14_pass, B = M.babip, sp = M.model_choice.spread;
      var decTxt = function (L) { return L.map(function (d) { return "decile " + d.decile + " (" + (d.gap * 100).toFixed(1) + " pts)"; }).join(", "); };
      var c10cells = [], c10fail = [];
      Object.keys(M.C10).forEach(function (st) { ["K", "BB", "ISO", "BABIP"].forEach(function (k) { c10cells.push(1); if (!M.C10[st][k].pass) c10fail.push(st + " " + k); }); });

      w.appendChild(h("h1", { style: "margin-top:24px", text: "Methodology" }));
      w.appendChild(h("p", { class: "lede" }, "I built this to put a defensible surplus dollar value on every A through AAA hitter, with every number traceable to its inputs. The short version: it is a reasonable baseline that clearly beats a naive model, it trails scouts on the lists where both can be scored over six full years, and it is not a replacement for scouting."));
      w.appendChild(h("ul", { class: "toc", "aria-label": "Sections" }, [["results", "Results"], ["revision", "v1.1 revision"], ["data", "Data"], ["park", "Park factors"], ["mle", "Translations"], ["war", "WAR"], ["feat", "Features"], ["models", "Models"], ["value", "Value"], ["assume", "Assumptions"], ["limits", "Limitations"]].map(function (x) { return h("li", null, h("a", { href: "#" + x[0], text: x[1] })); })));

      /* results */
      w.appendChild(S("results", "What I found"));
      w.appendChild(P("I made every modeling decision on 2005 to 2012 snapshots with cross-validation grouped by player, then scored two holdouts once each: 2013 to 2017 and a fresh 2018 to 2019 set that no version of the model had seen. The honest results come first because they decide how much weight a reader should put on the dollar figures."));
      w.appendChild(h("ul", { class: "results" },
        h("li", null, h("b", { text: "Beats the naive baseline (C3)" }), "On 2013 to 2017, P(MLB) log loss " + f3(C3.logloss_model) + " vs " + f3(C3.logloss_baseline) + " for an age-vs-level plus OPS baseline; expected-WAR Spearman " + f3(C3.spearman_model) + " vs " + f3(C3.spearman_baseline) + " (n=" + C3.n.toLocaleString() + " holdout hitters not yet in MLB)." + (C3.model_beats_baseline_logloss && C3.model_beats_baseline_spearman ? "" : " The model does not win both measures.")),
        h("li", { class: ci[1] < 0 ? "bad" : null }, h("b", { text: "Trails MLB Pipeline on the 2014 to 2018 lists (C2)" }), "Pooled Spearman vs realized six-year WAR: model " + f3(pool.spearman_model) + ", Pipeline " + f3(pool.spearman_list) + "; difference " + f3(pool.diff) + ", 90% bootstrap CI " + f3(ci[0]) + " to " + f3(ci[1]) + ". The model " + verdict(ci) + " the list (n=" + C2.n + ")."),
        h("li", null, h("b", { text: "Ahead of Pipeline on the 2019 and 2020 lists, on a shorter horizon (C12)" }), "Spearman vs WAR accumulated through 2026: model " + f3(pool12.spearman_model) + ", Pipeline " + f3(pool12.spearman_list) + "; difference " + f3(pool12.diff) + ", 90% CI " + f3(ci12[0]) + " to " + f3(ci12[1]) + " (n=" + L12.n + "). This is a first look at data the model never saw, but it measures six to seven seasons of calendar time rather than six MLB seasons, which rewards quick arrival, and the sample is small. I read it as encouraging, not as proof that the model out-ranks scouts."),
        h("li", null, h("b", { text: "Fresh 2018 to 2019 holdout (C12)" }), "P(MLB) log loss " + f3(hs12.logloss) + ", AUC " + f3(hs12.auc) + " (n=" + hs12.n.toLocaleString() + "). Expected-WAR Spearman vs WAR through 2026 is close to the naive baseline (2018: " + f3(C12.ev_vs_war_thru_2026.all["2018"].spearman_model) + " vs " + f3(C12.ev_vs_war_thru_2026.all["2018"].spearman_baseline) + "; 2019: " + f3(C12.ev_vs_war_thru_2026.all["2019"].spearman_model) + " vs " + f3(C12.ev_vs_war_thru_2026.all["2019"].spearman_baseline) + "). Among 2018 players with a complete six-year window (fast risers only, n=" + C12.war6_2018_complete_windows_fast_risers.n + "), WAR Spearman is " + f3(C12.war6_2018_complete_windows_fast_risers.spearman_war_mean) + " vs " + f3(C12.war6_2018_complete_windows_fast_risers.spearman_baseline) + " for the baseline."),
        h("li", { class: failDec.length ? "bad" : null }, h("b", { text: "P(MLB) under-predicts in the upper-middle deciles (C4)" }), failDec.length ? "On 2013 to 2017, " + decTxt(failDec) + " miss the 5 point tolerance" + (fail12.length ? "; on 2018 to 2019, " + decTxt(fail12) + "." : ".") + " Cross-validation on the training years was within 5 points, so this looks like drift toward more players reaching MLB in later classes. I report it rather than recalibrate to the holdout." : "All deciles within 5 points."),
        h("li", { class: "bad" }, h("b", { text: "The 2013 to 2017 holdout has been used before (Q18)" }), M.holdout_looks + " Earlier versions changed the WAR selection rule after seeing a holdout result, so that holdout is not clean. The 2018 to 2019 results above are the cleaner test."),
        h("li", { class: "bad" }, h("b", { text: "Translation level-step test fails in " + c10fail.length + " of " + c10cells.length + " cells (C10)" }), "Players who move up a level still look slightly better in MLB-equivalent terms than players who repeat it, mostly for walks and for power at AA to AAA, so the translations remain a little too harsh on the lower level (see Translations)."),
        h("li", { class: s14 ? null : "bad" }, h("b", { text: "Batted-ball adjustment rejected (C8)" }), s14 ? "S14 passed its gate and is applied." : "Expected ISO from exit velocity and launch angle helped year-ahead AAA prediction, but did not predict MLB results at least as well as the existing chain (n=" + C8.b.n + "), so S14 is not applied."),
        h("li", { class: "bad" }, h("b", { text: "Fielding is borrowed and only in the outcome" }), "MLB fielding runs come from Baseball-Reference (DRS-based), so the WAR target values defense, but no minor league input measures it; the model sees defense only through position mix and projected position.")));
      w.appendChild(P("The comparison to Pipeline is the one I would weight most. Hitters on a top 100 list already passed a scouting screen, so beating them on stats alone was always a long shot; the model sees age, level and production, and nothing about tools, swing, or makeup. Where it is useful is breadth: it prices all " + M.coverage.players_2026.toLocaleString() + " hitters, including ones no list covers, with a range."));

      /* headline tables */
      w.appendChild(h("h3", { text: "Backtest by list year" }));
      var lyRows = Object.keys(C2.per_year).map(function (y) { var d = C2.per_year[y]; return [y, "six-year WAR", d.n, f3(d.spearman_model), f3(d.spearman_list)]; })
        .concat(Object.keys(L12.per_year).map(function (y) { var d = L12.per_year[y]; return [y, "WAR through 2026", d.n, f3(d.spearman_model), f3(d.spearman_list)]; }));
      w.appendChild(table(["List year", "Outcome", { t: "n", n: 1 }, { t: "Model Spearman", n: 1 }, { t: "Pipeline Spearman", n: 1 }], lyRows,
        { label: "Per-year list results", caption: "Spearman vs realized WAR among matched ranked hitters. Pipeline lists are used because Baseball America lists are paywalled (Q6). Censored and pre-2005 rows excluded from six-year rows; listed players already in MLB enter with P(MLB) = 1." }));
      w.appendChild(h("h3", { text: "P(MLB) calibration on the 2013 to 2017 holdout" }));
      w.appendChild(calibrationChart(C4.deciles));
      w.appendChild(table(["Decile", { t: "n", n: 1 }, { t: "Predicted", n: 1 }, { t: "Observed", n: 1 }, { t: "Gap (pts)", n: 1 }, "Within 5 pts"],
        C4.deciles.map(function (d) { return [String(d.decile), d.n, pct(d.predicted), pct(d.observed), num(d.gap * 100, 1), { v: d.pass ? "pass" : "fail", cls: d.pass ? "" : "neg" }]; }),
        { label: "C4 calibration deciles" }));
      w.appendChild(h("h3", { text: "P(MLB) calibration on the fresh 2018 to 2019 holdout" }));
      w.appendChild(calibrationChart(dec12));
      w.appendChild(P("Holdout 2013 to 2017 (stat group, players not yet in MLB, n=" + hs.n.toLocaleString() + "): log loss " + f3(hs.logloss) + ", AUC " + f3(hs.auc) + ", Spearman of expected WAR vs realized " + f3(hs.spearman_ev_vs_realized) + ", Spearman among reached players " + f3(hs.spearman_war_reached_only) + "; the 10th to 90th WAR interval covers " + pct(hs.war_q10_q90_coverage, 0) + " of reached stat-group players and " + pct(hp.war_q10_q90_coverage, 0) + " of prior-group players (nominal 80%). Earlier versions reported higher Spearman values because they scored players already in MLB, who are easy to rank; on that older population this version scores " + f3(M.C3.v1_population_spearman_model) + ". Restricted to players with no training-era rows (a time split otherwise shares players across train and test), expected-WAR Spearman is " + f3(M.holdout.stat_backtest.player_disjoint.spearman_ev_vs_realized) + " (n=" + M.holdout.stat_backtest.player_disjoint.n.toLocaleString() + ")."));
      w.appendChild(h("h3", { text: "Biggest disagreements with the 2014 to 2018 Pipeline lists" }));
      var dis = function (L) { return L.slice(0, 6).map(function (x) { return [x.name, String(x.list_year), x.list_rank, x.model_rank, pct(x.p_mlb, 0), num(x.realized_war, 1)]; }); };
      var dh = ["Player", "List year", { t: "List rank", n: 1 }, { t: "Model rank", n: 1 }, { t: "Model P(MLB)", n: 1 }, { t: "Realized 6-yr WAR", n: 1 }];
      w.appendChild(table(dh, dis(M.disagreements.model_higher), { label: "Model higher than list", caption: "Model ranked him well above his list rank. Rank is within matched hitters on that list." }));
      w.appendChild(table(dh, dis(M.disagreements.model_lower), { label: "Model lower than list", caption: "Model ranked him well below his list rank." }));
      w.appendChild(P("The model is high on productive hitters whose stat lines did not translate and low on young players whose tools are not in the stat line. Realized WAR is " + M.realized_definition));

      /* revision */
      w.appendChild(S("revision", "What changed in v1.1"));
      w.appendChild(P("An audit of the first version found problems that changed the board, so I fixed them, wrote the expected direction of each change down before rerunning, and then scored the holdouts once. The main changes:"));
      w.appendChild(h("ul", null,
        h("li", { text: "Players who had already debuted were scored as prospects (the old number one had debuted in August 2026) and made up 41% of the reached players the model trained on. They are now out of training and valued with P(MLB) = 1 and a control clock that started at their real debut." }),
        h("li", { text: "P(MLB) and debut timing now come from one model of the yearly chance to debut, which can learn from recent classes for the years they have been observed and removes an off-by-one year in the old ETA." }),
        h("li", { text: "BABIP left the model. In a train-era ablation, dropping it moved log loss from " + f3(B.logloss_with) + " to " + f3(B.logloss_without) + " and expected-WAR Spearman from " + f3(B.ev_spearman_with) + " to " + f3(B.ev_spearman_without) + ", which is noise, while a regressed MiLB BABIP MLE correlates only r = " + f2(B.r_next_mlb) + " with next-year MLB BABIP (n=" + B.n_next_mlb.toLocaleString() + "). It was nonetheless getting " + pct(B.driver_share_p_mlb_v1, 0) + " of the card driver weight for P(MLB), likely because teams promote players with high averages. It stays on cards as context." }),
        h("li", { text: "Translations now use cross-season pairs as well as same-season ones, because promotions follow hot stretches and same-season pairs make the lower level look better than it was." }),
        h("li", { text: "Batting run values come from BaseRuns, which fixed a regression that overvalued home runs and triples by roughly 20%." }),
        h("li", { text: "Surplus floors at zero each year and uses a per-player spread, so the model can finally say one prospect is riskier than another with the same mean." }),
        h("li", { text: "Career history now reaches back to 2000, so players whose careers began before 2005 no longer look like rookies in the training data, and pre-2005 draftees are no longer labeled undrafted." })));

      /* data */
      w.appendChild(S("data", "Data"));
      w.appendChild(P("MiLB season batting 2005 to 2024 comes from armstjc/milb-data-repository; 2025 and 2026 come from the MLB Stats API, because the repo's 2025 files stop on 2025-05-01 and some of its rate columns are internally impossible. I recompute every rate from counting stats (Q4) and aggregate mid-season stints. MLB seasons, bios, debut dates and draft records (1990 on) come from the Stats API; MiLB 2000 to 2004 from the Stats API is used only for career history (Q17). Bios and debut dates were pulled on " + M.people_pulled_on + ". Coverage: " + M.coverage.milb_player_season_rows.toLocaleString() + " MiLB player-season rows, " + M.coverage.milb_seasons + ". The 2026 snapshot scores " + M.coverage.players_2026.toLocaleString() + " hitters: " + M.coverage.stat.toLocaleString() + " stat-based and " + M.coverage.prior.toLocaleString() + " on the draft prior."));
      w.appendChild(P("Batted-ball data is Baseball Savant minors Statcast, which tracks AAA (full from 2023) and Low-A Florida State League parks (2021 on), " + M.coverage.tracked_bip_rows.toLocaleString() + " tracked balls in play across " + M.coverage.tracked_player_seasons.toLocaleString() + " player-seasons. Everything else has no exit velocity. Savant is the only source I used for batted balls; the repo play-by-play ends in May 2025."));

      /* park */
      w.appendChild(S("park", "Park factors"));
      w.appendChild(P("Park factors come from Stats API team home and road splits for every MiLB level and MLB, 2005 to 2026, by component (singles, doubles and triples, HR, walks, strikeouts, BABIP, runs). Each factor is a home rate over a road rate, normalized to a league mean of 1, pooled over a three-year window at the same venue, then shrunk toward 1 with a constant derived from the observed year-to-year reliability of the factors. A player's adjustment uses half the factor, since half his games are on the road."));
      var pe = M.park_examples;
      w.appendChild(table(["Team (AAA)", "Park", { t: "HR", n: 1 }, { t: "SO", n: 1 }, { t: "BABIP", n: 1 }, { t: "Runs", n: 1 }],
        pe.highest_hr.concat(pe.lowest_hr).map(function (x) { return [x.team, x.venue || "", f2(x.pf_HR), f2(x.pf_SO), f2(x.pf_BABIP), f2(x.pf_R)]; }),
        { label: "Park factor examples", caption: "Three most home-run-friendly and three least, " + pe.season + " AAA. " + pe.note }));

      /* mle */
      w.appendChild(S("mle", "Translations"));
      w.appendChild(P("To compare a Low-A line with a AAA line, I chain factors from matched pairs: the same player at adjacent levels, weighted by the harmonic mean of the two samples. Same-season pairs alone are biased, because players get promoted after hot stretches, so I add cross-season pairs (a full season at one level, then a full season one level up the next year) with normal year-over-year aging removed using players who repeated a level. Factors are fit at league-season grain, shrunk to level-season and then to an all-years factor, and chained through AAA to MLB. This handles the PCL, the 2021 restructure, and era shifts without special cases. The MLE is then regressed toward his league's average by sample size, using stabilization points (K 60 PA, BB 120 PA, ISO 160 AB, BABIP 820 BIP). Pooled all-years factors for one step up:"));
      var tf = M.translation_factors, lv = ["a", "a+", "aa", "aaa"], comps = ["K", "BB", "ISO", "BABIP"];
      w.appendChild(table(["Component"].concat(lv.map(function (l) { return { t: l === "aaa" ? "AAA to MLB" : LV(l) + " to next", n: 1 }; })),
        comps.map(function (c) { return [c].concat(lv.map(function (l) { var t = tf.filter(function (x) { return x.from_level === l && x.component === c; })[0]; return t ? f3(t.factor) : "n/a"; })); }),
        { label: "Translation factors", caption: "Multiply a park-neutral rate by the factor to move it up one level." }));
      w.appendChild(P("Out of sample (AAA season s, MLB season s+1, 200+ PA each), the MLE beats the raw AAA rate on RMSE for all four components. Some of that is just the level-bias correction, and the factors are fit on all years, so there is mild leakage."));
      w.appendChild(P("The level-step test (C10) checks whether moving up a level changes a player's MLE beyond normal aging; a good translation should not. Same-season pairs alone failed 10 of 12 cells. With cross-season pairs it fails " + c10fail.length + " of " + c10cells.length + ", with the remaining gaps in walks at every step and in power and BABIP at AA to AAA, so lower-level MLEs are still slightly pessimistic. Movers are also selected for a good season, which biases this test against finding that problem, so the real gap is likely a bit larger. The plus or minus one standard error band I set in advance is strict: an unbiased translation would still miss about a third of cells by chance."));
      w.appendChild(table(["Step", "Component", { t: "Mover change", n: 1 }, { t: "Repeater change", n: 1 }, { t: "Gap", n: 1 }, { t: "SE", n: 1 }, "Within 1 SE"],
        [].concat.apply([], Object.keys(M.C10).map(function (st) { return ["K", "BB", "ISO", "BABIP"].map(function (k) { var c = M.C10[st][k];
          return [({ "a->a+": "Low-A to High-A", "a+->aa": "High-A to AA", "aa->aaa": "AA to AAA" })[st] || st, k, f3(c.mover_change), f3(c.repeater_change_matched), f3(c.diff), f3(c.se), { v: c.pass ? "pass" : "fail", cls: c.pass ? "" : "neg" }]; }); })),
        { label: "C10 level-step test", caption: "Full-season movers vs same-level repeaters, mean change in MLE rates the next season (repeater change matched on age bucket)." }));

      /* war */
      w.appendChild(S("war", "WAR"));
      w.appendChild(P("I wrote my own simplified WAR: wOBA batting runs from run values derived each season from BaseRuns at league totals (the out valued above average, as in wOBA), park adjusted, plus baserunning (stolen bases and caught stealing, and double-play avoidance), a positional adjustment and a replacement level. Fielding runs are the one borrowed piece: Baseball-Reference's runs_field (DRS-based), available for every season since 2005. Against bWAR on " + C1.n.toLocaleString() + " player-seasons with 300+ PA, r = " + f3(C1.r_owar_bwar) + " (threshold " + C1.threshold + "). That number is partly shared by construction, so the cleaner test of my own pieces is the offense-only version against bWAR's offensive components (batting, baserunning, double plays, position, replacement): r = " + f3(C1.r_owar_vs_bwar_offense) + "."));
      var gr = function (L) { return L.map(function (x) { return [x.name + " " + x.season, num(x.owar, 1), num(x.bwar, 1)]; }); };
      w.appendChild(table(["Largest negative residuals", { t: "My WAR", n: 1 }, { t: "bWAR", n: 1 }], gr(C1.glove_first), { label: "Negative residuals", caption: "My WAR below bWAR: remaining gaps (batting runs, park, position credit)." }));
      w.appendChild(table(["Largest positive residuals", { t: "My WAR", n: 1 }, { t: "bWAR", n: 1 }], gr(C1.bat_first), { label: "Positive residuals", caption: "My WAR above bWAR." }));
      w.appendChild(P("Baserunning agrees with bWAR at r = " + f2(C1.r_bsr_vs_bwar_br_dp) + "; my double-play term is an approximation because true opportunities need MLB play-by-play, and extra bases taken are not included. The training target is this WAR summed over a player's first six MLB seasons from debut."));

      /* features */
      w.appendChild(S("feat", "Features"));
      w.appendChild(P("Each row is one player at one offseason snapshot, for players not yet in the majors. Features: regressed MLE rates (K, BB, ISO) blended 3:2 with the prior season, year-over-year change, age and age relative to the level average, highest level, projected MLB position (from a historical transition matrix) and its positional runs, plate-appearance volume, and the S15 groups that survived selection. I tested each S15 group on 2005 to 2012 data only, with cross-validation grouped by player, before looking at the holdout:"));
      var c9t = C9.table, kept = C9.kept_groups;
      w.appendChild(table(["Group", { t: "Log loss", n: 1 }, { t: "EV Spearman", n: 1 }, "Kept"],
        Object.keys(c9t).map(function (g) { var d = c9t[g]; return [g === "body" ? "body (height only)" : g, f3(d.logloss), f3(d.ev_spearman), g === "baseline" || g === "all_kept" ? "" : (d.keep ? "yes" : "no")]; }),
        { label: "C9 feature group selection", caption: "Train-era cross-validation (n=" + C9.n_rows.toLocaleString() + " rows). Kept: " + kept.join(", ") + ". Weight and BMI were removed earlier because of look-ahead (Q15). Several gains are within noise; the rule keeps a group if either measure improves and neither worsens beyond a small tolerance." }));
      w.appendChild(P("Development pace (games at the current level, how fast he climbed) was kept in v1 but dropped in v1.1 once career history before 2005 was backfilled, which suggests part of its earlier value came from players whose careers were cut off at 2005. Promotion speed still enters through level and age for level, which partly encodes how an organization judged him; ranks and grades are never inputs (X7). Height and weight are current values from the Stats API, not as of each snapshot (Q15); weight failed a look-ahead check (players who reach MLB have their weights updated over their careers) and is excluded."));

      /* models */
      w.appendChild(S("models", "Models"));
      var cv = M.model_choice.cv, ch = M.model_choice.chosen, cc = M.model_choice.calibration_check;
      w.appendChild(P("Two models carry the projection. The first is a yearly debut model: for each season after the snapshot, the chance he debuts that year given he has not yet. Chaining those gives P(MLB) over nine years and the whole debut-year distribution, and classes that are still in progress (2018 to 2025) contribute the years they have been observed, which is how the post-2021 minor leagues get into the fit. The second is expected six-year WAR given he reaches. Each is a regularized linear model or LightGBM, picked on train-era cross-validation; WAR is chosen on Spearman, not RMSE, because valuation is a ranking problem. The final WAR model trains on snapshots through 2015, because later classes have incomplete six-year windows and the players who are complete are the fast risers."));
      w.appendChild(table(["Target", "Metric", { t: "Linear", n: 1 }, { t: "LightGBM", n: 1 }, "Chosen"],
        [["Yearly debut", "log loss (person-years)", f3(cv.hazard.linear), f3(cv.hazard.lightgbm), ch.hazard],
         ["WAR if reached", "Spearman (higher is better)", f3(cv.war.spearman_linear), f3(cv.war.spearman_lightgbm), ch.war]],
        { label: "Model selection", caption: "Train-era cross-validation, snapshots through 2012, grouped by player." }));
      var tail = cc.stat_final.tail;
      w.appendChild(P("Cross-validated P(MLB) is within " + (cc.stat_backtest.max_abs_gap * 100).toFixed(1) + " points in every decile on the training years, so no recalibration is applied. The decile view hides the top tail: players predicted 90 to 98% reached somewhat less often than predicted (" + tail.filter(function (t) { return t.hi <= 0.98; }).map(function (t) { return pct(t.predicted, 0) + " predicted vs " + pct(t.observed, 0) + " observed, n=" + t.n; }).join("; ") + "), while every one of the " + tail[tail.length - 1].n + " players predicted above 99% reached."));
      var cov = sp.stat.coverage_by;
      w.appendChild(P("The WAR range comes from a second model of how far outcomes spread around the mean, fit on out-of-fold residuals from player features and the WAR prediction itself, then applied to a pooled shape of standardized residuals. Outcomes are strongly right-skewed: among the highest predicted fifth of training players, realized six-year WAR averaged well above its median. In cross-validation the 10th to 90th range covers " + pct(sp.stat.coverage_overall, 0) + " overall and between " + pct(Math.min.apply(null, [].concat.apply([], Object.keys(cov).map(function (k) { return Object.values(cov[k]); }))), 0) + " and " + pct(Math.max.apply(null, [].concat.apply([], Object.keys(cov).map(function (k) { return Object.values(cov[k]); }))), 0) + " across age, level and prediction subgroups (C11, target 75 to 85%)." + (sp.prior.c11_pass ? " The prior group's version passes too." : " The prior group's version misses in its smallest subgroup (AA and AAA draft-prior players, a handful of rows).")));
      w.appendChild(P("Players without 150 A-or-above plate appearances over two seasons (the Q7 rule) fall to a draft prior with the same structure: round, pick, age, level and years since draft. Signing bonus is missing before 2016 so it is not a usable input. Prior-group cards carry a low-confidence flag. Card drivers are SHAP values for LightGBM and coefficient times standardized value for linear models, summed by feature family; P(MLB) drivers average the yearly debut model over the nine years."));

      /* value */
      w.appendChild(S("value", "Value"));
      w.appendChild(P("Surplus is the market value of the projected WAR minus what the team pays, over the first six MLB seasons, discounted to 2026. WAR is spread across control years using the observed profile of real first-six-year careers (below). Years 1 to 3 pay the league minimum; years 4 to 6 pay a share of market value (arbitration). Each year's surplus floors at zero, because a team can option or release a pre-arbitration player and non-tender an arbitration one. I average that floored surplus over 199 points of the player's WAR distribution and over his debut-year probabilities, so a riskier player with the same mean is worth a bit more. Expected surplus sums debut-year probability times surplus, so it equals P(MLB) times the surplus if he reaches; a player who never reaches costs nothing. Players already in the majors keep only the control years after 2026. The range is the 10th, 50th and 90th percentile of the same calculation."));
      w.appendChild(table(["Parameter", { t: "Value", n: 1 }, "Unit", "Source and note"],
        M.dollar_params.map(function (d) { return [d.param, d.value >= 1000 ? d.value.toLocaleString() : String(d.value), d.unit, { v: [d.source_url ? h("a", { href: d.source_url, rel: "noopener", text: "source" }) : "no source", ". " + d.note], cls: "wrap-ok" }]; }),
        { label: "Dollar parameters", caption: "Every parameter is pinned to a cited public figure or labeled an assumption." }));
      w.appendChild(h("h3", { text: "Sensitivity to $/WAR growth" }));
      w.appendChild(P("The top of the board is stable but the order moves a little. Expected surplus in $M for the ten highest-ranked players at the base growth rate and at 3% and 7% a year:"));
      w.appendChild(table(["Rank"].concat(M.sensitivity.map(function (x) { return { t: (x.growth * 100).toFixed(2).replace(/\.?0+$/, "") + "% growth" + (x === M.sensitivity[0] ? " (base)" : ""), n: 1 }; })),
        M.sensitivity[0].top.map(function (_, i) { return [String(i + 1)].concat(M.sensitivity.map(function (x) { return x.top[i].name + " " + x.top[i].ev.toFixed(1); })); }),
        { label: "Sensitivity of top 10 to $/WAR growth", caption: "Name and expected surplus ($M), 2026 snapshot." }));
      w.appendChild(table(["Control year", { t: "Mean WAR", n: 1 }, { t: "Share of 6-year WAR", n: 1 }, { t: "n", n: 1 }],
        M.war_profile.map(function (x) { return [String(x.control_year), f2(x.mean_owar), pct(x.share), x.n]; }),
        { label: "WAR control-year profile", caption: "Mean WAR by control year for reached 2005 to 2017 debuts; missing seasons count as zero." }));

      /* assumptions */
      w.appendChild(S("assume", "Assumptions"));
      w.appendChild(h("dl", null,
        dd("Six seasons stand in for control (Q2)", "September call-ups and demotions break the match to real service time, and I do not model options or Super Two (X6)."),
        dd("Dollar economics beyond 2026 are assumptions (Q10)", "The 2026-27 $/WAR is not published, so the 2025-26 figure is the base, grown at the realized FanGraphs rate (about 0.6% a year, 2020 to 2026). The CBA expires in December 2026, so minimum salary and arbitration shares from 2027 on are assumptions, not terms. The 40/60/80 arbitration shares are a rule of thumb; observed averages are lower (about 25/40/62), so my surplus is conservative on arbitration cost. The table below shows how much the growth rate matters."),
        dd("International signees get a generic prior (Q1, X4)", "No free signing bonus source exists, so players without a draft record cluster at a population value and carry a low-confidence flag."),
        dd("Eligibility (Q7)", "Stat projection requires 150+ plate appearances at A or above across two seasons and under 130 MLB at-bats; others fall to the prior."),
        dd("Park factors for MLB use the same method (Q8)", "I did not borrow bWAR's park factors."),
        dd("Benchmark (Q6)", "MLB Pipeline top 100 for 2014 to 2020 stand in for Baseball America, whose full lists are paywalled. Name matching to player IDs rejects ambiguous matches rather than guessing (Q12); unmatched names are dropped."),
        dd("Backtest dollars are approximate (Q10)", "Backtest rows deflate 2026 $/WAR and minimum salary at the same growth rate. I backtest WAR and P(MLB) rankings, not dollar accuracy."),
        dd("Batted-ball data coverage depends on organization (Q14)", "Only AAA and Florida State League Low-A parks are tracked. Cards say when S14 would have applied; it is not applied anywhere."),
        dd("Contact rate gap (Q16)", "2025 swing and whiff data is unavailable, so 2026 contact features use 2026 alone and 2025 snapshots have none. Contact rate survived selection in v1.1 by a margin within noise."),
        dd("Career history before 2005 (Q17)", "MiLB seasons 2000 to 2004 come from the Stats API and feed only career history. Careers that began before 2000 are still partly cut off. Draft records go back to 1990; a player with no record by then is treated as an international signee or undrafted free agent."),
        dd("Data freshness", "API responses are cached; bios and debut dates are as of " + M.people_pulled_on + ". Rerunning with --refresh pulls them again."),
        dd("Height and weight (Q15)", "Both are current values, a mild look-ahead leak. Weight was removed from the model for it; height stays.")));

      /* limits */
      w.appendChild(S("limits", "Limitations"));
      w.appendChild(h("ul", null,
        h("li", { text: "Stats only. No scouting grades, no swing data, no makeup, no injury history. Young high-ceiling players are underrated (the Pipeline backtest shows it)." }),
        h("li", { text: "No minor league defense input. MLB outcomes include fielding, but the model can only infer a prospect's glove from where he plays, so a plus defender at a bat-first position is underrated." }),
        h("li", { text: "P(MLB) under-predicts in the upper-middle deciles on both holdouts; those players are somewhat more likely to reach than shown, likely because later classes reach at higher rates than the 2005 to 2012 training years." }),
        h("li", { text: "Hitters only (X1). No pitchers; two-way players are partly captured." }),
        h("li", { text: "On the 2013 to 2017 holdout the 10th to 90th WAR range covers " + pct(hs.war_q10_q90_coverage, 0) + " of reached stat-group players and " + pct(hp.war_q10_q90_coverage, 0) + " of prior-group players against a nominal 80%; on 2018 to 2019 (fast risers only) " + pct(hs12.war_q10_q90_coverage, 0) + "." }),
        h("li", { text: "Translations remain slightly harsh on the lower level (C10), so a Low-A hitter's MLB-equivalent numbers on his card understate him a little relative to a AAA hitter's." }),
        h("li", { text: "One snapshot per player per year; no in-season refresh (X3). The model is rerun by hand each offseason." }),
        h("li", { text: "Prior-group players (draft-based) are the weakest numbers on the site. They are flagged on the leaderboard and on every card." })));
      w.appendChild(h("p", { style: "margin-top:20px" }, "Jack Huffard. Pipeline run " + M.run_date + ". Questions or corrections are welcome."));
    }).catch(function (e) { chrome("method"); fail(e.message); });
  }
  function dd(t, d) { return h("div", null, h("dt", { text: t }), h("dd", { text: d })); }

  function calibrationChart(dec) {
    var W = 360, H = 300, pad = 40, mx = Math.max.apply(null, dec.map(function (d) { return Math.max(d.predicted, d.observed); })) * 1.05;
    var x = function (v) { return pad + v / mx * (W - pad - 10); }, y = function (v) { return H - pad - v / mx * (H - pad - 10); };
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, width: W, class: "chart fixed", role: "img", "aria-label": "Predicted vs observed P(MLB) by decile, with the 5 point tolerance band" });
    svg.appendChild(s("polygon", { points: [[0, 0.05], [mx - 0.05, mx], [mx, mx], [mx, mx - 0.05], [0.05, 0], [0, 0]].map(function (q) { return x(q[0]) + "," + y(q[1]); }).join(" "), fill: cssv("--accent"), opacity: .08 }));
    svg.appendChild(s("line", { x1: x(0), y1: y(0), x2: x(mx), y2: y(mx), class: "axis", "stroke-dasharray": "4 3" }));
    svg.appendChild(s("line", { x1: x(0), y1: y(0), x2: x(mx), y2: y(0), class: "axis" }));
    svg.appendChild(s("line", { x1: x(0), y1: y(0), x2: x(0), y2: y(mx), class: "axis" }));
    [0, .25, .5, .75, 1].filter(function (t) { return t <= mx; }).forEach(function (t) {
      svg.appendChild(s("text", { x: x(t), y: H - pad + 14, "text-anchor": "middle", text: Math.round(t * 100) + "%" }));
      svg.appendChild(s("text", { x: pad - 4, y: y(t) + 4, "text-anchor": "end", text: Math.round(t * 100) + "%" }));
    });
    svg.appendChild(s("text", { x: W / 2, y: H - 6, "text-anchor": "middle", text: "Predicted P(MLB)" }));
    var yl = s("text", { x: 10, y: H / 2, "text-anchor": "middle", transform: "rotate(-90 10 " + H / 2 + ")", text: "Observed rate" }); svg.appendChild(yl);
    dec.forEach(function (d) {
      svg.appendChild(s("circle", { cx: x(d.predicted), cy: y(d.observed), r: 5, fill: d.pass ? cssv("--pos") : cssv("--neg") }));
    });
    return h("div", null, svg, h("p", { class: "legend" }, h("span", { class: "sw", style: "background:var(--pos)" }), "within 5 points ", h("span", { class: "sw", style: "background:var(--neg);margin-left:10px" }), "outside 5 points; shaded band is the tolerance; dashed line is perfect calibration."));
  }

  var page = document.body.getAttribute("data-page");
  if (page === "index") initIndex(); else if (page === "player") initPlayer(); else if (page === "method") initMethod();
})();
