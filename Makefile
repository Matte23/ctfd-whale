# Same tools, versions and rules as CTFd 3.8.9 (see CTFd's Makefile and linting.txt).
# Setup: python3 -m venv .venv && .venv/bin/pip install -r linting.txt
VENV ?= .venv/bin

lint:
	$(VENV)/ruff check --select E,F,W,B,C4,I --ignore E402,E501,E712,B904,B905,I001 --exclude=.venv .
	$(VENV)/isort --profile=black --check-only --skip=.venv .
	$(VENV)/black --check --diff --exclude=.venv .

format:
	$(VENV)/isort --profile=black --skip=.venv .
	$(VENV)/black --exclude=.venv .

.PHONY: lint format
