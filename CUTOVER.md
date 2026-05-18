# Quite Frankly — Redesign Cutover Punch List

Remaining work between the current `redesign` branch and full production cutover.

---

## Pre-flight (your input required)

- [x] **Personal-relevance blurb refresh.** Now sources from `~/Claude/About Me/personal-context.md` (canonical), auto-synced into this repo via `hooks/pre-commit`. Edit the canonical; the project copy updates on next commit. See repo `README.md` "Personal context (canonical at About Me/)" for setup notes if cloning fresh.
- [x] **Daily run trigger.** Confirmed externally triggered (Frank, 2026-05-18: "we have a cron job that is handling that... possibly through Claude Chat. The trigger is running correctly. I received it this morning"). Not a local crontab, not a launchd LaunchAgent, not the `mcp__scheduled-tasks` local server. Likely a Claude.ai web-app scheduled task hitting the GitHub Actions API. Will continue firing on `main` post-merge as long as the trigger references the repo's `newsletter.yml` workflow.

## Cutover (mechanical)

- [x] **Partial local smoke** (2026-05-18): wiring confirmed end-to-end minus the Claude call and SMTP send.
- [x] **Live CI smoke** (2026-05-18, run 26041287561): merged → main, fired `mode=test` workflow run on main, all 9 workflow steps green in 412s, `comparison/2026-05-18.json` auto-committed back to main (commit 75c3a54). Live numbers: 120 items processed (hit `MAX_TRIAGE_INPUT_ITEMS` cap), 85 Phase-2 promotions, 10 Phase-2 demotions, enriched delta entries with headline/source/section/link verified end-to-end.
- [x] **Merge strategy.** Merge commit (`git merge --no-ff redesign`). Preserved the 19 individual redesign commits and the case-study message context. Merge commit on main: e25aae0.
- [x] **Production cutover.** Merged + verified via live CI smoke. Tomorrow's 8am cron-job.org fire will be the first regular production run on the new code; nothing on the cron side needs reconfiguring since the trigger already points at `{"ref":"main"}`.

## After cutover

- [ ] **Confirm the `[TEST]` email arrived** in suarez.milan@gmail.com inbox today (from run 26041287561).
- [ ] **Tomorrow 8am Toronto**: verify the cron-job.org-triggered production run lands cleanly and that `comparison/2026-05-19.json` gets committed back to main.
- [ ] **Sunday digest** (~2026-05-24): first weekly digest email will summarize ~5–6 days of comparison data. Useful heartbeat that the digest path works in production.
- [ ] **2–3 Sunday digests in** (~2026-06-07 to 2026-06-14): decide whether to promote Phase 2 traction scoring into production (config flag) or kill the shadow layer entirely.

## Observations from the live run (for future tuning)

- **Run duration: 412s (~7 min)**, up from ~2 min pre-shadow. Bulk of new time is the 120 items × ~9 traction API calls (8 Reddit subreddit searches + 1 HN search) = ~1080 sequential HTTP calls. Acceptable for a daily, but if it becomes an issue, parallelize the traction fetches in `comparison.attach_traction`.
- **85/120 items promoted by Phase 2** — that's an aggressive promotion rate. Worth watching across multiple Sunday digests before deciding whether Phase 2's traction weights are calibrated right. If Phase 2 promotes the majority of items, the signal collapses (everything is "important"). The 2–3 week eval window will reveal whether promoted items actually look better in retrospect or whether the weights in `comparison.compute_phase2_tier` need tuning down.
