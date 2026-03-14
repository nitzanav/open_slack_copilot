.PHONY: install run test docker-build docker-run

install:
	pip install -r requirements.txt

run:
	python -m core.slack_bot

test:
	pytest

docker-build:
	docker build -t open-slack-copilot .

docker-run:
	docker run --rm \
		-e SLACK_BOT_TOKEN \
		-e SLACK_APP_TOKEN \
		-e OPENAI_API_KEY \
		open-slack-copilot
