import pytest

from jarvis.assistant import Assistant
from jarvis.config import load_config
from jarvis.memory import Memory


@pytest.fixture
def jarvis(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    cfg.data["assistant"]["data_dir"] = str(tmp_path)
    cfg.data["llm"]["provider"] = "none"
    cfg.data["weather"]["city"] = "London"
    out = []
    a = Assistant(cfg, notify=out.append, memory=Memory())
    a.notified = out
    return a
