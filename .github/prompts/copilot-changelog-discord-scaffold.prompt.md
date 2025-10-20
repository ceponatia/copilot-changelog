---
description: Bootstrap a brand‑new repo that fetches GitHub Copilot changelog RSS, summarizes items, and posts to a Discord channel via webhook. Include local dev setup, Python script, GitHub Actions workflow, README, and basic quality gates. Start from zero files.
model: GPT-5
mode: agent
tools: []
---

# Task
Create a fresh repository that reads the **GitHub Changelog RSS**, filters for **Copilot** posts, summarizes them (basic local summary with optional LLM), and posts to **Discord** using a **Webhook**. Provide a clean local dev experience and a scheduled **GitHub Actions** workflow.

Follow these steps exactly, generating and saving files as specified.

## 0) Repository initialization
- Initialize a new repo named `copilot-changelog-discord` (assume empty working directory).
- Create and configure:
  - `.gitignore` for Python and editor junk.
  - `README.md` with clear setup and usage.
  - `LICENSE` (MIT).
  - A minimal `Makefile` with common commands.

## 1) Python project setup
- Use Python 3.11+.
- Create `requirements.txt` with:
  - `feedparser`
  - `requests`
  - `python-dateutil`
  - `beautifulsoup4`
- Add a `requirements-dev.txt` with:
  - `pytest`
  - `ruff`
  - `mypy`
  - `types-requests`
  - `types-python-dateutil`
  - `types-beautifulsoup4`
- Create `pyproject.toml` configuring `ruff` and `mypy` with sensible defaults (strict-ish but pragmatic).

## 2) Source code
Create `copilot_changelog_to_discord.py` in the repo root with the following behavior:

**Config & env**
- `FEED_URL = "https://github.blog/changelog/feed/"`
- Read `DISCORD_WEBHOOK_URL` from env (required).
- Optional env for AI summaries:
  - `OPENAI_API_KEY` (use when present).
  - If no key, fall back to a non-AI summary.
- `STATE_FILE = "seen.json"` persists posted IDs.
- `MAX_ITEMS_PER_RUN = 5` safety cap.

**Filtering**
- Parse RSS with `feedparser`.
- Keep items whose `category`/`tags` include `copilot` (case-insensitive).

**Summarization**
- Default: strip HTML and truncate to ~420 chars.
- If `OPENAI_API_KEY` is set, call an LLM to produce **2–4 bullets** (temperature 0.2, concise). If the API fails, gracefully fall back to basic summary.
- Do **not** require AI to run.

**Posting**
- Post 1–N items as a single Discord webhook payload with **embeds** (title, url, description, footer datetime in UTC). Batch oldest→newest order for readability.
- On success, append their IDs to `seen.json` to avoid duplicates.

**CLI**
- Running the script with `python copilot_changelog_to_discord.py` should execute once and exit 0 if nothing to post.

## 3) Workflow (GitHub Actions)
Create `.github/workflows/post-updates.yml` to run hourly and on manual dispatch:
- Matrix not necessary; single job `ubuntu-latest`.
- Steps:
  1) `actions/checkout@v4`
  2) `actions/setup-python@v5` with Python 3.11
  3) `pip install -r requirements.txt`
  4) `python copilot_changelog_to_discord.py` with env:
     - `DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}`
     - `OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}` (optional)
- Add a simple lint job (ruff + mypy) that runs on PRs and pushes to `main`. The lint job must **not** block the scheduled job from running (i.e., independent jobs).

## 4) Documentation
Write a thorough `README.md` that covers:
- What it does.
- How to create a **Discord Webhook** (Channel → Settings → Integrations → Webhooks → New → Copy URL).
- Local run instructions:
  - Create virtual env, install deps, set env var, run script.
- How duplicate prevention works (`seen.json`).
- How to enable AI summaries (set `OPENAI_API_KEY` secret).
- How the GitHub Actions schedule (cron) is in **UTC**.
- Troubleshooting tips (webhook 400s, missing env, feed/network) and rate‑limit notes.
- Security notes (never commit webhook URL or API keys).

## 5) Quality gates & DX
- Add `ruff.toml` / `pyproject.toml` rules:
  - Line length 100–120, select common flake rules, ignore overly pedantic ones.
- `mypy`:
  - strict optional, disallow untyped defs in new code; allow `# type: ignore[reason]` when justified.
- `Makefile` targets:
  - `install`: install app deps
  - `dev-install`: install dev deps
  - `lint`: ruff check
  - `typecheck`: mypy
  - `test`: pytest (create a trivial test that imports the module and validates helper funcs)
  - `run`: run script locally
- Add pre-commit config (optional) with ruff & black (if you choose to add black).

## 6) File tree
Produce this tree after generation (files with * contain content you must write):
```
copilot-changelog-discord/
├─ .github/
│  └─ workflows/
│     └─ post-updates.yml *
├─ .gitignore *
├─ LICENSE (MIT) *
├─ Makefile *
├─ README.md *
├─ requirements.txt *
├─ requirements-dev.txt *
├─ pyproject.toml *   # ruff + mypy config inside
├─ copilot_changelog_to_discord.py *
└─ seen.json          # created at runtime; do not commit by default
```

## 7) Concrete contents to write
### `.gitignore`
- Python: `__pycache__/`, `*.pyc`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`
- Tooling: `.DS_Store`, `.idea/`, `.vscode/`
- App: `seen.json`

### `requirements.txt`
- Exactly the packages listed in step 1.

### `requirements-dev.txt`
- Exactly the dev packages listed in step 1.

### `pyproject.toml`
- Configure ruff and mypy with sane defaults (you choose specifics).

### `copilot_changelog_to_discord.py`
- Implement the logic precisely as described in step 2.
- Include a small helper `is_copilot_tagged(entry)` that checks tags/categories robustly.
- Include `to_discord_embed(entry)` that formats the message.
- Include `post_to_discord(embeds)` with error handling.
- Make it safe if feed is empty.

### `.github/workflows/post-updates.yml`
- Hourly cron.
- Independent lint job for PRs/pushes.
- Read secrets as env.
- Ensure workflow exits successfully when there’s nothing new to post.

### `README.md`
- Include clear copy‑paste instructions for creating the Discord webhook and storing secrets.
- Example local run:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
  python copilot_changelog_to_discord.py
  ```
- Example repo secrets to add:
  - `DISCORD_WEBHOOK_URL`
  - (optional) `OPENAI_API_KEY`

### `Makefile`
Targets:
```make
.PHONY: install dev-install lint typecheck test run
install:
	pip install -r requirements.txt
dev-install:
	pip install -r requirements.txt -r requirements-dev.txt
lint:
	ruff check .
typecheck:
	mypy .
test:
	pytest -q
run:
	python copilot_changelog_to_discord.py
```

### Minimal tests (optional but add them):
- `tests/test_helpers.py` with a smoke test for `is_copilot_tagged` and the summarizer fallback behavior.
- Update tree and workflow to run tests if you add them.

## 8) Acceptance criteria
- Running locally with only `DISCORD_WEBHOOK_URL` posts summarized Copilot items (if any) and creates/updates `seen.json`.
- With `OPENAI_API_KEY` set, summaries switch to 2–4 bullet LLM output; on failure, fall back to basic summary.
- The hourly workflow posts new items and does not repost old ones.
- Lint and typecheck pass.
- README is sufficient for a novice to complete setup without external help.

## 9) Commit & PR hygiene
- Create initial commit with scaffold.
- Open a PR that shows workflow logs passing.
- Tag the first working version as `v0.1.0`.

## 10) Non‑goals (for later)
- Bot commands/slash commands (not needed when using webhooks).
- Database or cloud state (keep `seen.json` simple for now).
- Advanced embed styling or images.
