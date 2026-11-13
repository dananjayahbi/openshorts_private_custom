import os
import sys

import pytest

# Make the repo root importable so tests can import the app modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tests always run the app in self-host (BYOK) mode. app.py freezes
# BILLING_ENABLED at import time and load_dotenv never overrides an existing
# variable, so this must be set here — before any test module imports app — or
# the suite's behavior would depend on the developer's personal .env.
os.environ["BILLING_ENABLED"] = "0"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Never read the developer's real Storage/settings.json in a test.

    The LLM chain and the prompt overrides live there, so without this a saved
    five-provider chain would change which provider a test exercises (and a
    broken prompt edit could fail the whole suite).
    """
    monkeypatch.setenv("OPENSHORTS_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("OPENSHORTS_PROFILES", str(tmp_path / "style_profiles.json"))

