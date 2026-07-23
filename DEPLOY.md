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
