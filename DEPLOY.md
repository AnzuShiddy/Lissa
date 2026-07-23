# Deploying Lissa to Render

**Live app:** <https://lissa-02zl.onrender.com>

## Quick Deploy (Recommended)

1. **Go to [render.com](https://render.com)** and sign up or log in
2. **Click "New +" → "Web Service"**
3. **Connect your GitHub repo** (`AnzuShiddy/Lissa`)
4. **Render will auto-detect** `render.yaml` — just confirm the settings
5. **Add environment variable:**
   - Key: `GEMINI_API_KEY`
   - Value: Your Gemini API key (from https://aistudio.google.com/apikey)
6. **Click "Create Web Service"** — deploys in ~2 minutes

Your app will be live at a URL like `https://lissa-XXXX.onrender.com` — this deployment lives at <https://lissa-02zl.onrender.com>.

## Manual Setup (Alternative)

If you prefer the web dashboard:

1. **Create a new Web Service** and select your GitHub repo
2. **Name:** `lissa`
3. **Environment:** `Python`
4. **Build Command:** (leave default or use) `pip install -r requirements.txt`
5. **Start Command:** `uvicorn app:app --host 0.0.0.0 --port 10000`
6. **Instance Type:** Free (or Starter for better uptime)
7. **Add Environment Variables:**
   - `GEMINI_API_KEY` = your API key

## Behavior Notes

- **Free tier:** Spins down after 15 min of inactivity (first request takes ~30s to wake)
- **Sessions:** Each Render instance keeps in-memory sessions. If scaled to multiple instances, users will lose session on reload (sessions not shared across instances)
- **Memory:** Limited to ~512MB on free tier — fine for Lissa's per-user chat sessions

## Keeping the instance warm

The free tier spins down after ~15 min idle, and because the page itself is
served by the sleeping server, a cold visitor waits ~30s on a blank tab
before Lissa loads — most leave first. That bounce doesn't even show in the
usage stats (the `visit` event fires *after* the page loads), so it reads as
"nobody's interested" when it's really "nobody waited." Worth eliminating
before driving traffic to the site.

Two pingers keep it awake; run either or both.

### Option A — GitHub Actions (already in the repo, zero setup)

`.github/workflows/keepwarm.yml` pings `/api/stats` every 10 minutes. It's
free on the public repo and needs no account. **Caveat:** GitHub's scheduler
is best-effort and often fires late under load, so the real gap can stretch
past the 15-min spin-down window — treat it as "usually warm," not a
guarantee. GitHub also disables scheduled workflows after 60 days with no
repo activity; any push re-arms them. Trigger a run by hand any time from the
repo's **Actions → keep-warm → Run workflow**.

### Option B — UptimeRobot (more reliable, ~5 min to set up)

A dedicated uptime monitor fires on a far tighter, more dependable schedule
than GitHub cron, so it's the better choice for an actual launch window. The
free plan covers this completely.

1. Sign up at [uptimerobot.com](https://uptimerobot.com) (free plan, no card).
2. **+ New monitor** and set:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Lissa keep-warm`
   - **URL:** `https://lissa-02zl.onrender.com/api/stats`
     (use `/api/stats`, not `/` — it's a tiny JSON response, so each ping
     costs no Gemini quota and returns fast once the instance is awake)
   - **Monitoring Interval:** `5 minutes` (the free-plan minimum, and
     comfortably under the 15-min spin-down window)
3. Under **Advanced / Timeout**, raise the request timeout if offered
   (e.g. 30s+) so the very first ping against a *cold* instance — which takes
   ~30s to wake — isn't scored as "down."
4. **Alert Contacts:** add your email if you want to be told when the site is
   actually unreachable (as opposed to just waking up). Optional — the point
   here is keeping it warm, not alerting.
5. **Create Monitor.** It starts pinging immediately; the dashboard shows
   response time and uptime %, a free bonus signal on whether Render itself
   is healthy.

**Note on cost:** keeping the instance awake 24/7 consumes Render free-tier
instance hours (750/month — roughly enough for one always-on service). If you
only need it warm during launch pushes, pause the UptimeRobot monitor (and/or
disable the GitHub workflow) when you're not actively sharing the link.

## Custom Domain (Optional)

After deployment, under **Settings → Custom Domain**, add your own domain.

## Monitoring

Check logs under the **Logs** tab on your Render dashboard. Lissa logs:
- Server startup/shutdown
- API errors (rate limits, Gemini 429s)
- TTS fallback events
- `analytics {…}` lines — one JSON event per visit/message/voice use
  (anonymous: hashed session, counts and lengths, never content)

### Usage stats

`GET /api/stats` returns the last two weeks of aggregate usage (visitors,
returning visitors, messages, engaged sessions, minutes). Two caveats on the
free tier:

- The instance's `analytics.jsonl` is wiped every spin-down, so `/api/stats`
  only covers the current instance's lifetime. The durable record is the
  `analytics` lines in Render's logs — filter for `analytics ` and export
  from the Logs tab.
- Set `LISSA_STATS_TOKEN` as an environment variable to require
  `?token=<value>` on `/api/stats`; without it the endpoint is public
  (aggregate counts only, nothing sensitive).

## Auto-Deploy

Once connected, any push to `master` on GitHub auto-deploys to Render.
