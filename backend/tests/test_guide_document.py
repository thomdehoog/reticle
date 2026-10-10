"""The whole-document ``PUT`` that backs the editor's autosave.

These are the behaviours the editor depends on and cannot compensate for on the
client: contiguous renumbering, the media cap, referential checks, and the
optimistic-concurrency guard that stops one ZMB author silently overwriting
another.
"""

from __future__ import annotations

from sqlalchemy import func, select
from ulid import ULID

import pytest

from app.models import StepMedia, Tag

from .conftest import (
    annotation,
    bullet,
    create_guide,
    document_from,
    instant,
    publish_guide,
    save_guide,
    step,
    upload_media,
    upload_video,
)


def test_put_returns_the_saved_document(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            title="Sample Preparation for CLEM",
            summary="Correlative workflow from fixation to imaging.",
            difficulty="difficult",
            timeRequiredMinMinutes=30,
            timeRequiredMaxMinutes=90,
            introduction="Read the safety sheet first.",
            conclusion="Log the session in the booking system.",
            steps=[step("Fix the sample", bullets=[bullet("Use 4% PFA", color="orange", icon="caution")])],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Sample Preparation for CLEM"
    assert body["summary"] == "Correlative workflow from fixation to imaging."
    assert body["difficulty"] == "difficult"
    assert body["timeRequiredMinMinutes"] == 30
    assert body["timeRequiredMaxMinutes"] == 90
    assert body["introduction"] == "Read the safety sheet first."
    assert body["conclusion"] == "Log the session in the booking system."
    assert body["steps"][0]["bullets"][0] == {
        "id": body["steps"][0]["bullets"][0]["id"],
        "text": "Use 4% PFA",
        "color": "orange",
        "icon": "caution",
        "level": 0,
    }


def test_order_index_is_renumbered_contiguously_from_zero(author, category):
    created = create_guide(author, category.id)

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            steps=[
                {"title": "First", "orderIndex": 41, "bullets": [], "media": []},
                {"title": "Second", "orderIndex": 7, "bullets": [], "media": []},
                {"title": "Third", "orderIndex": 41, "bullets": [], "media": []},
            ],
        ),
    ).json()

    assert [s["orderIndex"] for s in body["steps"]] == [0, 1, 2]
    assert [s["title"] for s in body["steps"]] == ["First", "Second", "Third"]


def test_reordering_is_a_plain_array_move(author, category):
    created = create_guide(author, category.id)
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("A"), step("B"), step("C")]),
    ).json()

    moved = list(saved["steps"])
    moved.insert(0, moved.pop(2))
    reordered = author.put(f"/api/guides/{created['id']}", json=document_from(saved, steps=moved)).json()

    assert [s["title"] for s in reordered["steps"]] == ["C", "A", "B"]
    assert [s["orderIndex"] for s in reordered["steps"]] == [0, 1, 2]
    assert [s["id"] for s in reordered["steps"]] == [saved["steps"][2]["id"], saved["steps"][0]["id"], saved["steps"][1]["id"]]


def test_step_identity_survives_a_reorder(author, category):
    created = create_guide(author, category.id)
    saved = author.put(f"/api/guides/{created['id']}", json=document_from(created, steps=[step("A"), step("B")])).json()
    original_ids = {s["title"]: s["id"] for s in saved["steps"]}

    reordered = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(saved, steps=list(reversed(saved["steps"]))),
    ).json()

    assert {s["title"]: s["id"] for s in reordered["steps"]} == original_ids


def test_bullets_keep_their_authored_order(author, category):
    created = create_guide(author, category.id)

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            steps=[
                step(
                    "Mount",
                    bullets=[
                        bullet("Top level", level=0),
                        bullet("Detail", level=1, color="blue", icon="note"),
                        bullet("Sub detail", level=2, color="violet"),
                    ],
                )
            ],
        ),
    ).json()

    assert [b["text"] for b in body["steps"][0]["bullets"]] == ["Top level", "Detail", "Sub detail"]
    assert [b["level"] for b in body["steps"][0]["bullets"]] == [0, 1, 2]
    assert "orderIndex" not in body["steps"][0]["bullets"][0]


def test_removed_steps_and_bullets_are_deleted(author, category, db_session):
    from app.models import Bullet, Step

    created = create_guide(author, category.id)
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Keep", bullets=[bullet("a"), bullet("b")]), step("Drop")]),
    ).json()

    kept = saved["steps"][0]
    kept["bullets"] = kept["bullets"][:1]
    trimmed = author.put(f"/api/guides/{created['id']}", json=document_from(saved, steps=[kept])).json()

    assert [s["title"] for s in trimmed["steps"]] == ["Keep"]
    assert [b["text"] for b in trimmed["steps"][0]["bullets"]] == ["a"]
    assert db_session.query(Step).count() == 1
    assert db_session.query(Bullet).count() == 1


def test_client_supplied_ids_are_honoured_so_optimistic_ui_stays_stable(author, category):
    created = create_guide(author, category.id)
    step_id = str(ULID())
    bullet_id = str(ULID())

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Local", bullets=[bullet("Local", bullet_id=bullet_id)], step_id=step_id)]),
    ).json()

    assert body["steps"][0]["id"] == step_id
    assert body["steps"][0]["bullets"][0]["id"] == bullet_id


def test_a_step_id_belonging_to_another_guide_is_rejected(author, category):
    first = create_guide(author, category.id, "First")
    second = create_guide(author, category.id, "Second")
    saved = author.put(f"/api/guides/{first['id']}", json=document_from(first, steps=[step("Owned")])).json()

    response = author.put(
        f"/api/guides/{second['id']}",
        json=document_from(second, steps=[step("Stolen", step_id=saved["steps"][0]["id"])]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_malformed_step_id_is_rejected(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Bad", step_id="../../etc/passwd")]),
    )

    assert response.status_code == 422


def test_at_most_three_media_per_step(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(4)]

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Too many", media=media)]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "3" in response.json()["error"]["message"]


def test_exactly_three_media_is_allowed(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(3)]

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Three", media=media)]),
    ).json()

    assert [m["id"] for m in body["steps"][0]["media"]] == [m["id"] for m in media]
    assert body["steps"][0]["media"][0]["url"] == f"/api/media/{media[0]['id']}"


def test_the_cap_is_per_step_not_per_guide(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(4)]

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("A", media=media[:3]), step("B", media=media[3:])]),
    ).json()

    assert [len(s["media"]) for s in body["steps"]] == [3, 1]


def test_media_order_within_a_step_is_preserved(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(3)]
    reversed_media = list(reversed(media))

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Ordered", media=reversed_media)]),
    ).json()

    assert [m["id"] for m in body["steps"][0]["media"]] == [m["id"] for m in reversed_media]


def test_an_unknown_media_id_is_rejected(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            steps=[
                step(
                    "Ghost",
                    media=[{"id": str(ULID()), "kind": "image", "url": "/api/media/x", "alt": "", "width": 1, "height": 1, "annotations": []}],
                )
            ],
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_alt_text_is_saved_through_the_document(author, category):
    created = create_guide(author, category.id)
    media = upload_media(author)
    media["alt"] = "Turret with the 63x objective seated."

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Alt", media=[media])]),
    ).json()

    assert body["steps"][0]["media"][0]["alt"] == "Turret with the 63x objective seated."
    assert author.get(f"/api/guides/{created['id']}").json()["steps"][0]["media"][0]["alt"] == media["alt"]


def test_prerequisites_are_gone_from_the_model(author, category):
    """Zero of ZMB's 257 guides used them. A client that still sends the field
    is not refused — the editor round-trips whatever it holds — but nothing is
    stored and nothing comes back."""
    target = create_guide(author, category.id, "Main Guide")
    other = create_guide(author, category.id, "Other Guide")

    body = save_guide(author, target, prerequisiteIds=[other["id"]])

    assert "prerequisiteIds" not in body
    assert "prerequisiteIds" not in author.get(f"/api/guides/{target['id']}").json()


def test_moving_a_guide_to_an_unknown_category_is_rejected(author, category):
    created = create_guide(author, category.id)

    response = author.put(f"/api/guides/{created['id']}", json=document_from(created, categoryId=str(ULID())))

    assert response.status_code == 422


def test_a_stale_updated_at_conflicts_and_changes_nothing(author, as_role, category):
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch")

    fresh = author.get(f"/api/guides/{created['id']}").json()
    colleague.put(f"/api/guides/{created['id']}", json=document_from(fresh, title="Colleague's title"))

    response = author.put(f"/api/guides/{created['id']}", json=document_from(fresh, title="My title"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert author.get(f"/api/guides/{created['id']}").json()["title"] == "Colleague's title"


def test_a_current_updated_at_saves_and_moves_the_clock_forward(author, category):
    created = create_guide(author, category.id)

    saved = author.put(f"/api/guides/{created['id']}", json=document_from(created, title="Renamed")).json()

    assert saved["title"] == "Renamed"
    assert instant(saved["updatedAt"]) > instant(created["updatedAt"])
    assert saved["createdAt"] == created["createdAt"]


def test_consecutive_autosaves_chain_without_conflicting(author, category):
    document = create_guide(author, category.id)

    for index in range(4):
        response = author.put(f"/api/guides/{document['id']}", json=document_from(document, title=f"Revision {index}"))
        assert response.status_code == 200, response.text
        document = response.json()

    assert document["title"] == "Revision 3"


def test_a_missing_expected_updated_at_is_rejected_rather_than_assumed_current(author, category):
    """``updatedAt`` alone does not count: the token has its own name precisely
    so that echoing the object back cannot pass for a concurrency check."""
    created = create_guide(author, category.id)
    body = document_from(created)
    del body["expectedUpdatedAt"]

    response = author.put(f"/api/guides/{created['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "expectedUpdatedAt" in response.json()["error"]["message"]


def test_a_token_from_the_future_conflicts_too(author, category):
    """Any mismatch means the client is not looking at the stored row."""
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, expectedUpdatedAt="2999-01-01T00:00:00.000000Z"),
    )

    assert response.status_code == 409


def test_a_token_without_a_timezone_is_read_as_utc(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, expectedUpdatedAt=created["updatedAt"].rstrip("Z")),
    )

    assert response.status_code == 200


def test_publishing_moves_the_token_so_a_pre_publish_copy_is_stale(author, category):
    created = create_guide(author, category.id)
    saved = save_guide(author, created, steps=[step("One", bullets=[bullet("Text")])])
    publish_guide(author, saved)

    response = author.put(f"/api/guides/{created['id']}", json=document_from(saved, title="From the old copy"))

    assert response.status_code == 409


def test_the_save_records_who_edited_last(author, as_role, category):
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    fresh = colleague.get(f"/api/guides/{created['id']}").json()
    saved = colleague.put(f"/api/guides/{created['id']}", json=document_from(fresh, title="Edited")).json()

    assert saved["lastEditedBy"]["displayName"] == "Colleague Editor"
    assert saved["author"]["displayName"] == "Author"


def test_status_slug_and_version_are_not_writable_through_the_document(author, category):
    created = create_guide(author, category.id)

    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, status="published", slug="hijacked", version=99),
    ).json()

    assert saved["status"] == "draft"
    assert saved["slug"] == created["slug"]
    assert saved["version"] == 0


def test_an_invalid_enumeration_value_is_rejected(author, category):
    created = create_guide(author, category.id)

    assert author.put(f"/api/guides/{created['id']}", json=document_from(created, difficulty="trivial")).status_code == 422
    assert (
        author.put(
            f"/api/guides/{created['id']}",
            json=document_from(created, steps=[step("Bad", bullets=[bullet("x", color="chartreuse")])]),
        ).status_code
        == 422
    )
    assert (
        author.put(
            f"/api/guides/{created['id']}",
            json=document_from(created, steps=[step("Bad", bullets=[bullet("x", level=3)])]),
        ).status_code
        == 422
    )


def test_viewers_cannot_save_a_guide(author, viewer, category):
    created = create_guide(author, category.id)

    response = viewer.put(f"/api/guides/{created['id']}", json=document_from(created, title="Hijacked"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_saving_an_unknown_guide_is_not_found(author, category):
    created = create_guide(author, category.id)

    response = author.put(f"/api/guides/{ULID()}", json=document_from(created))

    assert response.status_code == 404


def test_a_published_guide_can_still_be_edited_and_the_reader_sees_the_new_text(author, viewer, category):
    created = create_guide(author, category.id)
    published = publish_guide(author, created)

    save_guide(author, published, steps=[step("Added after publish")])

    assert [s["title"] for s in viewer.get(f"/api/guides/{created['slug']}").json()["steps"]] == ["Added after publish"]


def test_an_empty_title_can_be_autosaved(author, category):
    """Clearing the title to retype it must not make the autosave underneath
    start failing; publishing is where a title becomes compulsory."""
    created = create_guide(author, category.id)

    saved = save_guide(author, created, title="")

    assert saved["title"] == ""
    assert saved["slug"] == created["slug"]


# --------------------------------------------------------------------- tags


def test_tags_are_slugged_sorted_and_created_on_first_use(author, category, db_session):
    created = create_guide(author, category.id)

    saved = save_guide(author, created, tags=["  LAS X ", "Stellaris", "confocal"])

    assert saved["tags"] == ["confocal", "las-x", "stellaris"]
    stored = {tag.slug: tag.name for tag in db_session.scalars(select(Tag))}
    assert stored == {"las-x": "LAS X", "stellaris": "Stellaris", "confocal": "confocal"}


def test_the_first_spelling_of_a_tag_stays_its_name(author, category, db_session):
    first = create_guide(author, category.id, "First")
    second = create_guide(author, category.id, "Second")

    save_guide(author, first, tags=["LAS X"])
    saved = save_guide(author, second, tags=["las x", "Las-X"])

    assert saved["tags"] == ["las-x"]
    assert [tag.name for tag in db_session.scalars(select(Tag))] == ["LAS X"]


def test_the_slug_rule_matches_the_tag_input_in_the_frontend():
    """``slugifyTag`` in ``TagInput.tsx`` claims to match the server. These are
    the cases where a transliterating slugger would quietly disagree with it."""
    from app.slugs import tag_slug

    assert tag_slug("LAS X") == "las-x"
    assert tag_slug("  3D / SIM  ") == "3d-sim"
    assert tag_slug("Zürich") == "z-rich"
    assert tag_slug("--confocal--") == "confocal"
    assert tag_slug("!!!") == ""


def test_tags_can_be_removed_and_replaced(author, category):
    created = create_guide(author, category.id)
    saved = save_guide(author, created, tags=["confocal", "stellaris"])

    saved = save_guide(author, saved, tags=["stellaris", "fiji"])

    assert saved["tags"] == ["fiji", "stellaris"]
    assert save_guide(author, saved, tags=[])["tags"] == []


def test_a_tag_with_no_letter_or_digit_is_rejected(author, category):
    created = create_guide(author, category.id)

    response = author.put(f"/api/guides/{created['id']}", json=document_from(created, tags=["confocal", " ?! "]))

    assert response.status_code == 422
    assert "tag" in response.json()["error"]["message"].lower()


def test_at_most_thirty_tags_of_at_most_sixty_characters(author, category):
    created = create_guide(author, category.id)

    at_the_limit = save_guide(author, created, tags=[f"tag-{index:02d}" for index in range(29)] + ["x" * 60])
    assert len(at_the_limit["tags"]) == 30

    too_many = document_from(at_the_limit, tags=[f"tag-{index:02d}" for index in range(31)])
    too_long = document_from(at_the_limit, tags=["x" * 61])
    assert author.put(f"/api/guides/{created['id']}", json=too_many).status_code == 422
    assert author.put(f"/api/guides/{created['id']}", json=too_long).status_code == 422


def test_two_guides_introducing_the_same_tag_at_once_share_it(author, category, db_session):
    """With two workers both saves can find the tag missing and both try to
    create it. The loser must adopt the winner's row, not fail the save."""
    from app import documents

    winner = Tag(slug="lightsheet", name="Lightsheet")
    db_session.add(winner)
    db_session.commit()

    adopted = documents._create_tag(db_session, "lightsheet", "lightsheet")

    assert adopted.id == winner.id
    assert db_session.scalars(select(Tag)).all() == [winner]


# --------------------------------------------------------------- field rules


def test_time_is_a_range_and_either_end_may_be_open(author, category):
    created = create_guide(author, category.id)

    saved = save_guide(author, created, timeRequiredMinMinutes=30, timeRequiredMaxMinutes=None)
    assert (saved["timeRequiredMinMinutes"], saved["timeRequiredMaxMinutes"]) == (30, None)

    saved = save_guide(author, saved, timeRequiredMinMinutes=None, timeRequiredMaxMinutes=90)
    assert (saved["timeRequiredMinMinutes"], saved["timeRequiredMaxMinutes"]) == (None, 90)

    saved = save_guide(author, saved, timeRequiredMinMinutes=45, timeRequiredMaxMinutes=45)
    assert (saved["timeRequiredMinMinutes"], saved["timeRequiredMaxMinutes"]) == (45, 45)


def test_a_backwards_or_negative_time_range_is_rejected(author, category):
    created = create_guide(author, category.id)

    backwards = document_from(created, timeRequiredMinMinutes=90, timeRequiredMaxMinutes=30)
    negative = document_from(created, timeRequiredMinMinutes=-5)
    fractional = document_from(created, timeRequiredMaxMinutes=12.5)

    response = author.put(f"/api/guides/{created['id']}", json=backwards)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert author.put(f"/api/guides/{created['id']}", json=negative).status_code == 422
    assert author.put(f"/api/guides/{created['id']}", json=fractional).status_code == 422


@pytest.mark.parametrize("color", ["black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet"])
def test_all_eight_bullet_colours_are_accepted(author, category, color):
    created = create_guide(author, category.id)

    saved = save_guide(author, created, steps=[step("Colour", bullets=[bullet("x", color=color)])])

    assert saved["steps"][0]["bullets"][0]["color"] == color


@pytest.mark.parametrize("icon", [None, "note", "caution", "reminder"])
def test_the_three_flags_and_no_flag_are_accepted(author, category, icon):
    created = create_guide(author, category.id)

    saved = save_guide(author, created, steps=[step("Flag", bullets=[bullet("x", icon=icon)])])

    assert saved["steps"][0]["bullets"][0]["icon"] == icon


def test_the_retired_warning_flag_is_rejected(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Old", bullets=[bullet("x", icon="warning")])]),
    )

    assert response.status_code == 422


# --------------------------------------------------------------- annotations


def test_annotations_are_saved_on_the_image_within_its_step(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    image["annotations"] = [
        annotation("rectangle", "red", x=0.1, y=0.2, width=0.3, height=0.25),
        annotation("arrow", "light_blue", x=0.9, y=0.9, width=-0.4, height=-0.5),
        annotation("ellipse", "green", x=0, y=0, width=1, height=1),
    ]

    saved = save_guide(author, created, steps=[step("Annotated", media=[image])])

    stored = saved["steps"][0]["media"][0]
    assert set(stored) == {"id", "kind", "url", "alt", "width", "height", "annotations"}
    assert [(a["shape"], a["color"]) for a in stored["annotations"]] == [
        ("rectangle", "red"),
        ("arrow", "light_blue"),
        ("ellipse", "green"),
    ]
    assert set(stored["annotations"][0]) == {"id", "shape", "color", "x", "y", "width", "height"}
    assert stored["annotations"][1]["width"] == -0.4
    assert author.get(f"/api/guides/{created['id']}").json()["steps"][0]["media"][0] == stored


def test_annotation_ids_from_the_client_are_kept_and_missing_ones_minted(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    mine = str(ULID())
    image["annotations"] = [{**annotation(), "id": mine}, annotation("ellipse")]

    stored = save_guide(author, created, steps=[step("Ids", media=[image])])["steps"][0]["media"][0]["annotations"]

    assert stored[0]["id"] == mine
    assert stored[1]["id"] and stored[1]["id"] != mine


def test_the_same_upload_reused_in_another_step_starts_clean(author, category, db_session):
    """Annotations belong to the image *within that step*. A screenshot shown
    twice must not carry the first step's arrows into the second."""
    created = create_guide(author, category.id)
    image = upload_media(author)
    annotated = {**image, "alt": "Navigator button", "annotations": [annotation()]}
    plain = {**image, "alt": "The whole window", "annotations": []}

    saved = save_guide(author, created, steps=[step("First", media=[annotated]), step("Second", media=[plain])])

    first, second = (s["media"][0] for s in saved["steps"])
    assert first["id"] == second["id"] == image["id"]
    assert len(first["annotations"]) == 1 and second["annotations"] == []
    assert (first["alt"], second["alt"]) == ("Navigator button", "The whole window")
    assert db_session.scalar(select(func.count()).select_from(StepMedia)) == 2


def test_annotations_survive_an_autosave_that_does_not_touch_them(author, category):
    created = create_guide(author, category.id)
    image = {**upload_media(author), "annotations": [annotation("arrow", "violet")]}
    saved = save_guide(author, created, steps=[step("Keep", media=[image])])

    again = save_guide(author, saved, summary="Only the summary changed.")

    assert again["steps"][0]["media"][0]["annotations"] == saved["steps"][0]["media"][0]["annotations"]


@pytest.mark.parametrize(
    "broken",
    [
        {"x": -0.01},
        {"x": 1.01},
        {"y": 2},
        {"width": 1.5},
        {"height": -1.5},
        {"shape": "polygon"},
        {"color": "chartreuse"},
        {"id": "../../etc/passwd"},
        {"x": "NaN"},
    ],
)
def test_an_annotation_outside_the_rules_is_rejected(author, category, broken):
    created = create_guide(author, category.id)
    image = {**upload_media(author), "annotations": [{**annotation(), **broken}]}

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, steps=[step("Bad", media=[image])])
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_at_most_fifty_annotations_per_image(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    fifty = save_guide(author, created, steps=[step("Busy", media=[{**image, "annotations": [annotation()] * 50}])])
    assert len(fifty["steps"][0]["media"][0]["annotations"]) == 50

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(fifty, steps=[step("Busier", media=[{**image, "annotations": [annotation()] * 51}])]),
    )
    assert response.status_code == 422


def test_a_repeated_annotation_id_on_one_image_is_rejected(author, category):
    created = create_guide(author, category.id)
    repeated = {**annotation(), "id": str(ULID())}
    image = {**upload_media(author), "annotations": [repeated, repeated]}

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, steps=[step("Twice", media=[image])])
    )

    assert response.status_code == 422


# -------------------------------------------------------------------- videos


def test_a_video_sits_in_a_step_like_an_image_and_counts_toward_the_cap(author, category):
    created = create_guide(author, category.id)
    clip = upload_video(author)
    pictures = [upload_media(author) for _ in range(3)]

    saved = save_guide(author, created, steps=[step("Mixed", media=[clip, *pictures[:2]])])
    assert [m["kind"] for m in saved["steps"][0]["media"]] == ["video", "image", "image"]
    assert saved["steps"][0]["media"][0]["width"] is None

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(saved, steps=[step("Too many", media=[clip, *pictures])])
    )
    assert response.status_code == 422
    assert "3" in response.json()["error"]["message"]


def test_a_video_cannot_carry_annotations(author, category):
    created = create_guide(author, category.id)
    clip = {**upload_video(author), "annotations": [annotation()]}

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, steps=[step("Clip", media=[clip])])
    )

    assert response.status_code == 422
    assert "video" in response.json()["error"]["message"].lower()


def test_the_same_file_twice_in_one_step_is_rejected(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, steps=[step("Twice", media=[image, image])])
    )

    assert response.status_code == 422


def test_document_ceilings_hold(author, category):
    """One request must not be able to write tens of thousands of rows."""
    created = create_guide(author, category.id)

    too_many_steps = document_from(created, steps=[step(f"Step {index}") for index in range(201)])
    too_many_bullets = document_from(created, steps=[step("One", bullets=[bullet("x")] * 201)])

    assert author.put(f"/api/guides/{created['id']}", json=too_many_steps).status_code == 422
    assert author.put(f"/api/guides/{created['id']}", json=too_many_bullets).status_code == 422
