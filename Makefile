PYTHON := python3
VENV := venv

.PHONY: install venv clean aequilibrae-docs

venv:
	$(PYTHON) -m venv $(VENV)

# Platform-specific compiler/env handling (e.g. macOS's OpenMP toolchain
# for building aequilibrae from source) lives in settings.yaml and
# scripts/native_build_env.py, not here, so this recipe is OS-agnostic.
install: venv
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install pyyaml
	bash -c 'set -a; eval "$$($(VENV)/bin/python scripts/native_build_env.py)"; set +a; $(VENV)/bin/pip install -r requirements.txt'

# Sparse-checkout config for the vendor/aequilibrae submodule is local repo
# state, not something `git submodule update --init` restores on its own -
# run this after cloning (or after `git submodule update --init`) to fetch
# only the docs/ subtree instead of the full aequilibrae source tree.
aequilibrae-docs:
	git submodule update --init vendor/aequilibrae
	git -C vendor/aequilibrae sparse-checkout init --cone
	git -C vendor/aequilibrae sparse-checkout set docs

clean:
	rm -rf $(VENV)
