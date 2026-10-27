/* Shop a player (ported from the NBA Tradeability Index shop.py): the package of 1-3 of one club's positive-value
   assets whose total surplus is closest to the shopped player's. Team-neutral; values in $M. Also run by tests/test_b33_shop.py. */
function shopTol(V, fair) { return Math.min(fair, Math.max(1, 0.1 * V)); }

function shopTeam(V, assets, fair) {
  var tol = shopTol(V, fair);
  var a = assets.filter(function (x) { return x.v > 0 && x.v <= V + tol; }).sort(function (x, y) { return x.v - y.v; });
  var best = null;
  function near(lo, t) { // index in [lo, n) whose value is closest to t, or -1
    if (lo >= a.length) return -1;
    var l = lo, r = a.length - 1;
    while (l < r) { var m = (l + r) >> 1; if (a[m].v < t) l = m + 1; else r = m; }
    return l > lo && t - a[l - 1].v < a[l].v - t ? l - 1 : l;
  }
  function consider(pk) {
    var s = pk.reduce(function (t, x) { return t + x.v; }, 0), g = Math.abs(s - V), even = g <= tol;
    // smallest gap to the nearest $1M, then fewest pieces (exact dollars would let filler players win on noise)
    var key = [even ? 0 : 1, Math.round(g), pk.length];
    var d = best ? key[0] - best.key[0] || key[1] - best.key[1] || key[2] - best.key[2] : -1;
    if (d < 0) best = { assets: pk, total: s, gap: s - V, even: even, key: key };
  }
  var i, j, k;
  if ((k = near(0, V)) >= 0) consider([a[k]]);
  for (i = 0; i < a.length; i++) {
    if ((k = near(i + 1, V - a[i].v)) >= 0) consider([a[i], a[k]]);
    for (j = i + 1; j < a.length; j++) if ((k = near(j + 1, V - a[i].v - a[j].v)) >= 0) consider([a[i], a[j], a[k]]);
  }
  return best;
}

if (typeof module !== "undefined") module.exports = { shopTeam: shopTeam, shopTol: shopTol };
