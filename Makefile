.PHONY: install test lint format clean

VENV := .venv

ifeq ($(OS),Windows_NT)
    VENV_BIN := $(VENV)\Scripts
    PYTHON := $(VENV_BIN)\python.exe
    SYS_PYTHON := py
    VENV_CREATE := if not exist "$(PYTHON)" $(SYS_PYTHON) -m venv $(VENV)
else
    VENV_BIN := $(VENV)/bin
    PYTHON := $(VENV_BIN)/python
    SYS_PYTHON := python3
    VENV_CREATE := test -x "$(PYTHON)" || $(SYS_PYTHON) -m venv $(VENV)
endif

## install — Create venv and install Clean + dev deps
install:
	@$(VENV_CREATE)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

## test — Run all tests
test:
	$(PYTHON) -m pytest

## lint — Lint and format-check
lint:
	$(PYTHON) -m ruff check src/ tests/
	$(PYTHON) -m ruff format --check src/ tests/

## format — Auto-format code
format:
	$(PYTHON) -m ruff format src/ tests/
	$(PYTHON) -m ruff check --fix src/ tests/

## clean — Remove venv and caches
clean:
	$(SYS_PYTHON) -c "import shutil; [shutil.rmtree(p, True) for p in ('$(VENV)', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'src/clean.egg-info')]"
