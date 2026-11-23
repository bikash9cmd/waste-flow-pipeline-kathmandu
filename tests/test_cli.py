"""python -m fohor: user mistakes get one line on stderr and exit 2, not a traceback."""
import pytest

from fohor import pipeline
from fohor.__main__ import main
from fohor.source import LocalSource


@pytest.fixture
def published(upstream, lake, tmp_path):
    src = LocalSource(upstream)
    assert pipeline.run_all(src, src, lake)["status"] == "published"
    return str(tmp_path / "lake")


@pytest.mark.parametrize("cmd", [["blockade", "--days", "3"], ["query", "select 1"]])
def test_nothing_published_is_a_usage_error(tmp_path, capsys, cmd):
    assert main(["--lake", str(tmp_path / "empty"), *cmd]) == 2
    out = capsys.readouterr()
    assert out.err.strip() == "fohor: error: nothing published yet; run the pipeline first"
    assert "Traceback" not in out.err and out.out == ""


@pytest.mark.parametrize("days", ["0", "31"])
def test_days_out_of_range_is_a_usage_error(published, capsys, days):
    assert main(["--lake", published, "blockade", "--days", days]) == 2
    assert capsys.readouterr().err.strip() == "fohor: error: days must be between 1 and 30"


def test_bad_sql_is_a_usage_error(published, capsys):
    assert main(["--lake", published, "query", "select no_such_column from municipality_waste"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("fohor: error: query failed:") and "no_such_column" in err


def test_blockade_and_query_succeed(published, capsys):
    assert main(["--lake", published, "blockade", "--days", "7"]) == 0
    assert "9,800 t of waste uncollected" in capsys.readouterr().out
    assert main(["--lake", published, "query", "select count(*) as n from municipality_waste"]) == 0
    assert "18" in capsys.readouterr().out


def test_unexpected_errors_still_raise(published, monkeypatch):
    def boom(*_):
        raise KeyError("bug")

    monkeypatch.setattr("fohor.__main__.blockade_report", boom)
    with pytest.raises(KeyError):
        main(["--lake", published, "blockade"])


def test_rebuild_stops_when_silver_is_blocked(published, monkeypatch, capsys):
    from fohor.storage import open_lake
    from tests.conftest import RELEASE_A

    issue = {"check": "district_census", "severity": "block", "detail": "no 2021 census total for Lalitpur"}
    monkeypatch.setattr(pipeline, "run_silver", lambda lake, release: {"release": release, "issues": [issue],
                                                                       "built": False})

    def must_not_run(*_):
        raise AssertionError("run_gold must not publish the previous silver")

    monkeypatch.setattr(pipeline, "run_gold", must_not_run)
    lake = open_lake(published)
    before = lake.list(f"quality/release={RELEASE_A}/")
    assert main(["--lake", published, "rebuild", "--release", RELEASE_A]) == 1
    assert '"passed": false' in capsys.readouterr().out
    assert len(lake.list(f"quality/release={RELEASE_A}/")) == len(before) + 1
