# Same lint tools and rules as CTFd 3.8.9 (see CTFd's Makefile and linting.txt).
# Setup: make venv   (needs uv; Python 3.11 like CTFd's Docker image)
VENV ?= .venv/bin
CTFD_PATH ?= ../CTFd
PYTHON ?= 3.11

venv:
	uv venv --python $(PYTHON) .venv
	uv pip install --python .venv/bin/python -r $(CTFD_PATH)/requirements.txt -r requirements.txt -r dev-requirements.txt

lint:
	$(VENV)/ruff check --select E,F,W,B,C4,I --ignore E402,E501,E712,B904,B905,I001 --exclude=.venv .
	$(VENV)/isort --profile=black --check-only --skip=.venv .
	$(VENV)/black --check --diff --exclude=.venv .

format:
	$(VENV)/isort --profile=black --skip=.venv .
	$(VENV)/black --exclude=.venv .

# Runs against CTFd's own test app; CTFD_PATH must be a checkout of the
# CTFd version the plugin targets, with the ctfd_cheaters plugin installed.
test:
	CTFD_PATH=$(CTFD_PATH) $(VENV)/pytest -c plugin_tests/pytest.ini plugin_tests

.PHONY: venv lint format test
