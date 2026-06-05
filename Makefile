
VENV=.venv

# Detect platform and python paths
UNAME_S := $(shell uname -s 2>/dev/null || echo Windows)
ifeq ($(UNAME_S),Windows)
    PY := $(VENV)/Scripts/python.exe
    CREATE_PY := python
else
    PY := $(VENV)/bin/python
    CREATE_PY := $(shell command -v python3 2>/dev/null || command -v python)
endif

.PHONY: venv install validate

venv:
	@if [ -z "$(CREATE_PY)" ]; then \
		echo "Python not found (python3 or python)"; exit 1; \
	fi
	$(CREATE_PY) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

install: venv

validate: venv
	$(PY) window-open-blueprint/tools/validate_blueprint_templates.py
