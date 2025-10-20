# Copilot Changelog → Discord

Post GitHub Copilot changelog updates from the GitHub Changelog RSS feed to a Discord channel using a webhook. Summaries can be basic (no AI), generated with GitHub-hosted models, or via OpenAI if you provide credentials.

## What it does

- Polls the GitHub Changelog RSS: <https://github.blog/changelog/feed/>
- Filters entries tagged for GitHub Copilot
- Summarizes each entry
  - Default: HTML stripped + ~420 chars
  - Optional: 2–4 AI bullet points when `GITHUB_TOKEN`/`GITHUB_MODELS_TOKEN` or `OPENAI_API_KEY` is set
- Posts 1–N entries as Discord embeds via webhook
- Avoids duplicates by tracking IDs in `seen.json`

## Create a Discord Webhook

1. Open your Discord server and navigate to the target channel.
2. Channel settings → Integrations → Webhooks.
3. Click “New Webhook”.
4. Name it and select the channel.
5. Copy the Webhook URL.

Keep this URL secret. Anyone with it can post to your channel.

## Local setup and run

Requirements: Python 3.11+

```bash
python3 -m venv .venv
source .venv/bin/activate.fish  # use .venv/bin/activate for bash/zsh
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
# Optionally enable AI summaries (GitHub Models preferred)
# export GITHUB_TOKEN="ghp_..."            # or set GITHUB_MODELS_TOKEN
# export GITHUB_MODELS_MODEL="gpt-4o-mini"  # optional override
# export OPENAI_API_KEY="sk-..."            # fallback provider
python copilot_changelog_to_discord.py
```

The script exits 0 if nothing new to post. On success, a `seen.json` file will be created/updated to remember which entries were posted.

## Duplicate prevention (`seen.json`)

- After successfully posting, entry IDs (or link/title fallback) are saved in `seen.json`.
- Subsequent runs skip any already-seen IDs.
- The file is ignored by Git (`.gitignore`).

## GitHub Actions workflow (hourly)

This repo includes a workflow that posts hourly in UTC and on manual dispatch.

Add repository secrets:

- `DISCORD_WEBHOOK_URL` — Required. Your Discord webhook URL
- `GITHUB_TOKEN` or `GITHUB_MODELS_TOKEN` — Optional. Enables GitHub Models summaries
- `OPENAI_API_KEY` — Optional fallback for AI bullet summaries

Workflow is defined in `.github/workflows/post-updates.yml` and uses Python 3.11.

## Troubleshooting

- Webhook 400/401/403: Validate the webhook URL and that your Discord server/channel hasn’t changed.
- Missing env var errors: Ensure `DISCORD_WEBHOOK_URL` is set locally or as a repository secret.
- Feed/network errors: Network hiccups can happen. The script will simply find nothing or fail to fetch; it exits gracefully if no entries found.
- Nothing posts: Check `seen.json`. Delete it locally to reprocess from scratch (be mindful of duplicates in production).
- Rate limits: Discord webhooks have limits; this script batches up to `MAX_ITEMS_PER_RUN=5` embeds per run.

## Security notes

- Never commit secrets such as webhook URLs or API keys.
- Prefer GitHub Actions repository secrets for CI.

## Development

Useful commands via Makefile:

```make
install        # install app deps
dev-install    # install dev deps (ruff, mypy, pytest)
lint           # ruff check .
typecheck      # mypy .
test           # pytest -q
run            # python copilot_changelog_to_discord.py
```

## License

MIT
