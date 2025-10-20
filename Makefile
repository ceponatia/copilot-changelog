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
