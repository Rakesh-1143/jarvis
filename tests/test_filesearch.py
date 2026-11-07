"""Search inside files (piece BM). Windows Search is faked; never opens real files."""
import time
from datetime import datetime, timezone

import pytest

from jarvis.actions import filesearch as fs

_REAL_RUN = fs._run_query


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    fs.reset()
    calls = {"sql": [], "opened": [], "rows": []}

    def run(sql):
        calls["sql"].append(sql)
        return list(calls["rows"])

    monkeypatch.setattr(fs, "_run_query", run)
    monkeypatch.setattr(fs, "_startfile", calls["opened"].append)
    monkeypatch.setattr(fs, "_home", lambda: "C:\\Users\\rakesh")
    yield calls
    fs.reset()


def test_query_text_kind_scope():
    sql = fs.build_query("the file that mentions invoice 2024", "pdfs", "")
    assert "SCOPE='file:C:/Users/rakesh'" in sql
    assert """CONTAINS(*, '"invoice" AND "2024"')""" in sql
    assert "System.FileExtension IN ('.pdf')" in sql
    assert "TOP 10" in sql and "ORDER BY System.Search.Rank DESC" in sql
    assert "System.ItemType <> 'Directory'" in sql


def test_query_escapes_quotes_and_sql():
    sql = fs.build_query("tax' OR 1=1; DROP \"x\" % _ *", "", "")
    inside = sql.split("CONTAINS(*, '")[1].split("')")[0]
    assert "'" not in inside.replace("''", "")
    assert ";" not in sql and "=1" not in inside and "%" not in inside and "*" not in inside


def test_query_scope_with_quote_is_escaped():
    sql = fs.build_query("x", "", "", scope="C:\\Users\\o'brien")
    assert "SCOPE='file:C:/Users/o''brien'" in sql


def test_query_modified_yesterday_has_both_bounds():
    now = time.mktime((2026, 11, 7, 15, 0, 0, 0, 0, -1))
    sql = fs.build_query("", "", "yesterday", now=now)
    mid = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start = datetime.fromtimestamp(mid.timestamp() - 86400, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end = datetime.fromtimestamp(mid.timestamp(), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    assert f"System.DateModified >= '{start}'" in sql
    assert f"System.DateModified < '{end}'" in sql
    assert "CONTAINS" not in sql and "ORDER BY System.DateModified DESC" in sql


def test_norm_modified():
    assert fs.norm_modified("this week") == "week"
    assert fs.norm_modified("Today") == "today"
    assert fs.norm_modified("someday") == ""


def test_find_needs_something(fake):
    assert "What should I look for" in fs.find_files({})
    assert "What should I look for" in fs.find_files({"text": "the file"})
    assert fake["sql"] == []


def test_find_lists_top_three_and_remembers(fake):
    now = time.time()
    fake["rows"] = [(f"C:\\Users\\rakesh\\Documents\\r{i}.pdf", now) for i in range(5)]
    out = fs.find_files({"text": "invoice", "kind": "pdf"})
    assert out.startswith("I found 5 files:")
    assert "r0.pdf" in out and "r2.pdf" in out and "r3.pdf" not in out
    assert "and 2 more" in out and "edited today" in out
    assert fs.has_results()


def test_find_one_file_wording(fake):
    fake["rows"] = [("C:\\Users\\rakesh\\a.txt", 0.0)]
    assert fs.find_files({"modified": "today"}).startswith("I found 1 file:")


def test_find_nothing(fake):
    out = fs.find_files({"text": "zebra"})
    assert "I found no files that mention zebra" in out
    assert not fs.has_results()


def test_search_off_says_how_to_turn_on(monkeypatch):
    def boom(sql):
        raise fs.SearchError("provider not found")

    monkeypatch.setattr(fs, "_run_query", boom)
    assert "Searching Windows" in fs.find_files({"text": "x"})


def test_not_windows_and_missing_pywin32(monkeypatch):
    for reason, words in (("not windows", "only works on Windows"), ("pywin32 missing", "pip install pywin32")):
        def boom(sql, r=reason):
            raise fs.SearchError(r)

        monkeypatch.setattr(fs, "_run_query", boom)
        assert words in fs.find_files({"text": "x"})


def test_real_run_query_off_windows(monkeypatch):
    monkeypatch.setattr(fs.sys, "platform", "linux")
    with pytest.raises(fs.SearchError):
        _REAL_RUN("SELECT 1")


def test_open_result_by_number_and_word(fake, tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.docx"
    a.write_text("x")
    b.write_text("x")
    fake["rows"] = [(str(a), 0.0), (str(b), 0.0)]
    fs.find_files({"text": "x"})
    assert fs.open_result({"number": 2}) == "Opening b.docx."
    assert fs.open_result({"number": "first"}) == "Opening a.pdf."
    assert fs.open_result({"number": "the second one"}) == "Opening b.docx."
    assert fake["opened"] == [str(b), str(a), str(b)]


def test_open_result_out_of_range_and_none(fake, tmp_path):
    assert "no search results" in fs.open_result({"number": 1})
    fake["rows"] = [(str(tmp_path / "a.pdf"), 0.0)]
    fs.find_files({"text": "x"})
    assert "only have 1 result" in fs.open_result({"number": 4})
    assert "only have 1 result" in fs.open_result({"number": 0})


def test_open_result_missing_file(fake, tmp_path):
    fake["rows"] = [(str(tmp_path / "gone.pdf"), 0.0)]
    fs.find_files({"text": "x"})
    assert "not there any more" in fs.open_result({"number": 1})
    assert fake["opened"] == []


def test_open_result_never_runs_programs(fake, tmp_path):
    p = tmp_path / "setup.exe"
    p.write_text("x")
    fake["rows"] = [(str(p), 0.0)]
    fs.find_files({"text": "x"})
    assert "won't open it" in fs.open_result({"number": 1})
    assert fake["opened"] == []


def test_to_epoch():
    d = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert fs._to_epoch(d) == d.timestamp()
    assert fs._to_epoch(datetime(2026, 1, 1)) == d.timestamp()  # naive = UTC
    assert fs._to_epoch(None) == 0.0


def test_catalog_shape():
    assert set(fs.CATALOG) == set(fs.HANDLERS) == {"find_files", "open_result"}
    assert fs.CATALOG["find_files"]["info"] is True
    assert not fs.CATALOG["open_result"].get("info")
