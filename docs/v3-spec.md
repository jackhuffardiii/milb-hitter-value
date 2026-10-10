# MiLB Player Value v3: MLB players and a trade simulator (DRAFT, not approved)

Drafted 2026-10-10 by Claude while Jack was away, from the V3 plan in X15 and project memory. Every decision below is a
default, tagged **[review]** where Jack has not decided it. No v3 code is written against this until Jack approves it
(project-intake rule). IDs continue v2's numbering.

## Problem
- **P5** v2 values prospects only. A trade question ("would the Mariners do Anderson for a controllable starter?") needs
  MLB players on the same surplus-$ scale.
- **P6** Prospects are the currency in most MLB trades, so the simulator is only as good as the prospect values (v2).

## Scope: V3a (MLB player value) then V3b (simulator)
- **S32** Population: every player on a 2026 MLB 40-man roster or with 2026 MLB playing time, valued at the 2026
  offseason snapshot. Prospects keep their v2 values. **[review]**
- **S33** Projection: our own WAR (same 590/410 scale), Marcel-style weighted history (5/4/3 over the last three seasons,
  regressed toward a playing-time-scaled mean), our own aging curve from the delta method on 2005-2026 WAR, separate for
  hitters, starters and relievers. Six seasons projected (or to free agency, whichever is shorter for control value).
  **[review]** Alternative: Steamer/ZiPS-style public projections as inputs (not reproducible offline).
- **S34** Contracts: guaranteed salary by year and options from Baseball-Reference team payroll pages (current snapshot,
  30 cached pages). Pre-arb years at the league minimum. Arbitration years from an arbitration salary model (S35).
- **S35** Arbitration model: salary in arb year k ~ prior-season WAR, cumulative WAR, service class (Super Two, Arb 1-3),
  position group, prior salary; trained on Cot's 2010-2026 salaries + service time (D19). **[review]**
- **S36** Surplus: per season, projected WAR x $/WAR (D9, or calibrated on Cot's FA signings, S38) minus salary,
  discounted 8%. Pre-arb and arb years floor at 0 (non-tender / option); guaranteed years do not floor (the team owes
  the money). Team options exercised when value > option price; player opt-outs when value > remaining salary.
- **S37** Site: MLB players join the board under an "MLB" filter, with contract and service-time rows on the card.
- **S38** $/WAR calibration from Cot's free-agency workbook (1991-2027 signings) instead of the cited FanGraphs figure,
  only if it passes C25. **[review]**
- **S39** V3b simulator: browser engine (Pyodide, stdlib-only request path) ported from the NBA Tradeability Index
  `shop.py` pattern: evaluate a trade, shop a player, acquire a target. Value change per team = incoming minus outgoing
  surplus; MLB rules: 40-man roster limit, no-trade clauses (from the payroll pages where shown), CBT tax
  before/after. **[review]**
- **S40** Contender adjustment: a team's marginal win is worth more near the playoff line; a win curve from 2012-2026
  playoff odds by win total scales current-season WAR for contenders. **[review]** (The NBA project's fit-value test
  failed and shipped team-neutral; v3 should start team-neutral too.)

## Out of scope
- **X16** Player-team fit, positional need. Team-neutral first (NBA lesson).
- **X17** Minor-league contracts and Rule 5 eligibility logic beyond a flag.
- **X18** Draft picks as trade assets (competitive balance picks are tradeable but rare). **[review]**

## Data
| id | what | source | lives |
|---|---|---|---|
| D19 | MLB salaries 2000-2026, service time 2010-2026 (~870-970 paid players/yr) | Cot's workbook, hand-downloaded | data/raw/cots/ (gitignored) |
| D20 | Free-agent signings 1991-2027 | Cot's workbook | data/raw/cots/ |
| D21 | 2026 contracts, options, service time, FA year | B-Ref team payroll pages (30, cached) | data/raw/bref_payroll/ |
| D22 | Every MLB trade since 2015, MLBAM ids | ~/Projects/mlb-trade-web/public/data/trades.json | read-only |

Feasibility (checked 2026-10-10): D19 parses with stdlib zipfile (no openpyxl); salary rows have names "Last, First",
no ids, so the join to MLBAM ids goes by name + season + position with ambiguity rejection (Q12 rule).

## Success criteria
- **C23** Projection backtest: next-season WAR correlation and RMSE for 2015-2025, ours vs plain Marcel on our WAR.
  Ships if not worse than Marcel. **[review]**
- **C24** Arb model: grouped-CV error on 2010-2020 arb salaries vs the 40/60/80 rule v2 uses; one holdout look on
  2021-2026.
- **C25** $/WAR calibration: real FA AAV vs projected WAR at signing; reported, used only if stable across years.
- **C26** Trade replay (V3b): on real trades made after the v3 declaration date (D22), report how often both sides'
  value changes are within a tolerance band, and the distribution of the surplus gap. Report only; no tuning on it.
- **C27** Name-join coverage: >= 95% of paid player-seasons 2010-2026 matched to an MLBAM id, ambiguous rejected.

## Build order (proposed)
- **B27** D19/D20 parser + MLBAM id join (C27). (S)
- **B28** D21 payroll pull + contract table (options, FA year). (S)
- **B29** MLB projection + aging (S33, C23). (M)
- **B30** Arb model (S35, C24). (M)
- **B31** MLB surplus (S36) + board/site (S37). (M)
- **B32** Simulator engine + page (S39, S40 team-neutral first, C26). (L)

## Open questions for Jack
- Q26 Projection: our Marcel + aging (reproducible, all ours) or public projections as an input?
- Q27 Contender adjustment in v1 of the simulator, or team-neutral only (NBA precedent)?
- Q28 Does the simulator need draft picks / international bonus pool money as assets?
- Q29 Same Netlify site with an MLB tab, or a separate site?
