# Redline: your daily vehicle security digest

A free, self-hosted site that collects connected and autonomous vehicle security news every morning, ranks each story by "heat" (1–10), and shows a summary, why it matters, and a research angle. It installs like an app on your phone or computer.

## How it works

- **GitHub Actions** runs `scripts/fetch.py` once a day. It reads the feeds in `scripts/feeds.txt`, keeps vehicle security stories, scores them, and saves `docs/data/stories.json`.
- **GitHub Pages** serves the `docs/` folder as your website.
- **Scoring:** with an Anthropic API key, Claude filters, scores, and writes the summaries and research angles. Without a key, a free keyword scorer runs instead (headlines and feed snippets only, with no "why it matters" or research angle).

## Setup (about 10 minutes)

1. **Create a repo.** Sign in to GitHub, click **New repository**, name it (for example `redline`), make it **Public**, and create it. Then click **uploading an existing file** and drag in everything from this folder, including the hidden `.github` folder. (If your file picker hides it, use GitHub Desktop or `git push` from a terminal.)
2. **Turn on the website.** Go to **Settings → Pages**. Under "Build and deployment," choose **Deploy from a branch**, pick **main** and the **/docs** folder, and save. After a minute your site is live at `https://YOUR-USERNAME.github.io/redline/`.
3. **(Optional) Add Claude scoring.** Get an API key at console.anthropic.com. In your repo go to **Settings → Secrets and variables → Actions → New repository secret**, name it `ANTHROPIC_API_KEY`, and paste the key. API usage is billed by Anthropic, but one small daily batch is inexpensive. Check current pricing on their site.
4. **Run it once.** Go to the **Actions** tab, enable workflows if asked, open **Daily digest**, and click **Run workflow**. After that it runs every day at 11:00 UTC on its own.

## Install it as an app

- **iPhone / iPad (Safari):** open your site, tap Share → **Add to Home Screen**.
- **Android (Chrome):** open your site, tap ⋮ → **Install app** (or **Add to Home screen**).
- **Desktop (Chrome / Edge):** click the install icon in the address bar.

It works offline with the last stories it loaded.

## Customize

- **Feeds:** edit `scripts/feeds.txt`. Prefix a name with `*` if the feed is already vehicle-focused. Feeds that fail to load are skipped. Google News search feeds are an easy way to add topics.
- **Schedule:** change the `cron` line in `.github/workflows/daily.yml` (times are UTC).
- **Settings (env vars in the workflow):** `REDLINE_MODEL` (default `claude-haiku-5-5`), `REDLINE_KEEP_DAYS` (archive length, default 365), `REDLINE_LOOKBACK_DAYS` (default 3), `REDLINE_MAX_CANDIDATES` (stories sent to Claude per run, default 40).
- **Keywords:** `VEHICLE_TERMS`, `SECURITY_TERMS`, and `HOT_TERMS` at the top of `scripts/fetch.py`.

## Run locally

```bash
pip install -r scripts/requirements.txt
ANTHROPIC_API_KEY=sk-... python scripts/fetch.py   # or leave the key out for keyword scoring
cd docs && python -m http.server 8000              # then open http://localhost:8000
```

## Notes

- Want the repo private? GitHub Pages on private repos needs a paid GitHub plan. The free alternative is to connect the repo to **Cloudflare Pages** (build command: none, output directory: `docs`).
- GitHub pauses scheduled workflows in repos with no activity for 60 days. The daily commits normally count as activity, but if the digest stops updating, check the Actions tab and re-enable it.
