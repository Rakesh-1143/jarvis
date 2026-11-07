"""Tests for actions/printer.py (piece BJ). win32print / ShellExecute are faked."""
import pytest

from jarvis.actions import fileconvert, printer as pr
from jarvis.actions import recent


class FakeWP:
    PRINTER_ENUM_LOCAL = 2
    PRINTER_ENUM_CONNECTIONS = 4
    JOB_CONTROL_DELETE = 5

    def __init__(self):
        self.default = "HP LaserJet"
        self.info = {"Status": 0, "Attributes": 0, "cJobs": 0}
        self.job_list = []
        self.deleted = []
        self.fail_ids = set()
        self.printers = [(0, "d", "HP LaserJet", ""), (0, "d", "Microsoft Print to PDF", "")]
        self.closed = 0

    def GetDefaultPrinter(self):
        if not self.default:
            raise RuntimeError("no default")
        return self.default

    def OpenPrinter(self, name):
        return ("h", name)

    def ClosePrinter(self, h):
        self.closed += 1

    def GetPrinter(self, h, level):
        assert level == 2
        return self.info

    def EnumJobs(self, h, first, n, level):
        return list(self.job_list)

    def SetJob(self, h, job_id, level, info, cmd):
        assert cmd == 5
        if job_id in self.fail_ids:
            raise PermissionError("access denied")
        self.deleted.append(job_id)

    def EnumPrinters(self, flags, name, level):
        return self.printers


@pytest.fixture
def wp(monkeypatch):
    fake = FakeWP()
    monkeypatch.setattr(pr, "_win32print", lambda: fake)
    return fake


@pytest.fixture
def printed(monkeypatch):
    sent = []
    monkeypatch.setattr(pr, "_shell_print", lambda p: sent.append(p))
    return sent


@pytest.fixture
def folders(tmp_path, monkeypatch):
    paths = {k: tmp_path / k for k in ("downloads", "desktop", "documents")}
    for p in paths.values():
        p.mkdir()
    monkeypatch.setattr(recent, "folder_path", lambda f: str(paths.get(f, tmp_path / "none")))
    monkeypatch.setattr(fileconvert, "explorer_selection", lambda: [])
    return paths


def _file(folder, name, text="hi"):
    p = folder / name
    p.write_text(text)
    return str(p)


# ---------- print_file ----------

def test_print_always_asks_with_file_and_printer(wp, folders):
    _file(folders["documents"], "report.pdf")
    args = {"name": "report"}
    assert pr.needs_confirm("print_file", args)
    assert pr.risky_text("print_file", args) == "print report.pdf on HP LaserJet"
    assert args["paths"][0].endswith("report.pdf")


def test_yes_prints_the_stored_file(wp, folders, printed):
    path = _file(folders["downloads"], "photo.jpg")
    args = {"name": "last download"}
    pr.risky_text("print_file", args)
    _file(folders["downloads"], "newer.txt")  # selection/downloads change after the question
    out = pr.print_file(dict(args, confirm=True))
    assert printed == [path]
    assert out == "Sent photo.jpg to HP LaserJet."


def test_print_this_uses_explorer_selection(wp, folders, printed, monkeypatch):
    a = _file(folders["desktop"], "a.docx")
    b = _file(folders["desktop"], "b.docx")
    monkeypatch.setattr(fileconvert, "explorer_selection", lambda: [a, b])
    args = {"name": "this"}
    assert pr.risky_text("print_file", args) == "print a.docx and b.docx on HP LaserJet"
    assert "Sent a.docx and b.docx" in pr.print_file(args)
    assert printed == [a, b]


def test_never_prints_programs(wp, folders, printed):
    _file(folders["downloads"], "setup.exe")
    args = {"name": "setup"}
    assert pr.risky_text("print_file", args) is None  # nothing to confirm; handler explains
    assert "program or script" in pr.print_file(args)
    assert printed == []


def test_stored_paths_from_ai_are_checked_too(wp, tmp_path, printed):
    bad = tmp_path / "x.bat"
    bad.write_text("echo")
    out = pr.print_file({"paths": [str(bad)], "confirm": True})
    assert "program or script" in out and printed == []


def test_folder_refused(wp, tmp_path, printed):
    out = pr.print_file({"paths": [str(tmp_path)]})
    assert "folder" in out and printed == []


def test_file_not_found(wp, folders, printed):
    assert "couldn't find" in pr.print_file({"name": "nothing here"})
    assert pr.risky_text("print_file", {"name": "nothing here"}) is None


def test_no_default_printer(wp, folders, printed):
    wp.default = ""
    _file(folders["documents"], "report.pdf")
    assert pr.print_file({"name": "report"}) == pr.NO_DEFAULT
    assert pr.risky_text("print_file", {"name": "report"}) is None


def test_no_app_can_print_pdf(wp, folders, monkeypatch):
    _file(folders["documents"], "report.pdf")

    class WinErr(Exception):
        winerror = 31

    def boom(p):
        raise WinErr("no association")

    monkeypatch.setattr(pr, "_shell_print", boom)
    out = pr.print_file({"name": "report"})
    assert "no app can print .pdf files" in out


def test_warns_when_printer_offline(wp, folders, printed):
    _file(folders["documents"], "report.pdf")
    wp.info = {"Status": 0x80}
    assert pr.print_file({"name": "report"}) == "Sent report.pdf to HP LaserJet. But the printer is offline."
    wp.info = {"Status": 0x10}
    assert "is out of paper" in pr.print_file({"name": "report"})


def test_too_many_files(wp, tmp_path, printed):
    paths = []
    for i in range(pr.MAX_FILES + 1):
        p = tmp_path / f"f{i}.txt"
        p.write_text("x")
        paths.append(str(p))
    assert "too many" in pr.print_file({"paths": paths})


# ---------- print_queue ----------

def test_queue_list_empty_and_full(wp):
    assert pr.print_queue({}) == "The print queue on HP LaserJet is empty."
    wp.job_list = [
        {"JobId": 1, "pDocument": "report.pdf", "Status": 0x10, "TotalPages": 3, "PagesPrinted": 0},
        {"JobId": 2, "pDocument": "photo.jpg", "Status": 0},
    ]
    out = pr.print_queue({"action": "list"})
    assert out == "2 jobs on HP LaserJet: report.pdf (printing, page 1 of 3), photo.jpg (waiting)."
    assert not pr.needs_confirm("print_queue", {"action": "list"})


def test_queue_list_caps_spoken_jobs(wp):
    wp.job_list = [{"JobId": i, "pDocument": f"d{i}"} for i in range(8)]
    assert pr.print_queue({}).endswith("and 3 more.")


def test_cancel_asks_only_when_jobs(wp):
    args = {"action": "cancel"}
    assert pr.needs_confirm("print_queue", args)
    assert pr.risky_text("print_queue", args) is None
    assert "nothing to cancel" in pr.print_queue(args)
    wp.job_list = [{"JobId": 7}, {"JobId": 8}]
    assert pr.risky_text("print_queue", args) == "cancel all 2 print jobs on HP LaserJet"
    wp.job_list = [{"JobId": 7}]
    assert pr.risky_text("print_queue", args) == "cancel the print job on HP LaserJet"


def test_cancel_deletes_jobs_and_reports_failures(wp):
    wp.job_list = [{"JobId": 7}, {"JobId": 8}, {"JobId": 9}]
    wp.fail_ids = {9}
    out = pr.print_queue({"action": "cancel", "confirm": True})
    assert wp.deleted == [7, 8]
    assert out.startswith("Cancelled 2 print jobs on HP LaserJet.")
    assert "another user" in out


def test_bad_queue_action(wp):
    assert "list the print queue" in pr.print_queue({"action": "pause"})


# ---------- printer_info ----------

def test_info_ready(wp):
    out = pr.printer_info({})
    assert out == ("Your default printer is HP LaserJet. It is online and ready. "
                   "Other printers: Microsoft Print to PDF.")


def test_info_offline_and_jobs(wp):
    wp.info = {"Status": 0, "Attributes": pr.PRINTER_ATTRIBUTE_WORK_OFFLINE, "cJobs": 2}
    out = pr.printer_info({})
    assert "It is offline." in out and "2 jobs waiting." in out


def test_info_problems(wp):
    wp.info = {"Status": 0x20000 | 0x8}
    assert "It is online but has a paper jam and is low on toner or ink." in pr.printer_info({})


def test_info_no_default(wp):
    wp.default = ""
    assert pr.printer_info({}) == pr.NO_DEFAULT


# ---------- platform / catalog ----------

def test_not_windows_message(monkeypatch):
    monkeypatch.setattr(pr, "IS_WINDOWS", False)
    assert pr.printer_info({}) == pr.NOT_WINDOWS
    assert pr.print_queue({}) == pr.NOT_WINDOWS


def test_catalog_and_handlers_match():
    assert set(pr.CATALOG) == set(pr.HANDLERS) == {"print_file", "print_queue", "printer_info"}
    assert pr.CATALOG["printer_info"]["info"] is True
    assert not pr.CATALOG["print_queue"].get("info")
    assert not pr.CATALOG["print_file"].get("info")
    assert not pr.needs_confirm("printer_info", {})
