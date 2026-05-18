# Quite Frankly — Redesign Cutover Punch List

Remaining work between the current `redesign` branch and full production cutover.

---

## Pre-flight (your input required)

- [x] **Personal-relevance blurb refresh.** Now sources from `~/Claude/About Me/personal-context.md` (canonical), auto-synced into this repo via `hooks/pre-commit`. Edit the canonical; the project copy updates on next commit. See repo `README.md` "Personal context (canonical at About Me/)" for setup notes if cloning fresh.
- [ ] **Daily run trigger.** The workflow YAML has only `workflow_dispatch` — no `schedule:` block. Commit `b6cc003` removed the cron deliberately. Confirm what's triggering the daily run today and that it still fires once `redesign` is merged to `main`.

## Cutover (mechanical)

- [ ] **Local smoke test** (Task 10 Step 3):
  ```bash
  cd .worktrees/redesign && MODE=test python3 newsletter.py
  ```
  Verify a `[TEST]`-prefixed email arrives. Verify `comparison/$(date -I).json` was written with sensible phase1/phase2/deltas structure.
- [ ] **Merge strategy decision.** `redesign` is currently ahead of `main`. Squash, merge commit, or rebase — your call. Pick before the merge.
- [ ] **Production cutover** (Task 10 Step 6): Merge `redesign` → `main`, trigger the workflow in test mode once from the Actions tab, confirm a real email arrives, confirm CI commits a `comparison/` file back to the repo. Then let it run live for ~a week.

## After cutover

- [ ] Watch the first Sunday digest (1 week post-cutover).
- [ ] After 2–3 Sunday digests, decide whether to promote Phase 2 traction scoring into production (config flag) or kill the shadow layer entirely.
