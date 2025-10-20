# Copilot Changelog → Discord

Automatically post **GitHub Copilot** updates (from the GitHub Changelog RSS) to a **Discord channel**. Summaries are simple by default and can use **GitHub Models** (no extra API key) inside GitHub Actions.

## What it does

- Reads the GitHub Changelog RSS feed and **filters items tagged “Copilot.”**
- Summarizes each item  
  - Default: strip HTML, keep ~420 chars.  
  - Optional: **AI summary** (2–4 bullets) via **GitHub Models** using the built‑in `GITHUB_TOKEN`.
- Posts one or more items to Discord as **embeds**.
- Avoids duplicates by recording IDs in `seen.json`.

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
   The workflow runs **hourly** (UTC) and via **Run workflow** (manual).  
   First manual run: **Actions → Post Copilot Changelog to Discord → Run workflow**.

That’s it. New Copilot changelog entries post to your channel automatically.

## Optional: run locally

Requirements: **Python 3.11+**

```bash
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Required for local run:
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/…"

# Optional AI summaries locally (PAT only needed outside Actions):
# export GITHUB_TOKEN="ghp_…"

python copilot_changelog_to_discord.py
```

- Exits with code 0 if there’s nothing new.
- Creates/updates `seen.json` after successful posts (this file is **git‑ignored**).

## How summaries work

- **Default (no AI):** HTML‑stripped snippet (~420 chars).  
- **With AI (preferred in CI):** The workflow uses **GitHub Models** through the automatic `GITHUB_TOKEN` and `permissions: models: read`.  
  - Optional model override via env `MODEL_ID` (the workflow example uses `openai/gpt-4o`).  
  - If the API isn’t accessible, the script **falls back** to the default summary.

> You do **not** need an OpenAI API key for CI. Only consider a PAT if your org policy blocks `GITHUB_TOKEN` access to Models.

## Duplicate prevention

- Posted item IDs are stored in `seen.json`.  
- Future runs skip anything already recorded.  
- Delete `seen.json` if you want to re‑post historical items (not recommended for production).

## Troubleshooting

- **Nothing posts:** The feed may have no new Copilot items, or they were already posted (see `seen.json`). Try manual run.  
- **Webhook errors (400/401/403):** Re‑check your `DISCORD_WEBHOOK_URL` and that the channel still exists.  
- **Models call fails:** Your org may not allow Models via `GITHUB_TOKEN`. Either enable `models: read` at the org level, or create a fine‑grained PAT with **Account permission: Models → Read** and set it as `GITHUB_TOKEN` in the job env.

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
