# Trade Web + Player Projections merge

The Trade Web becomes the one site for both projects: trade history, player value rankings, the trade machine, and every club's assets, with one player page that shows value, contract, and stats. The MiLB repo stays as the Python model and stops hosting a site.

Status: approved, 2026-11-18.

## Problem
- P1. Two sites show overlapping numbers about the same players. Every UI change happens twice, and a player's value lives on one site while his trade history lives on the other.
- P2. The Trade Web's player page has no stats for most MLB players who were never traded, and there's no way to see a club's whole asset base in one place.

## Users
- U1. Jack, plus anyone he sends the link to (front office contacts, interviewers). Public site, desktop first, must work on a phone.

## v1 scope
- S1. Top tabs become: **Trade Web**, **Teams** (renamed from Team Flows), **Trade Returns**, **Trade Machine** (new), **Player Projections** (new).
- S2. Teams gets an **Assets** sub-tab next to the two it already had (**Trees** and **Ledger**, both unchanged). The club selector is shared by all three. (Changed at build: Team Flows already had two sub-tabs, so Assets became the third rather than replacing them with one "Trades" tab.)
- S3. Assets shows two columns for the selected club: **MLB** (the club's established MLB players, `kind == "mlb"`, about 35 per club) and **Minors** (its prospects). Each row: name, position, age, level or contract, value with its 10th-90th range. Sorted by value, highest first.
- S4. Tapping any player anywhere (Assets, rankings, trade machine, existing places) opens the one player page.
- S5. Player page shows value (with range and the existing value read), contract year by year (MLB players) or P(MLB), career WAR, ETA (prospects), and stats: MLB year-by-year on top, MiLB year-by-year by level below, whichever exist.
- S6. Player Projections tab: all 8,002 valued players on one board with filters for name, hitter/pitcher, MLB vs prospect, level, club, and low confidence, plus sorting. (Changed at build: the MiLB leaderboard file holds only the 6,958 prospects, so the board joins the value file (everyone) to it for the prospect-only columns.)
- S7. Trade Machine tab: the MiLB trade simulator moved over as-is. Same rules (value in vs out per side, 40-man limit, 2027 payroll vs the tax line) and Shop a player. Restyled to the Trade Web's look.
- S8. The methodology page moves into the Trade Web, linked from the rankings tab and player pages. Links that pointed at milb-hitter-value.netlify.app point inside the Trade Web.
- S9. Every new view has a shareable URL and works with browser back/forward, matching how the Trade Web already handles history.
- S10. The MiLB repo stops publishing a site: `site/` pages and `netlify.toml` are removed. The Netlify site itself is shut down by Jack in the Netlify dashboard after the Trade Web PR is live.

## Not in v1
- X1. later: a true 26-man column. No 26-man data exists and it's the offseason; the MLB column uses established MLB players instead. Revisit in spring if active rosters matter.
- X2. later: redesigning the trade machine. It moves over as-is first.
- X3. later: contender/rebuilder adjustments to trade values (already deferred in the v3 spec).
- X4. never: keeping the MiLB site live alongside the Trade Web.
- X5. later: the prospect card's deep detail (what drives the projection, the box-score-to-MLE rate chain, handedness and pitch-type splits, batted ball, arsenal, debut-year chart). The player page shows value, outlook and level-by-level stats; the rest was on the retired MiLB card. Bring it back as a "How we got this value" section if wanted.
- X6. later: the global search box finds traded players and clubs only; any other player is found on Player Projections (name search) or Teams > Assets.

## Approach
- A1. The Trade Web (Vite, plain JS, Vercel) is the only site. New views follow its existing pattern: one file per view in `src/views/`, wired through `main.js`, `state.js`, and `history.js`. Reason: it already has the routing, history, and look we want; the MiLB site has neither routing nor history.
- A2. The MiLB pipeline gets a final export step that writes straight into `~/Projects/mlb-trade-web/public/data/`: values, the leaderboard, method content, and per-player files. Jack commits them in the Trade Web repo. Reason: the model only changes when the pipeline runs, so a daily fetch from a middle site buys nothing, and the site is going away.
- A3. Minor league stats load one small file per prospect, only when his page opens (`public/data/projections/milb/<id>.json`, 0.7 KB each, 5 MB total). MLB stats for every valued MLB player join the existing `players.json`, which already loads only when a player is opened and is refreshed daily. Reason: keeps first load fast. (Changed at build: `players.json` was already lazy, so adding the 1,044 MLB players to it (5.8 to 6.6 MB) met the goal with no new loader.)
- A4. The daily GitHub Action keeps refreshing trades, player stats and Savant data but drops the values fetch. `scripts/fetch-values.mjs` stays as the converter b34 runs to rebuild `values.json` from the local copy, since the daily trade grader reads `values.json`. Reason: values now arrive by commit (A2).
- A5. The trade machine and rankings code from `site/app.js` and `site/shop.js` is ported into Trade Web views, reusing the Trade Web's `money()`, `el()`, club codes, and styles instead of carrying the MiLB site's CSS. Reason: one look, one money format.
- A6. Club codes: values use Baseball-Reference codes (SDP, TBR), trades use MLB API codes (SD, TB). Keep the existing `BREF` map as the one translation point.

## Data
- D1. Values and contract detail for 8,002 players (1,044 MLB, 6,958 prospects): today `site/data/trade.json` from `pipeline/b32_trade.py`. Verified: kinds, fields (`v`, `q10`, `q90`, `kind`, `team`, `level`, `on40`, `ctrl`, `sal`, `war`).
- D2. Leaderboard rows: `site/data/leaderboard.json` (1.9 MB) from `pipeline/b9_site.py`. Verified it exists; filters to be checked against it at build.
- D3. Prospect stat history: `site/data/players/<id>.json`, 6,958 files (season, level, rate stats). Verified one pitcher file.
- D4. MLB stats: Trade Web `public/data/players.json` (5.8 MB) covers traded players only. New per-player MLB pull needed for the rest of the 1,044 MLB players.
- D5. Method content: `site/data/method.json` plus `site/method.html`.
- D6. 26-man rosters: not available anywhere. See X1.

## Success criteria
- C1. All five tabs load on desktop and a 375px phone with no console errors.
- C2. Teams > Assets for any club shows its MLB and Minors players, and the two columns together equal that club's count in the values data.
- C3. Every player in the values data opens a page with value and at least one stats table (or a clear "no stats yet" line for a player who has none).
- C4. Rankings tab row count and the top 10 match the MiLB site's leaderboard for the same filters.
- C5. Trade machine gives the same verdict as the MiLB site on 3 test trades, including one that breaks the 40-man limit and one over the tax line.
- C6. `npm test` and `vite build` pass; MiLB pytest still passes and all 8,002 values are unchanged.
- C7. No link anywhere in the Trade Web points to milb-hitter-value.netlify.app.

## Open questions and assumptions
- Q1. Assumed the Trade Web keeps its current first tab (Trade Web) as the landing page, with the new tabs to its right in the order in S1.
- Q2. Assumed Minors includes 40-man prospects (they're prospects in the model even though they're on the 40-man), marked with a small "40-man" tag.
- Q3. Assumed a player with no stats of either kind (recent draftee, international signee) shows his value and a "no stats yet" line rather than being hidden.
- Q4. Assumed the per-player MLB stat pull is roughly 1,044 small API calls at export time, batched the same way `fetch-players` batches today.
- Q5. Assumed the Trade Web stays on Vercel.
- Q6. Repo: MiLB work on this worktree's branch (fast-forwarded to main after PR #9); Trade Web work on `projections-merge`, cut from main. (Changed at build: `next-season-value` had already merged as mlb-trade-web#7.)
- Q7. 142 MLB players have no years of control left (free agents this winter). They still list under their 2026 club in Assets, tagged "free agent", at $0, because the model's data assigns them there.
- Q8. Player pages from Trade Returns keep their "Back to trade" button; the stand-alone player page relies on the browser's back button.

## Build order
- B1. MiLB: export step that writes values, leaderboard, method, and prospect player files into the Trade Web's `public/data/`. Small.
- B2. MLB per-player stat pull and file format. Medium.
- B3. Trade Web: tab bar, Teams rename with Trades/Assets sub-tabs, Assets view. Medium. First thing you can click.
- B4. Player page: stats tables (MLB then MiLB), all entry points route to it. Medium.
- B5. Player Projections tab (leaderboard port). Medium.
- B6. Trade Machine tab (simulator + Shop a player port). Large.
- B7. Methodology page, link sweep, drop `fetch-values` from the Action. Small.
- B8. MiLB: remove `site/` pages and `netlify.toml`. Small.
- B9. Verify C1-C7, `/code-review` on both PRs, open the PRs. Medium.

## How we build it
- V1. Claude builds it in this session.
- V2. Claude verifies every tab in the browser preview at desktop and phone width, and runs `npm test`, `vite build`, and MiLB pytest.
- V3. `/code-review` runs on each PR before Jack sees it; findings fixed or reported.
- V4. One PR per repo (Trade Web, MiLB). Jack reviews and merges. Vercel deploys the Trade Web on merge. Jack shuts down the Netlify site himself after the Trade Web is live.
