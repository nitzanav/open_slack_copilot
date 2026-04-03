.PHONY: install run test docker-build docker-run \
	rag-inspect-all-channels rag-inspect-channel rag-inspect-all \
	rag-inspect-collection rag-list-collections rag-help \
	rag-clean rag-clean-dry-run

PYTHON ?= python3
PY := .venv/bin/python

# Sample size per channel / collection (override: LIMIT=100 make rag-inspect-all-channels)
LIMIT ?= 20

# Local Qdrant folder (default matches config/default.yaml rag.storage_path)
RAG_STORAGE ?= .rag_storage

.venv:
	$(PYTHON) -m venv .venv

# Re-run pip only when requirements.txt changes (keeps repeat `make test` fast).
# `| .venv` is order-only so .venv directory mtime changes do not force reinstall.
.venv/.installed: requirements.txt | .venv
	.venv/bin/pip install -r requirements.txt
	@touch .venv/.installed

install: .venv/.installed

run:
	.venv/bin/python -m core.slack_bot

test: install
	.venv/bin/pytest

docker-build:
	docker build -t open-slack-copilot .

docker-run:
	docker run --rm \
	   -e SLACK_BOT_TOKEN \
	   -e SLACK_APP_TOKEN \
	   -e OPENAI_API_KEY \
	   open-slack-copilot

# --- RAG (inspect uses PYTHONPATH=.; works with bot running via read-only SQLite fallback) ---

rag-help:
	@echo "RAG Makefile targets:"
	@echo "  make rag-inspect-all-channels [LIMIT=20]     — all slack_channel_* indexes + sample payloads"
	@echo "  make rag-inspect-channel CHANNEL=C… [LIMIT=] — one channel (Slack channel id)"
	@echo "  make rag-inspect-all                         — all collections → point counts only"
	@echo "  make rag-inspect-collection COLLECTION=name [LIMIT=] — one collection (SQLite readonly path)"
	@echo "  make rag-list-collections                    — collection names"
	@echo "  make rag-clean-dry-run [RAG_STORAGE=path]    — show size / listing"
	@echo "  make rag-clean [RAG_STORAGE=path]          — delete local RAG store (stop bot first)"

rag-inspect-all-channels:
	PYTHONPATH=. $(PY) -c "import json; from common.slack.slack_rag import slack_rag; print(json.dumps(slack_rag.inspect_all_channels(limit_per_channel=int('$(LIMIT)')), indent=2))"

rag-inspect-channel:
	@test -n "$(CHANNEL)" || (echo "Usage: make rag-inspect-channel CHANNEL=C0123AB [LIMIT=50]"; exit 1)
	PYTHONPATH=. $(PY) -c "import json; from common.slack.slack_rag import slack_rag; print(json.dumps(slack_rag.inspect_channel('$(CHANNEL)', limit=int('$(LIMIT)')), indent=2))"

rag-inspect-all:
	PYTHONPATH=. $(PY) -c "import json; from common.rag import rag; print(json.dumps(rag.inspect_all(), indent=2))"

rag-inspect-collection:
	@test -n "$(COLLECTION)" || (echo "Usage: make rag-inspect-collection COLLECTION=slack_channel_C0123 [LIMIT=50]"; exit 1)
	PYTHONPATH=. $(PY) -c "import json; from common.rag import rag; print(json.dumps(rag.inspect_collection_readonly('$(COLLECTION)', limit=int('$(LIMIT)')), indent=2))"

rag-list-collections:
	PYTHONPATH=. $(PY) -c "import json; from common.rag import rag; print(json.dumps(rag.list_collection_names(), indent=2))"

rag-clean-dry-run:
	@if test -d "$(RAG_STORAGE)"; then \
		echo "$(RAG_STORAGE):"; \
		du -sh "$(RAG_STORAGE)"; \
		find "$(RAG_STORAGE)" -maxdepth 3 -type f 2>/dev/null | head -40 || true; \
	else \
		echo "No directory $(RAG_STORAGE)"; \
	fi

rag-clean:
	@test -n "$(RAG_STORAGE)" || (echo "RAG_STORAGE is empty; refusing"; exit 1)
	@if test -d "$(RAG_STORAGE)"; then \
		rm -rf "$(RAG_STORAGE)"; \
		echo "Removed $(RAG_STORAGE)"; \
	else \
		echo "Nothing to remove: $(RAG_STORAGE) (already absent)"; \
	fi