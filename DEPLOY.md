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

## Auto-Deploy

Once connected, any push to `master` on GitHub auto-deploys to Render.
