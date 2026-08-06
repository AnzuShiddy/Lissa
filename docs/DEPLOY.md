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

## The CI key is not the production key

The UI suite in `.github/workflows/tests.yml` drives the real API — roughly
twenty chat calls per run, plus TTS, embeddings and distillation. It reads
`GEMINI_API_KEY_CI` from the repository's Actions secrets, and that must
**not** be the key the live site runs on. A day of re-running the suite has
already exhausted a free tier's daily quota once; while the two shared a key,
that meant the live site answered real visitors with nothing until the quota
reset the next day. A test run must not be able to take production down.

Setting it up:

1. Go to <https://aistudio.google.com/apikey> and click **Create API key**
2. **Create a new project** for it rather than reusing the one the live key
   belongs to — call it something like `luciddive-ci`. This is the part that
   matters: free-tier quota is metered **per project**, not per key, so two
   keys in one project share one daily limit and split nothing
3. Copy the key, then in the repo: **Settings → Secrets and variables →
   Actions → New repository secret**, named `GEMINI_API_KEY_CI`
4. Leave Render's `GEMINI_API_KEY` alone — that stays the production key

With the secret unset the UI suite skips itself rather than failing, which is
also what happens on forks. `unit` still runs, needs no key and no network,
and is the job that actually gates the branch.

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

`.github/workflows/keepwarm.yml` pings `/healthz` every 10 minutes. It's
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
   - **URL:** `https://lissa-02zl.onrender.com/healthz`
     (use `/healthz`, not `/` — it's a tiny JSON response, so each ping
     costs no Gemini quota and returns fast once the instance is awake. It
     needs no token, which `/api/stats` does.)
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

`GET /api/stats?token=<PLATFORM_STATS_TOKEN>` returns the last two weeks of
aggregate usage (visitors, returning visitors, messages, engaged sessions,
minutes).

**Set `PLATFORM_STATS_TOKEN` in the dashboard.** Without it the endpoint is
closed, not public — it answers `404 stats disabled`. That direction is
deliberate: an unset variable is the normal state of a fresh deploy, and the
old "unset means public" rule meant one forgotten field quietly published the
figures, which is exactly what happened. `/healthz` stays open and carries
nothing but `{"ok": true}`, so keep-warm never needs the secret.

### Recovering history after a deploy

The free tier has no persistent disk, so `analytics.jsonl` is wiped by every
deploy and every spin-down, and `/api/stats` only covers the current
instance's lifetime. The durable copy is the `analytics ` lines in Render's
log store, which the app mirrors every event to for exactly this reason — but
the running process can't read its own logs back, so recovery is a manual
pull:

1. **Logs** tab → filter for `analytics ` → **Download**.
2. Merge the export into the event log:

   ```bash
   python tools/ingest_analytics.py render-logs.txt --dry-run   # look first
   python tools/ingest_analytics.py render-logs.txt
   ```

Events are deduplicated on content, so overlapping exports can be replayed as
often as you like without inflating a count. Run it against a local checkout
to build up a history that outlives the instance; point `--into` anywhere you
want that archive to live.

If you'd rather this happened by itself, it needs somewhere durable to write —
a free Postgres (Neon, Supabase) or a Render disk on a paid plan — since
nothing on the free tier survives a restart.

## Auto-Deploy

Once connected, any push to `master` on GitHub auto-deploys to Render.
