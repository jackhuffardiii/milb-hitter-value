/* MiLB Player Value: vanilla JS, no dependencies. Pages: index, player, method (body[data-page]). */
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
      h("a", { class: "brand", href: "index.html", text: "MiLB Player Value" }),
      h("span", { class: "muted", text: "Surplus dollars for every A to AAA hitter and pitcher" }),
      h("nav", { "aria-label": "Main" },
        h("a", { href: "index.html", "aria-current": page === "index" ? "page" : null, text: "Leaderboard" }),
        h("a", { href: "trade.html", "aria-current": page === "trade" ? "page" : null, text: "Trade simulator" }),
        h("a", { href: "method.html", "aria-current": page === "method" ? "page" : null, text: "Methodology" }))));
    document.body.insertBefore(head, document.body.firstChild);
    document.body.insertBefore(h("a", { class: "skip", href: "#main", text: "Skip to content" }), document.body.firstChild);
    var L = function (u, t) { return h("a", { href: u, rel: "noopener" }, t); };
    document.body.appendChild(h("footer", { class: "site-foot" }, h("div", { class: "wrap" },
      h("p", null, "Stats-only model by Jack Huffard; not affiliated with MLB. Run date: ", h("span", { class: "num", text: runDate || "unknown" }), through ? "; data through " : "", through ? h("span", { class: "num", text: through }) : "", "."),
      h("p", null, "Data sources:"),
      h("ul", null,
        h("li", null, L("https://github.com/armstjc/milb-data-repository", "armstjc/milb-data-repository"), " (MiLB season batting and pitching 2005 to 2024)"),
        h("li", null, L("https://statsapi.mlb.com", "MLB Stats API"), " (2025 to 2026 MiLB, MLB seasons, bios, draft, park splits)"),
        h("li", null, L("https://baseballsavant.mlb.com/statcast_search/minors", "Baseball Savant minors Statcast"), " (batted-ball context, pitch tracking)"),
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
        sel("f-role", "Players", ["H", "P"], function (x) { return x === "H" ? "Hitters" : "Pitchers"; }),
        sel("f-level", "Level", order.filter(function (x) { return uniq("level").indexOf(x) >= 0; }), LV),
        sel("f-pos", "Position", uniq("pos")),
        sel("f-org", "Organization", uniq("org")),
        sel("f-group", "Group", ["stat", "prior"], function (g) { return g === "stat" ? "Stat-based" : "Draft prior (low confidence)"; }),
        h("label", { class: "chk" }, h("input", { type: "checkbox", id: "f-conf" }), "Hide low confidence"));
      var count = h("p", { class: "count", "aria-live": "polite" });
      var cols = [
        ["rank", "#", 1], ["name", "Player", 0], ["org", "Organization", 0], ["level", "Level", 0], ["age", "Age", 1], ["pos", "Pos", 0],
        ["mlb_pos", "Proj. MLB role", 0], ["p_mlb", "P(MLB)", 1], ["war", "WAR (6 yr)", 1], ["eta", "ETA (yrs)", 1], ["ev", "Expected surplus", 1], ["q10", "10th (if MLB)", 1], ["q90", "90th (if MLB)", 1]
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
        h("table", null, h("caption", { text: "2026 hitters and pitchers, A through AAA, including rookie-eligible players who already debuted. Expected surplus is P(MLB) times the surplus if he reaches MLB, in millions of dollars. Pos is RHP or LHP for pitchers; their projected role is SP or RP." }), h("thead", null, thead), tbody));
      main.appendChild(h("div", { class: "wrap" },
        h("h1", { style: "margin-top:24px", text: "2026 leaderboard" }),
        h("p", { class: "lede" }, "Every A through AAA hitter and pitcher on one scale, ranked by expected surplus dollars over six years of team control. Use the Players filter to rank pitchers among pitchers. Open a player for the full trace from minor league line to dollars. ",
          h("a", { href: "method.html", text: "How this works, and where it fails." })),
        ctrl, count, tbl, more));
      var val = function (id) { return document.getElementById(id).value; };
      function filtered() {
        var t = q.value.trim().toLowerCase(), ro = val("f-role"), lv = val("f-level"), ps = val("f-pos"), og = val("f-org"), gp = val("f-group"), hide = document.getElementById("f-conf").checked;
        return rows.filter(function (r) {
          return (!t || r.name.toLowerCase().indexOf(t) >= 0) && (!ro || r.role === ro || (r.role === "2W")) && (!lv || r.level === lv) && (!ps || r.pos === ps) && (!og || r.org === og) && (!gp || r.group === gp) && (!hide || !r.low_conf);
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

  /* card pieces shared by hitter and pitcher cards */
  function driversBlock(p) {
    var two = h("div", { class: "two" });
    [["p_mlb", "Reach probability (log-odds)"], ["war", "Six-year WAR if he reaches (wins)"]].forEach(function (t) {
      var L = p.drivers[t[0]], mx = Math.max.apply(null, L.map(function (x) { return Math.abs(x.c); }).concat([0.001]));
      two.appendChild(h("div", null, h("h3", { text: t[1] }), L.length ? h("ol", { class: "drv", "aria-label": t[1] + " drivers" }, L.map(function (x) {
        return h("li", null, h("div", { class: "fam" }, h("span", { text: x.family }), h("span", { class: "num " + (x.c < 0 ? "neg" : ""), text: (x.c > 0 ? "+" : "") + num(x.c, 2) })),
          divBar(x.c, mx), h("div", { class: "ph", style: x.sup ? "font-style:italic" : null, text: x.phrase }));
      })) : h("p", { class: "muted", text: "No drivers available." })));
    });
    return [h("h3", { text: "What drives the projection" }),
      h("p", { class: "explain", text: "The model's inputs grouped into families. Blue pushes the projection up, orange pushes it down, sorted by size. Linear terms overlap, so read the family total, not single features. Italic phrases carry no direction: the family total also reflects trend and regressed values." }), two];
  }

  function answerBlock(p, why) {
    var s_ = p.surplus;
    return h("section", { class: "answer", "aria-labelledby": "h-answer" },
      h("h2", { id: "h-answer", style: "margin:0 0 8px;font-size:15px;font-family:var(--sans);font-weight:600", text: "Expected surplus value" }),
      h("div", { class: "big num" }, usd(s_.ev), h("small", { text: p.in_mlb ? "already in MLB; remaining control years only" : "P(MLB) " + pct(p.p_mlb, 0) + " times " + usd(s_.if_mlb) + " if he reaches MLB" })),
      rangeStrip({ q10: s_.q10, q50: s_.q50, q90: s_.q90, mean: s_.if_mlb, label: "Surplus if he reaches MLB: 10th " + usd(s_.q10) + ", median " + usd(s_.q50) + ", 90th " + usd(s_.q90) + ", mean " + usd(s_.if_mlb), fmt: function (v) { return usd(v, 0); } }),
      why);
  }

  function outlookBlock(p, prof) {
    var s2 = sec("h-war", "Outlook");
    s2.appendChild(h("dl", { class: "kv" },
      h("div", null, h("dt", { text: "P(MLB)" }), h("dd", { class: "num", text: pct(p.p_mlb, 1) })),
      h("div", null, h("dt", { text: "6-year WAR, mean" }), h("dd", { class: "num", text: num(p.war.mean, 1) })),
      h("div", null, h("dt", { text: "6-year WAR, median" }), h("dd", { class: "num", text: num(p.war.q50, 1) })),
      h("div", null, h("dt", { text: "ETA, mean" }), h("dd", { class: "num" }, p.eta ? [num(p.eta.mean, 1), h("small", { text: " yrs" })] : "in MLB"))));
    s2.appendChild(h("h3", { text: "Six-year WAR if he reaches MLB" }));
    s2.appendChild(rangeStrip({ q10: p.war.q10, q50: p.war.q50, q90: p.war.q90, mean: p.war.mean, label: "6-year WAR if he reaches MLB: 10th " + num(p.war.q10) + ", median " + num(p.war.q50) + ", 90th " + num(p.war.q90), fmt: function (v) { return num(v, 1); } }));
    var wy = prof && warByYear(p, prof); if (wy) s2.appendChild(wy);
    s2.appendChild(h("h3", { text: "Debut year" }));
    if (p.eta) {
      var items = Object.keys(p.eta.debut).sort().map(function (y) { return { k: y, v: p.eta.debut[y] }; });
      s2.appendChild(barChart(items, "Probability of debut by year: " + items.map(function (i) { return i.k + " " + Math.round(i.v * 100) + "%"; }).join(", ")));
      s2.appendChild(h("p", { class: "legend", text: "ETA 10th to 90th percentile: " + num(p.eta.q10, 0) + " to " + num(p.eta.q90, 0) + " years." }));
    } else s2.appendChild(h("p", { class: "muted", text: "Debuted " + p.in_mlb.debut + "." }));
    return s2;
  }

  /* ---------- player card ---------- */
  function sec(id, title) {
    return h("section", { "aria-labelledby": id }, h("h2", { id: id, text: title }));
  }
  var COMP = { K: "Strikeout rate", BB: "Walk rate", ISO: "Isolated power", BABIP: "BABIP" };

  function initPlayer() {
    var main = document.getElementById("main");
    var id = new URLSearchParams(location.search).get("id");
    if (!/^\d+$/.test(id || "")) { chrome("player"); main.appendChild(h("div", { class: "wrap" }, h("div", { class: "err" }, "No player selected. ", h("a", { href: "index.html", text: "Pick one from the leaderboard." })))); return; }
    Promise.all([load("data/players/" + id + ".json"), load("data/method.json").catch(function () { return null; })]).then(function (pm) {
      var p = pm[0], prof = pm[1] && pm[1].war_profile;
      chrome("player", p.run_date, p.data_through);
      document.title = p.name + " | MiLB Player Value";
      if (p.kind === "pitcher") return renderPitcher(p, pm[1] && pm[1].pitchers && pm[1].pitchers.war_profile);
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

      /* 1. value: the number up front; how we got it sits behind "Show more" */
      var s_ = p.surplus;
      var why = h("details", { class: "why" }, h("summary", { text: "Show more: how we got this value" }),
        h("p", { class: "explain" }, "Dollars of value above what the team pays, over six years of control, discounted to 2026. Each year's surplus floors at zero, since a team can option, release or non-tender a player who does not produce, so a wider range of outcomes adds value. " + (p.in_mlb ? "Over his remaining control years" : "If he reaches MLB") + " the 10th to 90th percentile range is " + usd(s_.q10) + " to " + usd(s_.q90) + "; the median is " + usd(s_.q50) + "."),
        h("p", { class: "legend" }, "Range is conditional on reaching MLB. The triangle is the mean; the bar is the 10th to 90th range and the tick is the median. Outcomes are right-skewed, so the median sits below the mean. WAR is ours, with MLB fielding from Baseball-Reference; debut bars come from a hazard model and sum to P(MLB)."));

      add(why, driversBlock(p));

      /* rate chain */
      why.appendChild(h("h3", { text: "From the box score to the model input" }));
      why.appendChild(h("p", { class: "explain", text: "Each rate goes through four steps: the raw 2026 line, adjusted for the home park, translated to an MLB-equivalent (MLE), then regressed toward his league's average by sample size. Park factor 1.00 is neutral. BABIP is shown for context only; it is not a model input." }));
      if (p.chain.length) {
        var rows = [];
        p.chain.forEach(function (c) {
          ["K", "BB", "ISO", "BABIP"].forEach(function (k, i) {
            var pf = c.park ? (k === "K" ? c.park.SO : k === "BB" ? c.park.BB : k === "BABIP" ? c.park.BABIP : "2B/3B " + num(c.park.B2B3B, 2) + ", HR " + num(c.park.HR, 2)) : null;
            var f = k === "ISO" || k === "BABIP" ? rate : function (x) { return pct(x, 1); };
            rows.push([{ v: i === 0 ? LV(c.level) : "", cls: "lvl" }, COMP[k], i === 0 ? c.PA : "", f(c[k][0]), f(c[k][1]), f(c[k][2]), f(c[k][3]), typeof pf === "number" ? num(pf, 2) : (pf || "n/a")]);
          });
        });
        why.appendChild(table(["Level", "Rate", { t: "PA", n: 1 }, { t: "Raw", n: 1 }, { t: "Park-neutral", n: 1 }, { t: "MLE", n: 1 }, { t: "Regressed", n: 1 }, "Park factor"],
          rows, { label: "Rate chain by level", caption: "2026 rates by level. MLE and regressed are on the MLB scale." }));
        if (p.blend) {
          why.appendChild(h("p", { class: "explain" }, "Model input across levels (3:2 weighted blend of 2026 and 2025 regressed MLEs, 2026 alone when 2025 is missing): K " + pct(p.blend.K) + ", BB " + pct(p.blend.BB) + ", ISO " + rate(p.blend.ISO) + ". Single-season regressed (across levels): K " + pct(p.blend.reg_K) + ", BB " + pct(p.blend.reg_BB) + ", ISO " + rate(p.blend.reg_ISO) + "." + (p.blend.contact != null ? " Contact rate (1 minus whiffs per swing, A to AAA): " + pct(p.blend.contact) + "." : "")));
        }
      } else why.appendChild(h("p", { class: "muted", text: "No A through AAA rate chain for 2026 (Rookie-level or too few plate appearances). The projection comes from the prior." }));
      why.appendChild(h("p", { class: "legend", text: "Batted-ball data is display only. An adjustment that swaps observed ISO and BABIP for expected values from it (S14) was tested and not applied. Height enters the model; weight does not, because current listed weight leaks information from after the snapshot. Position probabilities come from the 2005 to 2017 transition matrix and feed the positional adjustment in WAR. S14 applied to this card: " + (p.s14_applied ? "yes" : "no") + "." }));

      w.appendChild(answerBlock(p, why));
      w.appendChild(outlookBlock(p, prof));

      /* 3. stats */
      var s3 = sec("h-stats", "Stats");
      var hist = p.hist.map(function (x) { return [String(x.season), LV(x.level), x.G, x.PA, rate(x.AVG), rate(x.OBP), rate(x.SLG), pct(x.K), pct(x.BB), rate(x.ISO), rate(x.BABIP)]; });
      s3.appendChild(table(["Season", "Level", { t: "G", n: 1 }, { t: "PA", n: 1 }, { t: "AVG", n: 1 }, { t: "OBP", n: 1 }, { t: "SLG", n: 1 }, { t: "K%", n: 1 }, { t: "BB%", n: 1 }, { t: "ISO", n: 1 }, { t: "BABIP", n: 1 }],
        hist, { label: "Level history", caption: "Last three seasons, as played." }));
      s3.appendChild(h("h3", { text: "By pitcher hand" }));
      if (p.hand && p.hand.length) {
        s3.appendChild(table(["Season", "Level", "Vs", { t: "PA", n: 1 }, { t: "AVG", n: 1 }, { t: "OBP", n: 1 }, { t: "SLG", n: 1 }, { t: "ISO", n: 1 }, { t: "K%", n: 1 }, { t: "BB%", n: 1 }],
          p.hand.map(function (x) { return [String(x.season), LV(x.level), x.hand, x.PA, rate(x.AVG), rate(x.OBP), rate(x.SLG), rate(x.ISO), pct(x.K), pct(x.BB)]; }),
          { label: "Splits by pitcher hand", caption: "Last three seasons, vs left- and right-handed pitchers." }));
      } else s3.appendChild(h("p", { class: "muted", text: "No handedness splits available." }));
      s3.appendChild(h("h3", { text: "By pitch type" }));
      if (p.pitch && p.pitch.length) {
        s3.appendChild(table(["Season", "Pitch", { t: "Pitches", n: 1 }, { t: "Seen%", n: 1 }, { t: "PA", n: 1 }, { t: "AVG", n: 1 }, { t: "SLG", n: 1 }, { t: "wOBA", n: 1 }, { t: "Whiff%", n: 1 }, { t: "Avg EV", n: 1 }, { t: "EV90", n: 1 }],
          p.pitch.map(function (x) { return [String(x.season), x.family, x.n, pct(x.share, 0), x.PA, rate(x.AVG), rate(x.SLG), rate(x.wOBA), pct(x.whiff), x.ev == null ? "n/a" : num(x.ev, 1) + " mph", x.ev90 == null ? "n/a" : num(x.ev90, 1) + " mph"]; }),
          { label: "Splits by pitch type", caption: "Statcast, tracked AAA and Low-A Florida State League parks only. Fastball: four-seam, sinker, cutter. Breaking: slider, sweeper, curveball. Offspeed: changeup, splitter." }));
      } else s3.appendChild(h("p", { class: "muted", text: "Not tracked: no pitches seen at AAA or Low-A Florida State League parks in 2024 to 2026." }));
      s3.appendChild(h("h3", { text: "Batted ball" }));
      if (p.batted.length) {
        s3.appendChild(table(["Season", "Level", { t: "Tracked BIP", n: 1 }, { t: "Avg EV", n: 1 }, { t: "EV90", n: 1 }, { t: "Hard-hit%", n: 1 }, { t: "Avg LA", n: 1 }, { t: "Sweet-spot%", n: 1 }, { t: "Barrel%", n: 1 }],
          p.batted.map(function (x) { return [String(x.season), LV(x.level), x.n, num(x.ev, 1) + " mph", num(x.ev90, 1) + " mph", pct(x.hh), num(x.la, 1) + "°", pct(x.sweet), pct(x.barrel)]; }), { label: "Batted-ball metrics", caption: "Statcast, tracked at AAA and Low-A Florida State League parks only." }));
      } else s3.appendChild(h("p", { class: "muted", text: "Not tracked: no batted balls at AAA or Low-A Florida State League parks in 2025 or 2026." }));
      w.appendChild(s3);

      /* 4. positions */
      var s4 = sec("h-pos", "Projected MLB position");
      s4.appendChild(h("ul", { class: "drv", "aria-label": "Position probabilities" }, p.pos_probs.map(function (x) {
        var svg = s("svg", { viewBox: "0 0 300 12", class: "chart", "aria-hidden": "true", style: "max-height:14px" });
        svg.appendChild(s("rect", { x: 0, y: 1, width: Math.max(1, x[1] * 300), height: 10, fill: cssv("--accent") }));
        return h("li", null, h("div", { class: "fam" }, h("span", { text: POSS[x[0]] || x[0] }), h("span", { class: "num", text: pct(x[1], 0) })), svg);
      })));
      w.appendChild(s4);

      w.appendChild(h("p", { class: "explain", style: "margin-top:24px" }, h("a", { href: "index.html", text: "Back to leaderboard" }), " or read the ", h("a", { href: "method.html", text: "methodology" }), "."));
    }).catch(function (e) { chrome("player"); fail(e.message); });
  }

  /* ---------- pitcher card ---------- */
  var PCOMP = { K: "Strikeout rate", BB: "Walk rate (no IBB)", HR: "Home run rate", GB: "Ground-ball rate", XB: "Extra bases per ball in play" };
  var PT = { FF: "Four-seam", SI: "Sinker", FC: "Cutter", FA: "Fastball", SL: "Slider", ST: "Sweeper", SV: "Slurve", CU: "Curveball", KC: "Knuckle curve",
    CS: "Slow curve", CH: "Changeup", FS: "Splitter", FO: "Forkball", SC: "Screwball", KN: "Knuckleball", EP: "Eephus" };

  function renderPitcher(p, prof) {
    var main = document.getElementById("main");
    var w = h("div", { class: "wrap" }); main.appendChild(w);
    var b = p.bio, ro = p.role;
    var ht = b.height_in ? Math.floor(b.height_in / 12) + "'" + (b.height_in % 12) + '"' : null;
    w.appendChild(h("div", { class: "card-head" }, h("h1", { text: p.name }), h("span", { class: "muted" }, "Rank " + p.rank + " of " + p.n_ranked.toLocaleString() + " (hitters and pitchers)")));
    w.appendChild(h("p", { class: "sub" }, [p.org, p.team, LV(p.level), "age " + num(p.age, 1), b.throws ? (b.throws === "L" ? "left" : "right") + "-handed pitcher" : "pitcher", ht].filter(Boolean).join(", ")));
    if (p.low_conf) w.appendChild(h("p", { class: "note", role: "note" }, h("b", { text: "Low confidence. " }),
      "Too few batters faced at A or above for the stat model, so the numbers come from a draft-based prior (draft round, pick, age, level, batters faced, high school or college). Treat the range as wide and the middle as soft."));
    if (p.in_mlb) w.appendChild(h("p", { class: "note", role: "note" }, h("b", { text: "Already in MLB. " }),
      "He debuted on " + p.in_mlb.debut + " and is still rookie-eligible, so P(MLB) is 1 and his control clock is running: " + p.in_mlb.control_years_left + " control year" + (p.in_mlb.control_years_left === 1 ? "" : "s") + " remain from 2027."));
    if (p.il) w.appendChild(h("p", { class: "note", role: "note" }, h("b", { text: "Injured list in 2026. " }),
      p.il.count + " placement" + (p.il.count === 1 ? "" : "s") + (p.il.max_days ? ", longest " + p.il.max_days + " days" : "") + ". Shown for context; injuries are not a model input."));

    var why = h("details", { class: "why" }, h("summary", { text: "Show more: how we got this value" }),
      h("p", { class: "explain" }, "Dollars of value above what the team pays, over six years of control, discounted to 2026. Each year's surplus floors at zero. Pitcher WAR is ours, anchored so pitchers earn 41% of all WAR, with starter and reliever replacement levels set per appearance."),
      h("p", { class: "legend" }, "Range is conditional on reaching MLB. The triangle is the mean; the bar is the 10th to 90th range and the tick is the median."));
    add(why, driversBlock(p));
    why.appendChild(h("h3", { text: "From the box score to the model input" }));
    why.appendChild(h("p", { class: "explain", text: "Each rate goes through four steps: the raw 2026 line, adjusted for the home park, translated to an MLB-equivalent (MLE) with pitchers who moved between levels, then regressed toward his league's average by sample size. Ground-ball rate is outs-based (ground outs over ground plus air outs), the only definition every source shares." }));
    if (p.chain.length) {
      var rows = [];
      p.chain.forEach(function (c) {
        ["K", "BB", "HR", "GB", "XB"].forEach(function (k, i) {
          var f = k === "XB" ? rate : function (x) { return pct(x, 1); };
          rows.push([{ v: i === 0 ? LV(c.level) : "", cls: "lvl" }, PCOMP[k], i === 0 ? c.BF : "", f(c[k][0]), f(c[k][1]), f(c[k][2]), f(c[k][3])]);
        });
      });
      why.appendChild(table(["Level", "Rate", { t: "BF", n: 1 }, { t: "Raw", n: 1 }, { t: "Park-neutral", n: 1 }, { t: "MLE", n: 1 }, { t: "Regressed", n: 1 }], rows,
        { label: "Rate chain by level", caption: "2026 rates by level. MLE and regressed are on the MLB scale." }));
    } else why.appendChild(h("p", { class: "muted", text: "No A through AAA rate chain for 2026. The projection comes from the prior." }));
    if (p.blend) why.appendChild(h("p", { class: "explain" }, "Model inputs (3:2 blend of 2026 and 2025 regressed MLEs): K " + pct(p.blend.K) + ", BB " + pct(p.blend.BB) + ", HR " + pct(p.blend.HR) + ", GB " + pct(p.blend.GB) + ", extra bases per ball in play " + rate(p.blend.XB) +
      (p.contact && p.blend.XB_box != null && p.blend.XB !== p.blend.XB_box ? " (box score " + rate(p.blend.XB_box) + "; replaced by his tracked quality of contact, xwOBA on contact " + rate(p.contact.xwoba) + " over " + p.contact.bip + " balls in play)" : "") + "."));
    why.appendChild(h("p", { class: "legend", text: "mERA, P(SP) and the arsenal are display only. mERA was tested as a model input and did not improve it. Weight is not an input: current listed weight leaks information from after the snapshot." }));
    w.appendChild(answerBlock(p, why));
    w.appendChild(outlookBlock(p, prof));

    var sR = sec("h-role", "Role and run prevention");
    sR.appendChild(h("dl", { class: "kv" },
      h("div", null, h("dt", { text: "Projected MLB role" }), h("dd", { text: ro.proj ? (ro.proj === "SP" ? "Starter" : "Reliever") : "n/a" })),
      h("div", null, h("dt", { text: "P(starter)" }), h("dd", { class: "num", text: ro.p_sp == null ? "n/a" : pct(ro.p_sp, 0) })),
      h("div", null, h("dt", { text: "2026 starts share" }), h("dd", { class: "num", text: pct(ro.gs_share, 0) })),
      h("div", null, h("dt", { text: "2026 IP per game" }), h("dd", { class: "num", text: num(ro.ip_per_g, 1) }))));
    sR.appendChild(h("p", { class: "legend", text: "P(starter) is the chance he starts most of his games in his first two MLB seasons, from a logistic model of 2016 to 2025 debuts on role, stuff proxies (K, BB, GB), age and level." }));
    if (p.mera) {
      var lad = ["a", "a+", "aa", "aaa"].filter(function (k) { return p.mera.ladder[k] != null; });
      sR.appendChild(h("h3", { text: "Projected mERA (MLB-equivalent runs per nine)" }));
      sR.appendChild(table(["", { t: "mERA", n: 1 }], [["Next season, MLB scale", num(p.mera.mera, 2)]].concat(lad.map(function (k) { return ["Projected next season at " + LV(k), num(p.mera.ladder[k], 2)]; })),
        { label: "mERA ladder", caption: "Projections from his translated strikeout, walk, ground-ball and contact rates. The ladder shows what he would project to allow next season at each level from his own up." }));
    }
    w.appendChild(sR);

    var sA = sec("h-ars", "Arsenal");
    if (p.arsenal.length) {
      sA.appendChild(table(["Season", "Pitch", { t: "Pitches", n: 1 }, { t: "Usage", n: 1 }, { t: "Velo", n: 1 }, { t: "Spin", n: 1 }, { t: "IVB", n: 1, title: "Induced vertical break, inches" }, { t: "HB", n: 1, title: "Horizontal break, inches, arm side positive" }, { t: "Ext.", n: 1, title: "Release extension, feet" }, { t: "Whiff%", n: 1 }],
        p.arsenal.map(function (x) { return [String(x.season), PT[x.type] || x.type, x.n, pct(x.usage, 0), num(x.velo, 1), x.spin == null ? "n/a" : String(x.spin), num(x.ivb, 1), num(x.hb, 1), num(x.ext, 1), pct(x.whiff)]; }),
        { label: "Arsenal by pitch type", caption: "Statcast, tracked AAA and Low-A Florida State League parks only. Movement in inches; horizontal break is positive toward his arm side." }));
    } else sA.appendChild(h("p", { class: "muted", text: "Not tracked: no pitches at AAA or Low-A Florida State League parks in 2025 or 2026." }));
    w.appendChild(sA);

    var s3 = sec("h-stats", "Stats");
    s3.appendChild(table(["Season", "Level", { t: "G", n: 1 }, { t: "GS", n: 1 }, { t: "IP", n: 1 }, { t: "BF", n: 1 }, { t: "K%", n: 1 }, { t: "BB%", n: 1 }, { t: "HR%", n: 1 }, { t: "GB%", n: 1 }, { t: "BABIP", n: 1 }, { t: "RA9", n: 1 }],
      p.hist.map(function (x) { return [String(x.season), LV(x.level), x.G, x.GS, num(x.IP, 1), x.BF, pct(x.K), pct(x.BB), pct(x.HR), pct(x.GB), rate(x.BABIP), num(x.RA9, 2)]; }),
      { label: "Level history", caption: "Last three seasons, as pitched. BB% excludes intentional walks." }));
    w.appendChild(s3);
    w.appendChild(h("p", { class: "explain", style: "margin-top:24px" }, h("a", { href: "index.html", text: "Back to leaderboard" }), " or read the ", h("a", { href: "method.html", text: "methodology" }), "."));
  }

  /* ---------- methodology ---------- */
  function initMethod() {
    var main = document.getElementById("main");
    load("data/method.json").then(function (M) {
      chrome("method", M.run_date, M.data_through);
      var w = h("div", { class: "wrap narrow prose" }); main.appendChild(w);
      var P = function (t) { return h("p", null, t); };
      var r2 = function (x) { return x.toFixed(2).replace(/^0\./, "."); }, r3 = function (x) { return x.toFixed(3).replace(/^0\./, "."); };
      var n = function (x) { return x.toLocaleString(); };
      var dp = {}; M.dollar_params.forEach(function (d) { dp[d.param] = d.value; });
      var C2 = M.C2.primary_excl_censored, C3 = M.C3.primary_excl_censored, L12 = M.C12.lists_2019_2020_vs_war_thru_2026;
      var p2 = C2.pooled, p12 = L12.pooled, fresh = M.holdout.stat_fit2017.all, cov = M.coverage;
      var fy = M.C12.ev_vs_war_thru_2026.all, fyk = Object.keys(fy);
      var freshBase = fyk.reduce(function (a, k) { return a + fy[k].logloss_baseline * fy[k].n; }, 0) / fyk.reduce(function (a, k) { return a + fy[k].n; }, 0);
      var low = M.C4.deciles.filter(function (d) { return !d.pass; });
      var c10fail = 0; Object.keys(M.C10).forEach(function (st) { ["K", "BB", "ISO", "BABIP"].forEach(function (k) { if (!M.C10[st][k].pass) c10fail++; }); });

      w.appendChild(h("h1", { style: "margin-top:24px", text: "Methodology" }));
      w.appendChild(h("p", { class: "lede" }, "This project puts a surplus dollar value on every hitter and pitcher from Low-A through AAA using only what shows up in the stat line: production, age, and level. It clearly beats a naive baseline, it trails MLB Pipeline on the lists I could fully score, and it is built to complement scouting, not replace it."));
      w.appendChild(h("ul", { class: "toc", "aria-label": "Sections" }, [["how", "How it works"], ["results", "How well it works"], ["pitchers", "Pitchers"], ["limits", "What it misses"]].map(function (x) { return h("li", null, h("a", { href: "#" + x[0], text: x[1] })); })));

      /* how it works */
      w.appendChild(h("h2", { id: "how", text: "How it works" }));
      w.appendChild(P("The question is simple: what is a minor league hitter worth to his organization over his six years of team control? I answer it in four steps."));

      w.appendChild(h("h3", { text: "1. Put every stat line on the same scale" }));
      w.appendChild(P("A .280 hitter in the Pacific Coast League and a .280 hitter in the Florida State League are not the same player. I adjust each line for its home park using home and road splits, then translate it into MLB-equivalent strikeout, walk, and power rates using players who moved between levels. Because players tend to get promoted right after a hot stretch, I also use full-season pairs across years so the timing of promotions does not skew the translations. Each rate is then regressed toward league average based on sample size."));

      w.appendChild(h("h3", { text: "2. Define what success looks like" }));
      w.appendChild(P("The target is WAR over a player's first six MLB seasons, the years his team controls him. I built my own WAR from batting runs, baserunning, a positional adjustment, and replacement level, borrowing only fielding runs from Baseball-Reference. It correlates with bWAR at r = " + r2(M.C1.r_owar_bwar) + " across " + n(M.C1.n) + " player-seasons with 300 or more plate appearances."));

      w.appendChild(h("h3", { text: "3. Project whether he makes it and what he does once he gets there" }));
      w.appendChild(P("Two models carry the projection. The first estimates a player's chance of debuting in each season after the snapshot, which together give his probability of reaching MLB and when he is likely to arrive. The second projects his six-year WAR if he reaches, along with a range, since prospect outcomes are heavily right-skewed. For each, I chose between a regularized linear model and LightGBM using cross-validation grouped by player. I picked the WAR model on rank correlation rather than error, because valuing prospects is ultimately a ranking problem."));
      w.appendChild(P("Inputs are the translated rates, age relative to level, highest level reached, projected MLB position, and playing time. Scouting grades and prospect rankings are never inputs. Hitters without at least 150 plate appearances at A or above over two seasons (" + n(cov.prior) + " of the " + n(cov.players_2026) + " scored in 2026) fall back to a projection based on their draft position and are flagged as low confidence."));

      w.appendChild(h("h3", { text: "4. Convert WAR to dollars" }));
      w.appendChild(P("Surplus value is what the projected WAR would cost on the free-agent market minus what the team actually pays him, discounted to today at " + Math.round(dp.discount_rate * 100) + "% a year. I price a win at $" + (dp.dollars_per_war_2026 / 1e6).toFixed(1) + "M (FanGraphs' figure for the 2025-26 free-agent class), pay the league minimum in years one through three, and pay " + [dp.arb_share_year1, dp.arb_share_year2, dp.arb_share_year3].map(function (x) { return Math.round(x * 100); }).join(", ").replace(/, (\d+)$/, ", and $1") + " percent of market value in the three arbitration years. Each year's surplus floors at zero, since a team can always option, release, or non-tender a player who is not worth his salary. Because of that floor, a riskier player is worth slightly more than a safer one with the same average projection. The final number is weighted by the chance he ever reaches the majors."));

      /* results */
      w.appendChild(h("h2", { id: "results", text: "How well it works" }));
      w.appendChild(P("I made every modeling decision on 2005 to 2012 data. 2005 is where my minor league data begins, and stopping at 2012 means nearly every player in the training set has had time to either play out his first six MLB seasons or wash out, so the model learns from finished careers rather than ones still in progress. It also leaves later classes untouched for testing. I then scored two holdout periods once each: 2013 to 2017, and a fresh 2018 to 2019 set that no version of the model had seen. The test I weight most is the comparison to MLB Pipeline's top 100 lists, since that is the bar any prospect model has to clear."));
      w.appendChild(h("ul", { class: "results" },
        h("li", null, h("b", { text: "Beats a naive baseline" }), "On the 2013 to 2017 holdout, log loss for reaching MLB of " + r3(C3.logloss_model) + " vs " + r3(C3.logloss_baseline) + " for a baseline built on age, level, and OPS (n = " + n(C3.n) + ")."),
        h("li", null, h("b", { text: "Holds up on fresh data" }), "On 2018 to 2019, AUC of " + r2(fresh.auc) + " and log loss of " + r3(fresh.logloss) + " vs " + r3(freshBase) + " for the baseline (n = " + n(fresh.n) + "). Its WAR rankings there are only even with the baseline so far, with most of those careers still in progress."),
        h("li", { class: p2.diff_ci90_boot2000[1] < 0 ? "bad" : null }, h("b", { text: "Trails Pipeline on the 2014 to 2018 lists" }), "Rank correlation with six-year WAR of " + r2(p2.spearman_model) + " for the model vs " + r2(p2.spearman_list) + " for Pipeline (n = " + C2.n + ")."),
        h("li", null, h("b", { text: "Ahead of Pipeline on the 2019 and 2020 lists" }), "Rank correlation with WAR through 2026 of " + r2(p12.spearman_model) + " for the model vs " + r2(p12.spearman_list) + " for Pipeline (n = " + L12.n + "). That window is shorter and rewards quick arrival, and the sample is small, so I read it as encouraging rather than proof.")));
      w.appendChild(P("Trailing Pipeline on the full six-year test was the expected result. Hitters on a top 100 list have already passed a scouting screen, and the model knows nothing about tools, swing decisions, or makeup. Where it adds value is breadth: it puts a dollar value and a range on all " + n(cov.players_2026) + " hitters, including the thousands no list covers, and gives a consistent, stat-based check against how a player is ranked."));

      /* pitchers (v2) */
      var X = M.pitchers;
      if (X) {
        var P3 = X.c3, h13 = X.holdout_2013_17.stat, c12y = Object.keys(X.c12), bd = X.c19.board;
        w.appendChild(h("h2", { id: "pitchers", text: "Pitchers" }));
        w.appendChild(P("Pitchers go through the same four steps with their own pieces. Strikeout, walk, hit-by-pitch, home run, ground-ball and extra-base rates are park-adjusted and translated to MLB equivalents with pitchers who moved between levels. Pitcher WAR is built from those components and anchored so pitchers earn 41% of all WAR and hitters 59%, the Baseball-Reference split, which puts both on one dollar scale. Starters and relievers get separate replacement levels per appearance, and relief innings are scaled by leverage. The models are fit separately from the hitter models; cross-validation picked a regularized linear model for both reaching MLB and WAR."));
        w.appendChild(P("Role enters through starts share, innings per game and pitches per game. For pitchers tracked by Statcast, the extra-base rate is replaced by one implied by xwOBA on contact, which predicted next season's contact damage better than the box score did (RMSE " + X.c17.rmse_xwoba_only.toFixed(4).replace(/^0/, "") + " vs " + X.c17.rmse_observed.toFixed(4).replace(/^0/, "") + ", n = " + n(X.c17.n) + "). A Bayesian run-prevention estimate, mERA, was tested as an input and dropped: it improved reach-probability log loss by " + X.c15.mera_cv.d_logloss_gain.toFixed(4) + " but made the value ranking slightly worse, so it is shown on cards only. P(starter) is display only too (AUC " + r2(X.psp.oof_auc) + " on " + n(X.psp.n) + " debuts)."));
        w.appendChild(h("ul", { class: "results" },
          h("li", null, h("b", { text: "Beats a naive baseline on 2013 to 2017" }), "Log loss " + r3(P3.logloss_model) + " vs " + r3(P3.logloss_baseline) + " for age, level and K-BB%, and value-ranking correlation " + r3(P3.spearman_model) + " vs " + r3(P3.spearman_baseline) + " (n = " + n(P3.n) + "; AUC " + r2(h13.auc) + ")."),
          h("li", null, h("b", { text: "Even with Pipeline on the 2014 to 2018 lists" }), "Rank correlation with six-year WAR of " + r2(X.c2.spearman_model) + " for the model vs " + r2(X.c2.spearman_list) + " for Pipeline's top 100 pitchers (n = " + X.c2_n + ")."),
          h("li", { class: "bad" }, h("b", { text: "Weaker on 2018 and 2019" }), "It still beats the baseline on log loss, but its value ranking trails it (" + c12y.map(function (y) { return y + ": " + r3(X.c12[y].spearman_model) + " vs " + r3(X.c12[y].spearman_baseline); }).join("; ") + "), and Pipeline beat it on the 2019 and 2020 lists (" + r2(X.c12_lists.spearman_model) + " vs " + r2(X.c12_lists.spearman_list) + ", n = " + X.c12_lists_n + "). Recent seasons differ from the training years: starters throw fewer innings and minor league walk rates jumped with the automated strike zone.")));
        w.appendChild(P("On the combined 2026 board, pitchers rank low: " + (bd.top50_roles.P || 0) + " of the top 50 and " + (bd.top100_roles.P || 0) + " of the top 100. Debuting pitchers and hitters produce similar six-year WAR on average, but pitcher outcomes are harder to call from a stat line, so even the model's best pitchers carry less expected WAR than its best hitters. Straightening out the walk-rate drift or recalibrating the WAR model did not change that. Use the Players filter to rank pitchers against each other; the hitter/pitcher WAR split barely matters (" + bd.n.toLocaleString() + " players; top 50 unchanged at a 57/43 or 61/39 split)."));
      }

      /* trades (v3 draft) */
      var V = M.v3;
      if (V) {
        var c24 = V.c24.holdout, inf = V.c26.informational_2026_from_jul1 || {};
        w.appendChild(h("h2", { id: "trades", text: "Major leaguers and trades (draft)" }));
        w.appendChild(P("The trade simulator puts " + n(V.n_mlb) + " players on 2026 40-man rosters on the same surplus scale as the prospects. Each major leaguer's WAR is projected six seasons out: a weighted average of his last three seasons of our WAR, pulled toward league average by playing time, aged with a curve fit to our own WAR since 2006. Each season is then priced against what he will actually be paid: guaranteed salary from his contract, an arbitration estimate, or the league minimum. Options are exercised when that side benefits. Pre-arbitration and arbitration years floor at zero, because a club can non-tender a player; guaranteed money does not, because the club owes it."));
        w.appendChild(P("The arbitration estimate is a model trained on real arbitration salaries since 2011. On salaries from 2021 on, which it never saw, its median miss is " + Math.round(c24.model.median_abs_pct_err * 100) + "%, against " + Math.round(c24.baseline.median_abs_pct_err * 100) + "% for the simple 40/60/80% of market value rule the prospect values still use."));
        if (inf.fully_valued) w.appendChild(P("As a rough check, " + n(inf.fully_valued) + " two-team trades made after July 1, 2026 involved only players the model values. The median gap between the two sides was $" + inf.median_gap_m.toFixed(1) + "M, and " + Math.round(inf.share_within_fair * 100) + "% were within $" + V.fair + "M. That check peeks at the rest of the 2026 season, so the real test is trades made from here on, which are logged as they happen."));
        w.appendChild(P("Values are team-neutral: a contender paying for this year's wins, or a club with no room for a reliever, is not priced in yet. Treat the simulator as a draft: the projection, arbitration and option rules are defaults awaiting review."));
      }

      /* limits */
      w.appendChild(h("h2", { id: "limits", text: "What it misses" }));
      w.appendChild(h("ul", null,
        h("li", null, h("b", { text: "Tools. " }), "The model only sees production, so young, high-ceiling players whose talent has not shown up in the stat line yet are underrated."),
        h("li", null, h("b", { text: "Defense. " }), "There is no minor league fielding input, so a plus defender at a bat-first position is underrated."),
        low.length ? h("li", null, h("b", { text: "Mid-range odds. " }), "Players given roughly a " + Math.round(Math.min.apply(null, low.map(function (d) { return d.predicted; })) * 20) * 5 + " to " + Math.round(Math.max.apply(null, low.map(function (d) { return d.predicted; })) * 20) * 5 + " percent chance of reaching MLB actually reached more often than predicted, likely because recent classes debut at higher rates than the training years did.") : null,
        c10fail ? h("li", null, h("b", { text: "Lower-level translations. " }), "Translations are still slightly harsh on the lower levels, so a Low-A hitter's MLB-equivalent line understates him a little compared to a AAA hitter's.") : null,
        h("li", null, h("b", { text: "Draft-based projections. " }), "Hitters without enough upper-level playing time are projected from their draft position alone. These are the weakest numbers on the site and are flagged everywhere they appear."),
        h("li", null, h("b", { text: "Pitchers sit low on the combined board. " }), "See the pitcher section: the model's best pitchers carry less expected WAR than its best hitters, and recent minor league walk rates make 2026 pitchers look wilder than the pitchers it learned from.")));
      w.appendChild(P("The clear next step is blending in scouting grades, which goes straight at the model's biggest weakness, along with minor league defensive metrics and pitch-level swing decision data where it exists. Armed with that information, I would expect the gap to Pipeline on high-ceiling players to narrow considerably."));
      w.appendChild(h("p", { style: "margin-top:20px" }, "Jack Huffard. Model run " + M.run_date + "."));
    }).catch(function (e) { chrome("method"); fail(e.message); });
  }

  /* ---------- trade simulator (v3 draft) ---------- */
  function initTrade() {
    var main = document.getElementById("main");
    load("data/trade.json").then(function (T) {
      chrome("trade", T.run_date);
      var w = h("div", { class: "wrap" }); main.appendChild(w);
      var byTeam = {}, tName = {};
      T.teams.forEach(function (t) { byTeam[t.code] = []; tName[t.code] = t; });
      T.assets.forEach(function (a) { if (byTeam[a.team]) byTeam[a.team].push(a); });
      var picked = { A: {}, B: {} }, team = { A: T.teams[0].code, B: T.teams[1].code };
      w.appendChild(h("h1", { style: "margin-top:24px", text: "Trade simulator (beta)" }));
      w.appendChild(h("p", { class: "lede" }, "Pick two clubs and the players each sends. Every asset is in surplus dollars on one scale: prospects from the expected surplus on the leaderboard, major leaguers from projected WAR minus what their contract or arbitration will pay them. Values are team-neutral: a contender's need is not priced in. Beta: the major league aging, playing-time and arbitration assumptions are still under review. ",
        h("a", { href: "method.html#trades", text: "How trades are valued." })));
      var summary = h("section", { class: "answer", "aria-live": "polite", "aria-label": "Trade result" });
      var cols = h("div", { class: "two" });
      w.appendChild(summary); w.appendChild(cols);
      var kindTag = function (a) { return a.kind === "mlb" ? "MLB" : a.on40 ? "Prospect, 40-man" : "Prospect"; };

      function side(k) {
        var box = h("div");
        var sel = h("select", { id: "team-" + k }, T.teams.map(function (t) { return h("option", { value: t.code, text: t.name, selected: t.code === team[k] ? true : null }); }));
        var q = h("input", { type: "search", placeholder: "Filter players", autocomplete: "off", "aria-label": "Filter players" });
        var list = h("div", { class: "tbl-wrap", role: "region", tabindex: "0", "aria-label": "Players" });
        function draw() {
          var t = q.value.trim().toLowerCase();
          var rows = byTeam[team[k]].filter(function (a) { return !t || a.name.toLowerCase().indexOf(t) >= 0; }).slice(0, t ? 80 : 60);
          list.textContent = "";
          list.appendChild(h("table", null, h("caption", { text: "Sends: tick players. Sorted by value; the top 60 shown, filter to find others." }),
            h("thead", null, h("tr", null, ["", "Player", "Type", "Age", "Value", "2027 salary"].map(function (x, i) { return h("th", { scope: "col", class: i >= 3 ? "n" : null, text: x }); }))),
            h("tbody", null, rows.map(function (a) {
              var cb = h("input", { type: "checkbox", "aria-label": "Trade " + a.name, checked: picked[k][a.id] ? true : null });
              cb.addEventListener("change", function () { if (cb.checked) picked[k][a.id] = a; else delete picked[k][a.id]; result(); });
              return h("tr", null, h("td", null, cb),
                h("td", null, a.kind === "mlb" ? a.name : h("a", { href: "player.html?id=" + a.id, text: a.name })),
                h("td", { text: kindTag(a) + (a.pos ? ", " + (a.kind === "mlb" ? a.pos.replace("two_way", "two-way") : a.pos) : "") }),
                h("td", { class: "n", text: num(a.age, 0) }), h("td", { class: "n" + (a.v < 0 ? " neg" : ""), text: usd(a.v) }),
                h("td", { class: "n", text: a.sal == null ? "n/a" : usd(a.sal, 2) }));
            }))));
        }
        sel.addEventListener("change", function () { team[k] = sel.value; picked[k] = {}; draw(); result(); });
        q.addEventListener("input", draw);
        box.appendChild(h("h2", { text: k === "A" ? "Club A sends" : "Club B sends" }));
        box.appendChild(h("div", { class: "controls" }, h("label", { for: "team-" + k }, "Club", sel), q));
        box.appendChild(list);
        draw();
        return box;
      }

      function result() {
        var v = function (o) { return Object.keys(o).reduce(function (s, id) { return s + o[id].v; }, 0); };
        var sal = function (o) { return Object.keys(o).reduce(function (s, id) { return s + (o[id].on40 && o[id].sal ? o[id].sal : 0); }, 0); };
        var n40 = function (o) { return Object.keys(o).filter(function (id) { return o[id].on40; }).length; };
        var sA = v(picked.A), sB = v(picked.B), gainA = sB - sA;
        summary.textContent = "";
        summary.appendChild(h("h2", { style: "margin:0 0 8px;font-size:15px;font-family:var(--sans);font-weight:600", text: "Result" }));
        if (!Object.keys(picked.A).length && !Object.keys(picked.B).length) { summary.appendChild(h("p", { class: "muted", text: "Tick players on either side to build a trade." })); return; }
        var lines = [["A", sB, sA, gainA], ["B", sA, sB, -gainA]].map(function (x) {
          var t = tName[team[x[0]]], roster = t.n40 - n40(picked[x[0]]) + n40(picked[x[0] === "A" ? "B" : "A"]);
          var pay = t.payroll - sal(picked[x[0]]) + sal(picked[x[0] === "A" ? "B" : "A"]);
          return h("div", null, h("h3", { text: t.name }),
            h("dl", { class: "kv" },
              h("div", null, h("dt", { text: "Gets" }), h("dd", { class: "num", text: usd(x[1]) })),
              h("div", null, h("dt", { text: "Gives" }), h("dd", { class: "num", text: usd(x[2]) })),
              h("div", null, h("dt", { text: "Net" }), h("dd", { class: "num" + (x[3] < 0 ? " neg" : ""), text: (x[3] > 0 ? "+" : "") + usd(x[3]) })),
              h("div", null, h("dt", { text: "40-man after" }), h("dd", { class: "num" + (roster > T.roster_max ? " neg" : ""), text: roster + " / " + T.roster_max })),
              h("div", null, h("dt", { text: "2027 payroll after" }), h("dd", { class: "num" + (pay > T.cbt ? " neg" : ""), text: usd(pay, 0) + (pay > T.cbt ? " (over the tax line)" : "") }))));
        });
        summary.appendChild(h("div", { class: "two" }, lines));
        var verdict = Math.abs(gainA) <= T.fair ? "Close to even: the gap is within $" + T.fair + "M, inside the model's error." :
          (gainA > 0 ? tName[team.A].name : tName[team.B].name) + " comes out ahead by " + usd(Math.abs(gainA)) + ".";
        summary.appendChild(h("p", { class: "explain" }, h("b", { text: verdict }), " Payroll is projected 2027 salary for 40-man players (guaranteed, arbitration estimate, or the minimum), compared with a $" + T.cbt + "M luxury-tax threshold."));
      }
      cols.appendChild(side("A")); cols.appendChild(side("B"));
      result();
    }).catch(function (e) { chrome("trade"); fail(e.message); });
  }

  /* six-year WAR quantiles spread across control years by the average profile of real careers */
  function warByYear(p, prof) {
    var dy = p.in_mlb ? +p.in_mlb.debut.slice(0, 4) : +Object.keys(p.eta.debut).reduce(function (a, y) { return p.eta.debut[y] > p.eta.debut[a] ? y : a; });
    var first = p.in_mlb ? 7 - p.in_mlb.control_years_left : 1;
    var ks = ["q10", "q50", "mean", "q90"], tot = [0, 0, 0, 0];
    var rows = prof.filter(function (x) { return x.control_year >= first; }).map(function (x) {
      var yr = dy + x.control_year - 1;
      return [String(yr), String(Math.floor(p.age + yr - p.season))].concat(ks.map(function (k, i) { var v = x.share * p.war[k]; tot[i] += v; return num(Math.round(v * 10) / 10 || 0, 1); }));
    });
    if (!rows.length) return null;
    rows.push([{ v: h("b", { text: "Total" }) }, ""].concat(tot.map(function (v) { return { v: h("b", { text: num(Math.round(v * 10) / 10 || 0, 1) }) }; })));
    return h("div", null, h("h3", { text: "Projected WAR by season" }),
      table(["Season", { t: "Age", n: 1 }, { t: "10th", n: 1, title: "10th percentile" }, { t: "Median", n: 1 }, { t: "Mean", n: 1 }, { t: "90th", n: 1, title: "90th percentile" }], rows, { label: "Projected WAR by season" }),
      h("p", { class: "legend", text: (p.in_mlb ? "Remaining control years only. " : "Assumes his most likely debut year, " + dy + ". ") + "Each column is a six-year outcome (10th percentile, median, mean, 90th percentile) spread across seasons using the average WAR profile of 2005 to 2017 debuts, not a separate projection for each season." }));
  }

  var page = document.body.getAttribute("data-page");
  if (page === "index") initIndex(); else if (page === "player") initPlayer(); else if (page === "method") initMethod(); else if (page === "trade") initTrade();
})();
