PYTHON := python3
VENV := venv

.PHONY: install venv clean

venv:
	$(PYTHON) -m venv $(VENV)

# Platform-specific compiler/env handling (e.g. macOS's OpenMP toolchain
# for building aequilibrae from source) lives in settings.yaml and
# scripts/native_build_env.py, not here, so this recipe is OS-agnostic.
install: venv
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install pyyaml
	bash -c 'set -a; eval "$$($(VENV)/bin/python scripts/native_build_env.py)"; set +a; $(VENV)/bin/pip install -r requirements.txt'

clean:
	rm -rf $(VENV)
