VENV=.venv
PY=$(VENV)/Scripts/python.exe

.PHONY: venv install validate

venv:
	python -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

install: venv

validate: venv
	$(PY) window-open-blueprint/tools/validate_blueprint_templates.py
