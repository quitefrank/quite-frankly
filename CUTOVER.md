# Quite Frankly — Redesign Cutover Punch List

Remaining work between the current `redesign` branch and full production cutover.

---

## Pre-flight (your input required)

- [x] **Personal-relevance blurb refresh.** Now sources from `~/Claude/About Me/personal-context.md` (canonical), auto-synced into this repo via `hooks/pre-commit`. Edit the canonical; the project copy updates on next commit. See repo `README.md` "Personal context (canonical at About Me/)" for setup notes if cloning fresh.
- [x] **Daily run trigger.** Confirmed externally triggered (Frank, 2026-05-18: "we have a cron job that is handling that... possibly through Claude Chat. The trigger is running correctly. I received it this morning"). Not a local crontab, not a launchd LaunchAgent, not the `mcp__scheduled-tasks` local server. Likely a Claude.ai web-app scheduled task hitting the GitHub Actions API. Will continue firing on `main` post-merge as long as the trigger references the repo's `newsletter.yml` workflow.

## Cutover (mechanical)

- [x] **Partial smoke test** (2026-05-18): wiring confirmed end-to-end minus the Claude call and SMTP send. Validated: module imports, day-of-week routing (Monday→`monday_catchup`, 29 feeds), `SECTION_MAP` covers all weekday feeds including Canadaland, `personal-context.md` loads with new content and embeds in `TRIAGE_SYSTEM_PROMPT`, `build_comparison_log` enriches deltas with headline/source/link, `build_weekly_digest_html` renders, `summarize_week` reads `comparison/` cleanly.
- [ ] **Full live smoke test** (requires `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` env vars locally). Frank to run when convenient:
  ```bash
  cd .worktrees/redesign && MODE=test python3 newsletter.py
  ```
  Verify a `[TEST]`-prefixed email arrives. Verify `comparison/$(date -I).json` was written with sensible phase1/phase2/deltas structure.
- [ ] **Merge strategy decision.** `redesign` is currently ahead of `main`. Squash, merge commit, or rebase — your call. Pick before the merge.
- [ ] **Production cutover** (Task 10 Step 6): Merge `redesign` → `main`, trigger the workflow in test mode once from the Actions tab, confirm a real email arrives, confirm CI commits a `comparison/` file back to the repo. Then let it run live for ~a week.

## After cutover

- [ ] Watch the first Sunday digest (1 week post-cutover).
- [ ] After 2–3 Sunday digests, decide whether to promote Phase 2 traction scoring into production (config flag) or kill the shadow layer entirely.
