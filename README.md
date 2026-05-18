# Quite Frankly - Newsletter Setup

A daily morning briefing delivered to your Gmail inbox at 8am Toronto time.
Pulls from a curated pool of RSS/Reddit/podcast sources, triages and scores via Claude, sends as a styled HTML email. See [Architecture](#architecture-post-2026-05-15-redesign) for the post-redesign pipeline.

---

## What you need before starting

- A GitHub account (free)
- Your Anthropic API key (from console.anthropic.com)
- A Gmail account to send from (can be the same one you receive on)

---

## Step 1 - Create a Gmail App Password

Gmail won't let scripts log in with your regular password. You need a special "App Password".

1. Go to your Google Account: https://myaccount.google.com
2. Click **Security** in the left sidebar
3. Make sure **2-Step Verification** is turned on (required for App Passwords to appear)
4. Search for "App passwords" in the search bar at the top, or go to: https://myaccount.google.com/apppasswords
5. Under "App name", type: `Quite Frankly`
6. Click **Create**
7. Google gives you a 16-character password. Copy it immediately - you won't see it again.

---

## Step 2 - Get your Anthropic API key

1. Go to: https://console.anthropic.com
2. Click **API Keys** in the left sidebar
3. Click **Create Key**, name it `Quite Frankly`, copy the key

---

## Step 3 - Create the GitHub repository

1. Go to: https://github.com/new
2. Name it `quite-frankly` (or anything you like)
3. Set it to **Private**
4. Click **Create repository**

---

## Step 4 - Upload the files

You need to add these files to the repository:

```
quite-frankly/
├── newsletter.py
├── requirements.txt
├── seen_links.json          ← create this yourself (see below)
└── .github/
    └── workflows/
        └── newsletter.yml
```

**Create seen_links.json yourself** - it just needs to start empty:
```json
{}
```

### Easiest way to upload (no coding required):

1. On your new repo page, click **Add file** > **Upload files**
2. Drag in `newsletter.py`, `requirements.txt`, and `seen_links.json`
3. Click **Commit changes**

For the workflow file, you need to create the folder structure manually:
1. Click **Add file** > **Create new file**
2. In the filename box, type: `.github/workflows/newsletter.yml`
3. Paste the contents of `newsletter.yml`
4. Click **Commit changes**

---

## Step 5 - Add your secrets

GitHub Secrets store your passwords securely so they never appear in your code.

1. In your repo, click **Settings** (top tab)
2. In the left sidebar, click **Secrets and variables** > **Actions**
3. Click **New repository secret** and add these three, one at a time:

| Name | Value |
|------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key from Step 2 |
| `GMAIL_ADDRESS` | The Gmail address you're sending from (e.g. suarez.milan@gmail.com) |
| `GMAIL_APP_PASSWORD` | The 16-character App Password from Step 1 |

---

## Step 6 - Test it manually

Before waiting until 8am, trigger a test run:

1. In your repo, click the **Actions** tab
2. Click **Quite Frankly Newsletter** in the left sidebar
3. Click **Run workflow** > **Run workflow**
4. Watch the run - it should go green in about 60-90 seconds
5. Check your inbox

If it fails, click the failed run to see the error log.

---

## How it runs automatically

The daily 8am send is triggered by an **external scheduler at cron-job.org**, not by GitHub Actions' built-in `schedule:` trigger. The built-in schedule was removed in commit `b6cc003` because it produced duplicate sends. The GitHub Actions workflow now only runs on `workflow_dispatch` (manual or HTTP-triggered).

### cron-job.org job configuration

Dashboard: https://console.cron-job.org

| Field | Value |
|---|---|
| Title | `Quite Frankly Newsletter` |
| URL | `https://api.github.com/repos/quitefrank/quite-frankly/actions/workflows/newsletter.yml/dispatches` |
| Method | POST |
| Schedule | `0 8 * * *` (daily at 8:00) |
| Timezone | `America/Toronto` (handles EDT/EST automatically) |
| Headers | `Authorization: Bearer <GitHub PAT>`, `Content-Type: application/json` |
| Body | `{"ref":"main"}` |
| Timeout | 30 seconds |
| Notify on failure | After 1 failure, plus when disabled due to too many failures |

The Authorization header carries a GitHub Personal Access Token with `repo` and `workflow` scopes (private repos need both). The token lives only on cron-job.org and in your password manager. Never commit it.

### Why an external scheduler

GitHub Actions' `schedule:` trigger has two problems for a small personal job: it can run twice when a previous run is still queued, and it has no visibility into failures unless you watch the Actions tab. cron-job.org gives proper email alerts on failure, deterministic single-fire scheduling, and is free at this volume.

### Triggering ad-hoc

- **From the GitHub UI:** Actions → Quite Frankly Newsletter → Run workflow → pick `main` ref → choose `mode=production` or `test`
- **From CLI:** `gh workflow run newsletter.yml --ref main -f mode=test`
- **From cron-job.org:** dashboard → job → "Run now"

### If sends stop arriving

Check, in order:
1. cron-job.org dashboard for failed executions and the last response code
2. The GitHub PAT in the Authorization header (expired, revoked, or scopes changed)
3. The GitHub Actions tab for failed workflow runs (the script itself may have failed)
4. Anthropic API quota, Gmail SMTP auth (less common)

### Rotating the PAT

When the GitHub PAT expires or is suspected of leaking:

1. GitHub → Settings → Developer settings → Personal access tokens → Revoke the old one
2. Generate a new token with `repo` and `workflow` scopes
3. Update the Authorization header on the cron-job.org job (no other places to update)
4. Trigger a "Run now" from cron-job.org to confirm the new token works

---

## Clearing the dedup cache

If you want to reset the seen-links history (e.g. after a bunch of test runs filled it up):

1. In your repo, click on `seen_links.json`
2. Click the pencil icon to edit
3. Replace the contents with `{}`
4. Click **Commit changes**

The next run will treat all headlines as fresh.

---

## Changing feeds or sections

All feed URLs, section assignments, and favicons live in `config.py`. Feeds are split by mode: `FEEDS_WEEKDAY`, `FEEDS_SATURDAY_STRATEGIC`, and `FEEDS_SUNDAY_VISUAL`. The `SECTION_MAP` dict assigns each source to a section. Edit and commit — the next run picks up the changes.

---

## Architecture (post-2026-05-15 redesign)

The script runs in one of four modes based on the day of week (Toronto time):

- **Monday** — catch-up of Friday through Sunday non-design news
- **Tuesday–Friday** — daily non-design news
- **Saturday** — weekly strategic design round-up (UX Collective, Smashing, NN/g, Lenny's Newsletter)
- **Sunday** — weekly visual design round-up (Design Milk, Hypebeast, Codrops, Sidebar, Trendland)

Internally the pipeline is:

```
fetch → dedup → assign IDs → Pass 1 (Claude triage: score, tier, cluster)
  → Phase 1.5 shadow scoring (Reddit + HN, writes comparison/YYYY-MM-DD.json)
  → Pass 2 (Claude format) → render HTML → SMTP send
```

On Sundays, a second SMTP send delivers a weekly digest summarizing what a traction-weighted Phase 2 would have promoted or demoted versus what Phase 1 actually sent. After 2–3 weeks of digests, the call is whether to promote Phase 2 into production tier scoring.

Module layout:

- `newsletter.py` — orchestration entry point
- `config.py` — feeds, sections, favicons, recipient
- `routing.py` — day-of-week mode resolution
- `pipeline.py` — feed fetching, dedup, ID assignment
- `triage.py` — Pass 1 Claude call (structured output via tool use)
- `formatting.py` — Pass 2 Claude call, HTML rendering, SMTP send
- `traction.py` — Reddit + HN traction fetchers (Phase 1.5)
- `comparison.py` — shadow scoring, comparison logs, weekly digest
- `prompts.py` — system prompts and personal-relevance blurb

See [`docs/2026-05-15-newsletter-redesign-spec.md`](docs/2026-05-15-newsletter-redesign-spec.md) for the full design and [`docs/2026-05-15-newsletter-redesign-plan.md`](docs/2026-05-15-newsletter-redesign-plan.md) for the implementation plan.

---

## Personal context (canonical at About Me/)

The reader-context blurb fed into the triage prompt lives canonically at `~/Claude/About Me/personal-context.md`. The newsletter ships with a synced copy at `./personal-context.md` that `prompts.py` reads at import time. Edit the canonical; the project copy auto-updates on the next commit via `hooks/pre-commit`.

**Fresh-clone setup (one-time, per machine):**

```bash
git config core.hooksPath hooks/
```

After that, any commit automatically syncs the project copy from the canonical if it's drifted. To sync without committing (e.g., before a manual workflow trigger), run `bash hooks/sync-context.sh`.

If you're cloning the repo somewhere that doesn't have `~/Claude/About Me/personal-context.md` (e.g., CI), the sync is a no-op and the committed `personal-context.md` is used as-is. CI does not run pre-commit hooks.

---

## Costs

| Service | Cost |
|---------|------|
| GitHub Actions | Free (well within free tier at ~1–2 min/day) |
| Claude API | Charged per token. Two-pass triage + format ≈ $0.06–$0.16 per newsletter |
| Reddit + HN APIs | Free (public JSON endpoints) |
| Gmail SMTP | Free |

At ~$0.10/day, the newsletter costs about $3/month in Claude API usage post-redesign (Phase 1.5 shadow scoring adds no Claude cost, just ~30 seconds of runtime per day for the traction queries).
