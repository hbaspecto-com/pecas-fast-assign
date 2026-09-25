import os
from pathlib import Path

import yaml

_DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.yaml"


def load_settings() -> dict:
    # Overridable so tests/smoke-runs can point at a scratch settings file
    # instead of the real network share, without touching production output.
    settings_path = Path(os.environ.get("PECAS_SETTINGS_PATH", _DEFAULT_SETTINGS_PATH))
    with open(settings_path) as f:
        return yaml.safe_load(f)
