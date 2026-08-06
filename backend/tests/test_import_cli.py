"""The command line is the whole interface to a once-only operation.

Somebody runs this at the end of a subscription, reads what it printed, and
decides whether the institute's documentation made it across. So the exit code
has to mean something: a run that lost content must not exit 0 and let a
deployment script carry on to the part where the old site is switched off.
"""

from __future__ import annotations

import json

import pytest

from app.importer import run as run_module
from app.importer.client import MigrationError

from .test_import_run import FakeDozuki, _guide


@pytest.fixture()
def author_account(make_user):
    return make_user("admin@zmb.uzh.ch", role="admin")


class LentSession:
    """The test's own session, lent to the importer with ``close`` disarmed.

    ``main`` closes its session in a ``finally``, and this session belongs to the
    fixtures — closing it would take the assertions after the call with it.

    It is a wrapper rather than ``monkeypatch.setattr(db_session, "close", ...)``,
    which is what it replaces, and the difference is a deadlock. That patch was
    installed on the *fixture's own* session object, and pytest tears `cli` down
    before `db_session`, so `db_session`'s finalizer called the disarmed `close`
    and the session was never closed at all. Its connection stayed checked out of
    the pool for the rest of the run, idle in a transaction, still holding the
    categories a dry run had written and not committed — and the next test to
    insert a category with one of those slugs waited on it until the job was
    killed. `--cov` made it reliable enough to catch.

    Disarming `close` on a wrapper leaves the real session untouched, so the
    fixture that owns it can still close it.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        """Deliberately nothing: the fixture that owns the session closes it."""


@pytest.fixture()
def cli(monkeypatch, db_session, media_root):
    """Run ``main`` against the test database and a scripted API."""

    def _run(argv: list[str], client: FakeDozuki):
        monkeypatch.setattr(run_module, "init_db", lambda: None)
        monkeypatch.setattr(run_module, "SessionLocal", lambda: LentSession(db_session))
        monkeypatch.setattr(run_module, "DozukiClient", lambda *args, **kwargs: client)
        return run_module.main(argv)

    return _run


BASE = ["--base-url", "https://example.test", "--author-email", "admin@zmb.uzh.ch"]


def test_a_clean_run_exits_zero(cli, author_account, capsys):
    assert cli(BASE, FakeDozuki([_guide()])) == 0
    assert "Every guide reconciled exactly." in capsys.readouterr().out


def test_an_unmapped_value_exits_non_zero_even_though_the_guide_was_written(
    cli, author_account, capsys
):
    payload = _guide()
    payload["steps"][0]["lines"][0]["bullet"] = "teal"

    assert cli(BASE, FakeDozuki([payload])) == 3
    captured = capsys.readouterr()
    assert "teal" in captured.out
    assert "does not recognise" in captured.err


def test_allowing_unmapped_values_still_fails_when_the_counts_disagree(cli, author_account, capsys):
    """Accepting a loss knowingly is a decision; hiding it is not."""
    payload = _guide()
    payload["steps"][0]["lines"][0]["bullet"] = "teal"

    assert cli([*BASE, "--allow-unmapped"], FakeDozuki([payload])) == 4
    assert "do not reconcile" in capsys.readouterr().err


def test_a_missing_account_stops_before_anything_is_written(cli, capsys):
    assert cli(BASE, FakeDozuki([_guide()])) == 2
    assert "No account for" in capsys.readouterr().err


def test_the_reports_are_written_where_they_were_asked_for(cli, author_account, tmp_path):
    text_report = tmp_path / "migration.txt"
    json_report = tmp_path / "migration.json"

    code = cli(
        [*BASE, "--report", str(text_report), "--json-report", str(json_report)],
        FakeDozuki([_guide()]),
    )

    assert code == 0
    assert "Reticle migration report" in text_report.read_text(encoding="utf-8")
    decoded = json.loads(json_report.read_text(encoding="utf-8"))
    assert decoded["guidesSeen"] == 1
    assert decoded["balanced"] is True


def test_a_dry_run_writes_no_content_and_still_reports(cli, author_account, db_session, capsys):
    from sqlalchemy import select

    from app.models import Guide

    assert cli([*BASE, "--dry-run"], FakeDozuki([_guide()])) == 0
    assert db_session.scalars(select(Guide)).all() == []
    assert "Guides   1 imported of 1 seen" in capsys.readouterr().out


def test_the_limit_stops_the_walk_early(cli, author_account, db_session):
    from sqlalchemy import select

    from app.models import Guide

    client = FakeDozuki([_guide(1), _guide(2, title="Second"), _guide(3, title="Third")])
    cli([*BASE, "--limit", "1"], client)

    assert len(db_session.scalars(select(Guide)).all()) == 1


def test_guides_only_and_pages_only_split_the_run(cli, author_account, db_session):
    from sqlalchemy import select

    from app.models import Guide, Page

    wikis = {
        "CATEGORY": [
            {
                "wikiid": 1,
                "namespace": "CATEGORY",
                "title": "Light Microscopy",
                "contents_raw": "text",
            }
        ]
    }

    cli([*BASE, "--guides-only"], FakeDozuki([_guide()], wikis))
    assert db_session.scalars(select(Page)).all() == []
    assert len(db_session.scalars(select(Guide)).all()) == 1

    cli([*BASE, "--pages-only"], FakeDozuki([_guide(2, title="Other")], wikis))
    assert len(db_session.scalars(select(Page)).all()) == 1
    assert len(db_session.scalars(select(Guide)).all()) == 1


def test_a_stopped_run_reports_rather_than_traces(cli, author_account, capsys, monkeypatch):
    client = FakeDozuki([_guide()])

    def explode(*_args, **_kwargs):
        raise MigrationError("the catalogue is unreadable")

    monkeypatch.setattr(client, "iter_guides", explode)

    assert cli(BASE, client) == 2
    assert "Migration stopped: the catalogue is unreadable" in capsys.readouterr().err


def test_the_parser_defaults_are_the_cautious_ones():
    """Anything that could lose content has to be asked for explicitly."""
    args = run_module.build_parser().parse_args(["--base-url", "https://example.test"])

    assert args.token is None
    assert args.include_private is False
    assert args.allow_unmapped is False
    assert args.dry_run is False
    assert args.skip_media is False
    assert args.limit is None
