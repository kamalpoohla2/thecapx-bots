# CapX Bot System — Complete Setup Guide
**For non-technical users. Takes about 30 minutes.**

---

## What You're Setting Up

A fully automated bot system that:
- **Analyzes** your website automatically
- **Generates** 3 SEO articles per day using free AI
- **Publishes** them to Medium, Dev.to, and Hashnode (driving traffic back to your site)
- **Never sleeps** — runs on GitHub's free servers
- **Restarts automatically** — if anything crashes, it resumes from exactly where it stopped
- **Switches sites** with one command — `python orchestrator.py switch https://newsite.com`

**Total cost: ₹0**

---

## STEP 1: Get a Free Gemini AI Key (5 minutes)

This is the AI brain that writes your articles.

1. Go to **https://ai.google.dev**
2. Click **"Get API key"**
3. Click **"Create API key"**
4. Copy the key — it looks like: `AIzaSyXXXXXXXXXXXXXXXXXXXX`
5. **Save it** — you'll need it in Step 4

> 💡 **Free limit:** 1 million tokens/day. That's ~500 articles/day. More than enough.

---

## STEP 2: Get a Free Supabase Database (5 minutes)

This stores all bot progress so they survive crashes and restarts.

1. Go to **https://supabase.com**
2. Click **"Start for free"** → Sign up with Google
3. Click **"New Project"**
4. Name it: `capx-bots` → Choose any password → Select region: **Southeast Asia (Singapore)**
5. Wait 1 minute for it to create
6. Go to **Settings** (gear icon) → **API**
7. Copy two things:
   - **Project URL** — looks like: `https://xxxxxxxxxxxx.supabase.co`
   - **anon public key** — a long string starting with `eyJ...`
8. **Save both** — you'll need them in Step 4

> 💡 **Free limit:** 500MB database, never expires. You'll never exceed this.

---

## STEP 3: Set Up GitHub (10 minutes)

GitHub runs your bots for free on a schedule.

### 3a. Create a GitHub account
1. Go to **https://github.com** → Sign up (free)

### 3b. Create a new repository
1. Click the **+** button (top right) → **New repository**
2. Name it: `capx-bots`
3. Select **Public** (required for free GitHub Actions)
4. Click **Create repository**

### 3c. Upload the bot files
1. On your new repo page, click **"uploading an existing file"**
2. Drag and drop the **entire `thecapx-bots` folder** from your computer
3. Click **"Commit changes"**

---

## STEP 4: Add Your Secret Keys to GitHub (5 minutes)

This is how your bots securely access the APIs.

1. On your GitHub repo, go to **Settings** (top menu)
2. In the left sidebar: **Secrets and variables** → **Actions**
3. Click **"New repository secret"** for each of the following:

| Secret Name | Value | How to get it |
|---|---|---|
| `GEMINI_API_KEY` | Your Gemini key | Step 1 |
| `SUPABASE_URL` | Your Supabase URL | Step 2 |
| `SUPABASE_KEY` | Your Supabase anon key | Step 2 |
| `TARGET_SITE_URL` | `https://www.thecapx.in` | Your site |
| `SITE_NAME` | `CapX` | Your site name |

**Optional — add these later to start publishing articles:**

| Secret Name | Value | How to get it |
|---|---|---|
| `MEDIUM_TOKEN` | Medium integration token | medium.com/me/settings → Integration tokens |
| `DEVTO_API_KEY` | Dev.to API key | dev.to/settings/extensions |
| `GROQ_API_KEY` | Groq API key | console.groq.com (free backup AI) |

---

## STEP 5: Run the Bots for the First Time

1. On your GitHub repo, click **Actions** (top menu)
2. You'll see "Daily Bots" and "Weekly Full Run"
3. Click **"Daily Bots"** → Click **"Run workflow"** → Click the green **"Run workflow"** button
4. Wait 2–3 minutes
5. Click on the running job to see the live logs

✅ **If you see green checkmarks** — everything is working!

The bots will now run automatically every day at 8:00 AM IST.

---

## STEP 6: Check Your Results

After the first run:
- Open `dashboard/index.html` in your browser to see bot status
- Articles are saved in your Supabase database
- Add Medium/Dev.to API keys to start publishing

---

## ⚡ SWITCHING TO A NEW SITE

To redirect ALL bots to a completely different website:

```bash
python orchestrator.py switch https://www.yournewsite.com
```

That's it. One command:
- Updates the target URL everywhere
- Clears the old site analysis
- Immediately analyzes the new site
- All future content will be about the new site

---

## 🛡️ FAILSAFE — How Crash Recovery Works

| What fails | What happens |
|---|---|
| Bot crashes mid-run | Saves its last step as a "checkpoint". On next run, resumes from that step |
| Server restarts | All state is in Supabase (cloud). Bot reads it and continues |
| AI API is down | Automatically switches to backup AI (Groq) |
| GitHub Actions fails | GitHub retries automatically. You get an email notification |
| Free tier limit hit | Manually switch to backup service (guide below) |

---

## 🔄 BACKUP SERVICES (if free tier ends)

| Service | Backup |
|---|---|
| Gemini AI (primary) | Groq (also free, auto-fallback) |
| Supabase database | Change `SUPABASE_URL` in GitHub Secrets to new provider |
| GitHub Actions | Switch to GitLab CI (also free, same YAML format) |
| Medium publishing | Add Dev.to or Hashnode tokens |

---

## 📅 What Runs When

| Schedule | What happens |
|---|---|
| **Daily at 8:00 AM IST** | Generates 3 new SEO articles, publishes pending articles |
| **Every Sunday at 9:00 AM IST** | Full re-analysis of your site + fresh content batch |
| **Manual anytime** | GitHub Actions → Run workflow → select bot |

---

## ❓ Common Questions

**Q: The bot ran but I don't see articles published.**
A: You need to add `MEDIUM_TOKEN`, `DEVTO_API_KEY`, or `HASHNODE_TOKEN` to GitHub Secrets. Without them, articles are saved locally but not published yet.

**Q: How do I see what articles were generated?**
A: Go to your Supabase dashboard → Table Editor → `bot_state` table → filter by `bot_name = content_generator`.

**Q: Can I change how many articles it generates per day?**
A: Yes — open `config.json`, change `"articles_per_day": 3` to any number.

**Q: The GitHub Action shows a red X.**
A: Click on it to see the error. Most common causes:
- `GEMINI_API_KEY` not set → Go to Settings → Secrets and add it
- `SUPABASE_URL` not set → Same fix

**Q: I want to add a new platform to publish to.**
A: Add your API key to GitHub Secrets, then message me and I'll add the publisher code.

---

## 🗺️ Future Bots (Phase 2)

Once Phase 1 is stable, we can add:
- **Analytics Bot** — reads Google Analytics, reports traffic impact
- **Engagement Bot** — re-engages inactive users via email/WhatsApp
- **Ad Manager Bot** — creates and optimizes Google/Meta ad campaigns
- **Social Media Bot** — posts to Reddit, Quora, LinkedIn automatically

---

*Built for thecapx.in · All free tools · No credit card required*
