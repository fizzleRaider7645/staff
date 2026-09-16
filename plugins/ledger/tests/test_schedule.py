import plistlib

import pytest

from ledger import config, schedule


class FakeRun:
    def __init__(self, fail_bootstrap=False):
        self.calls = []
        self.fail_bootstrap = fail_bootstrap

    def __call__(self, argv, **kw):
        self.calls.append(argv)

        class R:
            returncode = 0
            stdout = stderr = ""
        r = R()
        if argv[:2] == ["launchctl", "bootstrap"] and self.fail_bootstrap:
            r.returncode = 1
            r.stderr = "Bootstrap failed: 5: Input/output error"
        if argv[:2] == ["launchctl", "print"]:
            r.returncode = 0 if any(c[:2] == ["launchctl", "bootstrap"] for c in self.calls) else 1
        return r


@pytest.fixture
def agents_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    return tmp_path / "Library" / "LaunchAgents"


def test_install_writes_plist_and_bootstraps(agents_dir, home):
    run = FakeRun()
    info = schedule.install(6, 45, export=True, run=run)
    plist_file = agents_dir / f"{schedule.LABEL}.plist"
    assert info["plist"] == str(plist_file) and plist_file.exists()
    with open(plist_file, "rb") as f:
        plist = plistlib.load(f)
    assert plist["Label"] == schedule.LABEL
    assert plist["StartCalendarInterval"] == {"Hour": 6, "Minute": 45}
    assert plist["ProgramArguments"][0].endswith("/bin/ledger") and plist["ProgramArguments"][1:4] == ["sync", "--max-requests", "6"]
    assert "--export" in plist["ProgramArguments"]
    assert plist["EnvironmentVariables"]["LEDGER_HOME"] == str(config.home())
    assert plist["StandardOutPath"].endswith("logs/sync.log") and plist["RunAtLoad"] is False
    assert any(c[:2] == ["launchctl", "bootout"] for c in run.calls), "an existing agent is replaced, not duplicated"
    assert run.calls[-1][:2] == ["launchctl", "bootstrap"] and run.calls[-1][-1] == str(plist_file)

    st = schedule.status(run=run)
    assert st["installed"] and st["loaded"] and (st["hour"], st["minute"]) == (6, 45) and st["export"]

    gone = schedule.uninstall(run=run)
    assert gone["removed"] and not plist_file.exists()
    assert not schedule.status(run=FakeRun())["installed"]


def test_bootstrap_failure_is_reported(agents_dir, home):
    with pytest.raises(RuntimeError, match="Bootstrap failed"):
        schedule.install(run=FakeRun(fail_bootstrap=True))


def test_not_macos(monkeypatch, home):
    monkeypatch.setattr(schedule.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="macOS"):
        schedule.install(run=FakeRun())
