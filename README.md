# Copilot Changelog → Discord

Automatically post **GitHub Copilot** updates (from the GitHub Changelog RSS) to a **Discord channel**. Summaries are simple by default and can use **GitHub Models** (no extra API key) inside GitHub Actions.

## What it does

- Reads the GitHub Changelog RSS feed and **filters items tagged “Copilot.”**
- Summarizes each item  
  - Default: strip HTML, keep ~420 chars.  
  - Optional: **AI summary** (2–4 bullets) via **GitHub Models** using the built‑in `GITHUB_TOKEN`.
- Posts one or more items to Discord as **embeds**.
- Avoids duplicates by recording IDs in `seen.json`.
- Supports Discord **Forum channels** by providing a thread:
  - If `DISCORD_THREAD_ID` is set, posts into that existing thread.
  - Else if `DISCORD_THREAD_NAME` is set, creates a new thread with that name.
  - Else, behavior is controlled by `DISCORD_FORUM_MODE` (default `auto`).

## Quick setup (GitHub only)

> You don’t need to run a server or create a bot user. A Discord **Webhook** + GitHub Actions is enough.

1) **Create a Discord Webhook URL**  
   Discord → open your server → go to the target channel → **⚙️ Channel Settings** → **Integrations** → **Webhooks** → **New Webhook** → **Copy Webhook URL**. Keep it secret.

2) **Add the webhook to repo secrets**  
   GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**  
   - Name: `DISCORD_WEBHOOK_URL`  
   - Value: paste the Discord Webhook URL.

3) **Ensure workflow permissions**  
      The provided workflow (`.github/workflows/post-updates.yml`) already requests:

      ```yaml
      permissions:
         contents: read
         models: read
      ```

      This lets the workflow call **GitHub Models** with the built‑in `GITHUB_TOKEN` (no PAT needed).

4) **Run it**
   The workflow runs **daily at 22:00 UTC** (≈ 5pm EST) and via **Run workflow** (manual).  
   First manual run: **Actions → Post Copilot Changelog to Discord → Run workflow**.

   • Manual force: toggle “Force post (ignore seen.json)” to send regardless of history.  
   • Push force: include the literal token `[force-post]` anywhere in your commit message on `main` to trigger a one-off run that ignores `seen.json` (does not save state). Examples:
   - `chore: test poster [force-post]`
   - `[force-post] debug poster`

That’s it. New Copilot changelog entries post to your channel automatically.

## Optional: run locally

Requirements: **Python 3.11+**

```bash
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Required for local run:
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/…"

# Optional (Forum channel support)
# Post into an existing thread:
# export DISCORD_THREAD_ID="1234567890123456789"
# Or always create a thread with this name:
# export DISCORD_THREAD_NAME="GitHub Copilot Changelog"
# Control behavior if neither is set (default: auto)
# export DISCORD_FORUM_MODE=auto     # try one thread for the run (AI title), else per-item without titles
# export DISCORD_FORUM_MODE=per-item # always one thread per item (AI-derived titles)
# export DISCORD_FORUM_MODE=single   # one thread per run; title from first item (AI-derived)
# export DISCORD_FORUM_MODE=off      # never add thread_name automatically

# Optional AI summaries locally (PAT only needed outside Actions):
# export GITHUB_TOKEN="ghp_…"

python copilot_changelog_to_discord.py
```

- Exits with code 0 if there’s nothing new.
- Creates/updates `seen.json` after successful posts (this file is **git‑ignored**).

## How summaries work

- **Default (no AI):** HTML‑stripped snippet (~420 chars).
- **With AI (preferred in CI):** The workflow uses **GitHub Models** through the automatic `GITHUB_TOKEN` and `permissions: models: read`.
  - Optional model override via env `GITHUB_MODELS_MODEL` (default: `openai/gpt-5-mini`).
  - If the API isn’t accessible, the script **falls back** to the default summary.

> You do **not** need an OpenAI API key for CI. Only consider a PAT if your org policy blocks `GITHUB_TOKEN` access to Models.

### Thread titles in Forum channels

When posting to a Discord **Forum** channel via a webhook, Discord requires a thread. This script handles that automatically:

- Prefer setting `DISCORD_THREAD_ID` to post into a specific existing thread.
- Or set `DISCORD_THREAD_NAME` to create a thread with a fixed name.
- Or control auto behavior with `DISCORD_FORUM_MODE`:
      - `auto` (default): Try one thread for the run (AI‑derived title). If that fails, post each item separately without thread names.
      - `per-item`: Always create one thread per item with AI‑derived titles.
      - `single`: Create one thread per run with a single AI‑derived title (from the first item) and include all embeds in it.
      - `off`: Never set `thread_name` automatically; just attempt a batch post.
  
When titles are derived, the script uses GitHub Models (default `openai/gpt-5-mini`); if unavailable, it falls back to the entry title or a short summary phrase. Titles are cleaned and trimmed to ~90 chars.

### GitHub Actions: toggle forum mode

The provided workflow exposes a dispatcher input `forum_mode` with the same options (`auto`, `per-item`, `single`, `off`). Manual runs can choose a mode without changing code or env vars.

## Duplicate prevention

- Posted item IDs are stored in `seen.json`.  
- Future runs skip anything already recorded.  
- Delete `seen.json` if you want to re‑post historical items (not recommended for production).
  
In CI, `seen.json` is cached between runs to avoid duplicate posts across runners.

## Scheduling note

The schedule is `0 22 * * *` (22:00 UTC) which aligns with ~5pm Eastern Standard Time. During Eastern Daylight Time, 5pm ET corresponds to 21:00 UTC; if you need an exact “5pm America/New_York” trigger year‑round, use a manual run or adjust the cron seasonally.

## Troubleshooting

- **Nothing posts:** The feed may have no new Copilot items, or they were already posted (see `seen.json`). Try manual run.  
- **Webhook errors (400/401/403):** Re‑check your `DISCORD_WEBHOOK_URL` and that the channel still exists.  
- **Models call fails:** Your org may not allow Models via `GITHUB_TOKEN`. Either enable `models: read` at the org level, or create a fine‑grained PAT with **Account permission: Models → Read** and set it as `GITHUB_TOKEN` in the job env. When this happens, posts still succeed; thread titles simply fall back to non‑AI derivations.

## Makefile (developer convenience)

```make
install        # pip install -r requirements.txt
dev-install    # pip install -r requirements.txt -r requirements-dev.txt
lint           # ruff check .
typecheck      # mypy .
test           # pytest -q
run            # python copilot_changelog_to_discord.py
```

## Security

- Treat the **Discord Webhook URL** like a password. Rotate it if leaked (delete webhook, create a new one).  
- Never commit secrets. Use **Actions → Secrets** for CI.

## License

MIT
