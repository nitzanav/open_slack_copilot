.PHONY: install run test docker-build docker-run

PYTHON ?= python3

.venv:
	$(PYTHON) -m venv .venv

install: .venv
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/python -m core.slack_bot

test:
	.venv/bin/pytest

docker-build:
	docker build -t open-slack-copilot .

docker-run:
	docker run --rm \
	   -e SLACK_BOT_TOKEN \
	   -e SLACK_APP_TOKEN \
	   -e OPENAI_API_KEY \
	   open-slack-copilot