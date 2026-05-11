# Quite Frankly - Newsletter Setup

A daily morning briefing delivered to your Gmail inbox at 8am Toronto time.
Pulls from 10 RSS/Reddit sources, summarizes via Claude API, sends as a styled HTML email.

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

The workflow file tells GitHub to run the script every day at 12:00 UTC, which is:
- **8:00 AM EDT** (April to November)
- **7:00 AM EST** (November to April)

No action required from you - it just runs.

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

All feed URLs and section assignments are at the top of `newsletter.py` in the `FEEDS` and `SECTION_MAP` sections. Edit and commit - the next run picks up the changes.

---

## Costs

| Service | Cost |
|---------|------|
| GitHub Actions | Free (well within free tier at ~1 min/day) |
| Claude API | Charged per token - roughly $0.03 to $0.08 per newsletter |
| Gmail SMTP | Free |

At ~$0.05/day, the newsletter costs about $1.50/month in Claude API usage.
