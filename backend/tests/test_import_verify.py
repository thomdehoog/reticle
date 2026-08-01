"""Catching a migration that arrived complete and wrong.

The reconciliation report counts things, and counting catches a run that lost
half a corpus. It does not catch one where a step arrived with the right number
of bullets and different words in them, and it does not catch the failure that
matters most once a language model is anywhere near a pipeline: content in
Reticle that the source never had. A guide with an extra sentence in it reads
perfectly well, which is exactly why nobody finds it.

So the check here re-reads the source and compares the content, and it reports
those two failures separately — a value that differs is a loss, a value that
exists only on this side is an invention. The tests below plant one of each and
require that it is named precisely enough to go and look at.
"""

from __future__ import annotations

from sqlalchemy import select

from app.importer.run import Importer
from app.importer.verify import verify
from app.models import Bullet, Guide, Step
from app.settings import get_settings

from .test_import_run import FakeDozuki, _guide, _options

import pytest


@pytest.fixture()
def author_account(make_user):
    return make_user("admin@zmb.uzh.ch", role="admin")


def imported(db_session, client) -> Importer:
    importer = Importer(db_session, client, _options(), get_settings())
    importer.import_guides()
    return importer


def test_an_untouched_import_verifies_clean(db_session, author_account, media_root):
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    report = verify(db_session, client)

    assert report.faithful, report.to_text()
    assert "faithful copy" in report.to_text()


def test_a_changed_bullet_is_reported_as_drift(db_session, author_account, media_root):
    """The failure counting cannot see: right number of bullets, wrong words."""
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    bullet = db_session.scalars(select(Bullet).order_by(Bullet.order_index)).first()
    bullet.text = "Switch on something else entirely."
    db_session.commit()

    report = verify(db_session, client)

    assert not report.faithful
    verdict = report.verdicts[0]
    assert verdict.drift and not verdict.invention
    assert "bullet 1 text" in str(verdict.drift[0])
    assert "something else entirely" in report.to_text()


def test_a_recoloured_bullet_is_reported(db_session, author_account, media_root):
    """A caution that arrives as a note is a safety warning that stopped being one."""
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    bullet = db_session.scalars(select(Bullet).where(Bullet.icon == "caution")).one()
    bullet.icon = "note"
    bullet.color = "blue"
    db_session.commit()

    report = verify(db_session, client)

    assert not report.faithful
    assert any("flag" in str(d) for d in report.verdicts[0].drift)


def test_an_extra_bullet_is_reported_as_invention_not_drift(
    db_session, author_account, media_root
):
    """Nothing in this importer writes prose, so an extra sentence has an author."""
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    step = db_session.scalars(select(Step).order_by(Step.order_index)).first()
    db_session.add(
        Bullet(
            step_id=step.id,
            order_index=99,
            text="Also remember to calibrate the stage.",
            color="black",
            level=0,
        )
    )
    db_session.commit()

    report = verify(db_session, client)

    assert not report.faithful
    verdict = report.verdicts[0]
    assert verdict.invention
    assert any("bullet count" in str(d) for d in verdict.invention)
    assert "CONTENT WITH NO SOURCE" in report.to_text()


def test_an_extra_step_is_reported_as_invention(db_session, author_account, media_root):
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    guide = db_session.scalars(select(Guide)).one()
    db_session.add(Step(guide_id=guide.id, order_index=99, title="A step nobody wrote"))
    db_session.commit()

    report = verify(db_session, client)

    assert any("step count" in str(d) for d in report.verdicts[0].invention)


def test_a_summary_that_the_source_leaves_empty_is_an_invention(
    db_session, author_account, media_root
):
    """Filling a gap is the most plausible thing a generator would do."""
    payload = _guide()
    payload["summary"] = ""
    client = FakeDozuki([payload])
    imported(db_session, client)

    guide = db_session.scalars(select(Guide)).one()
    guide.summary = "A helpful summary that nobody at ZMB wrote."
    db_session.commit()

    report = verify(db_session, client)

    assert report.verdicts[0].invention
    assert any("summary" in str(d) for d in report.verdicts[0].invention)


def test_a_tag_nobody_applied_is_reported(db_session, author_account, media_root):
    from app.models import GuideTag, Tag

    client = FakeDozuki([_guide()])
    imported(db_session, client)

    guide = db_session.scalars(select(Guide)).one()
    tag = Tag(slug="invented", name="invented")
    db_session.add(tag)
    db_session.flush()
    db_session.add(GuideTag(guide_id=guide.id, tag_id=tag.id, order_index=9))
    db_session.commit()

    report = verify(db_session, client)

    assert any("not on the source" in str(d) for d in report.verdicts[0].invention)


def test_a_moved_annotation_is_reported(db_session, author_account, media_root):
    """A shape that drifts stops pointing at the control the bullet names."""
    from app.models import Annotation

    client = FakeDozuki([_guide()])
    imported(db_session, client)

    shape = db_session.scalars(select(Annotation)).one()
    shape.x = 0.7
    db_session.commit()

    report = verify(db_session, client)

    assert any("shape 1 x" in str(d) for d in report.verdicts[0].drift)


def test_an_annotation_nobody_drew_is_an_invention(db_session, author_account, media_root):
    from app.models import Annotation, Media

    client = FakeDozuki([_guide()])
    imported(db_session, client)

    media = db_session.scalars(select(Media)).first()
    db_session.add(
        Annotation(media_id=media.id, order_index=9, shape="ellipse", color="green", x=0.1, y=0.1, width=0.1, height=0.1)
    )
    db_session.commit()

    report = verify(db_session, client)

    assert any("shape count" in str(d) for d in report.verdicts[0].invention)


def test_a_guide_that_cannot_be_re_fetched_is_reported_rather_than_passed(
    db_session, author_account, media_root
):
    """Silence about a guide nobody could check is the same as claiming it is fine."""
    client = FakeDozuki([_guide()])
    imported(db_session, client)

    from app.importer.client import MigrationError

    def refuse(_guide_id):
        raise MigrationError("503 from the source")

    client.get_guide = refuse

    report = verify(db_session, client)

    assert not report.faithful
    assert report.verdicts[0].unreachable
    assert "COULD NOT BE RE-FETCHED" in report.to_text()


def test_the_json_report_carries_each_difference(db_session, author_account, media_root):
    import json

    client = FakeDozuki([_guide()])
    imported(db_session, client)
    bullet = db_session.scalars(select(Bullet)).first()
    bullet.text = "changed"
    db_session.commit()

    decoded = json.loads(verify(db_session, client).to_json())

    assert decoded["faithful"] is False
    assert decoded["guides"][0]["drift"][0]["found"] == "changed"


def test_the_check_can_be_limited_to_a_sample(db_session, author_account, media_root):
    """Two hundred and fifty-seven re-fetches is a long wait for a first look."""
    client = FakeDozuki([_guide(1), _guide(2, title="Second"), _guide(3, title="Third")])
    imported(db_session, client)

    report = verify(db_session, client, limit=2)

    assert len(report.verdicts) == 2
