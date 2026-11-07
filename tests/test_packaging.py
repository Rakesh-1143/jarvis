"""Auto-start tests with a fake winreg (run on any OS). Run: python -m pytest tests"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import autostart  # noqa: E402


def fake_winreg():
    store = {}

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def delete(key, name):
        if name not in store:
            raise FileNotFoundError
        del store[name]

    def query(key, name):
        if name not in store:
            raise FileNotFoundError
        return store[name], 1

    wr = types.SimpleNamespace(
        HKEY_CURRENT_USER=0, KEY_SET_VALUE=0, KEY_READ=0, REG_SZ=1,
        OpenKey=lambda *a: Key(),
        SetValueEx=lambda key, name, _r, _t, value: store.__setitem__(name, value),
        DeleteValue=delete, QueryValueEx=query,
    )
    return wr, store


def test_install_uninstall(monkeypatch):
    wr, store = fake_winreg()
    monkeypatch.setattr(autostart, "_winreg", lambda: wr)
    assert not autostart.is_installed()
    autostart.install()
    assert autostart.is_installed()
    assert "start_jarvis.pyw" in store["Jarvis"]
    autostart.uninstall()
    autostart.uninstall()  # second time must not fail
    assert not autostart.is_installed()


def test_command_is_quoted():
    cmd = autostart.command()
    assert cmd.startswith('"') and cmd.endswith('start_jarvis.pyw"')
    assert str(ROOT) in cmd


def test_launcher_file_exists():
    assert (ROOT / "packaging" / "start_jarvis.pyw").exists()
    assert (ROOT / "packaging" / "install.bat").exists()
