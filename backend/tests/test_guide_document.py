"""The whole-document ``PUT`` that backs the editor's autosave.

These are the behaviours the editor depends on and cannot compensate for on the
client: contiguous renumbering, the media cap, referential checks, and the
optimistic-concurrency guard that stops one ZMB author silently overwriting
another.
"""

from __future__ import annotations

from ulid import ULID

from .conftest import bullet, create_guide, document_from, instant, step, upload_media


def test_put_returns_the_saved_document(author, category):
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            title="Sample Preparation for CLEM",
            summary="Correlative workflow from fixation to imaging.",
            difficulty="difficult",
            timeRequiredMinMinutes=45,
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
    assert body["timeRequiredMinMinutes"] == 45
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


def test_at_most_four_media_per_step(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(5)]

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Too many", media=media)]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "4" in response.json()["error"]["message"]


def test_exactly_four_media_is_allowed(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(4)]

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Four", media=media)]),
    ).json()

    assert [m["id"] for m in body["steps"][0]["media"]] == [m["id"] for m in media]
    assert body["steps"][0]["media"][0]["url"] == f"/api/media/{media[0]['id']}"


def test_the_cap_is_per_step_not_per_guide(author, category):
    created = create_guide(author, category.id)
    media = [upload_media(author) for _ in range(5)]

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("A", media=media[:4]), step("B", media=media[4:])]),
    ).json()

    assert [len(s["media"]) for s in body["steps"]] == [4, 1]


def test_the_same_image_twice_in_one_step_is_rejected(author, category):
    """The link table is keyed on the pair, so a repeat is a failed insert at
    commit rather than a readable message — unless it is caught here."""
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Twice", media=[image, image])]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_same_step_twice_in_one_guide_is_rejected(author, category):
    created = create_guide(author, category.id)
    saved = author.put(f"/api/guides/{created['id']}", json=document_from(created, steps=[step("Once")])).json()
    repeated = saved["steps"][0]

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(saved, steps=[repeated, dict(repeated)]),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_same_bullet_twice_in_one_step_is_rejected(author, category):
    created = create_guide(author, category.id)
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Once", bullets=[bullet("Only")])]),
    ).json()
    only = saved["steps"][0]
    only["bullets"] = [only["bullets"][0], dict(only["bullets"][0])]

    response = author.put(f"/api/guides/{created['id']}", json=document_from(saved, steps=[only]))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_replacing_the_images_on_an_existing_step_detaches_the_old_ones(author, category):
    """The step survives the save, so its old links have to be cleared rather
    than left beside the new ones."""
    created = create_guide(author, category.id)
    first = upload_media(author)
    second = upload_media(author)
    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Pictures", media=[first])]),
    ).json()

    existing = saved["steps"][0]
    existing["media"] = [second]
    replaced = author.put(f"/api/guides/{created['id']}", json=document_from(saved, steps=[existing])).json()

    assert [m["id"] for m in replaced["steps"][0]["media"]] == [second["id"]]
    assert replaced["steps"][0]["id"] == saved["steps"][0]["id"]


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
            steps=[step("Ghost", media=[{"id": str(ULID()), "url": "/api/media/x", "alt": "", "width": 1, "height": 1}])],
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


def test_either_end_of_the_time_estimate_may_be_left_open(author, category):
    """ZMB writes "from 30 min" and "up to 2 h" as often as a closed range, so a
    single end has to be storable without inventing the other one."""
    created = create_guide(author, category.id)

    lower_only = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, timeRequiredMinMinutes=30, timeRequiredMaxMinutes=None),
    ).json()
    upper_only = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(lower_only, timeRequiredMinMinutes=None, timeRequiredMaxMinutes=120),
    ).json()

    assert (lower_only["timeRequiredMinMinutes"], lower_only["timeRequiredMaxMinutes"]) == (30, None)
    assert (upper_only["timeRequiredMinMinutes"], upper_only["timeRequiredMaxMinutes"]) == (None, 120)


def test_a_single_number_is_expressed_as_an_equal_range(author, category):
    created = create_guide(author, category.id)

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, timeRequiredMinMinutes=45, timeRequiredMaxMinutes=45),
    ).json()

    assert (body["timeRequiredMinMinutes"], body["timeRequiredMaxMinutes"]) == (45, 45)


def test_a_reversed_time_range_is_refused_rather_than_quietly_swapped(author, category):
    """Guessing which of the two numbers the author meant would publish a
    duration nobody wrote."""
    created = create_guide(author, category.id)

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, timeRequiredMinMinutes=90, timeRequiredMaxMinutes=45),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert author.get(f"/api/guides/{created['id']}").json()["timeRequiredMinMinutes"] is None


def test_a_negative_time_estimate_is_rejected(author, category):
    created = create_guide(author, category.id)

    assert (
        author.put(
            f"/api/guides/{created['id']}",
            json=document_from(created, timeRequiredMinMinutes=-1),
        ).status_code
        == 422
    )


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


def test_a_missing_updated_at_is_rejected_rather_than_assumed_current(author, category):
    created = create_guide(author, category.id)
    body = document_from(created)
    del body["updatedAt"]

    response = author.put(f"/api/guides/{created['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


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
    author.post(f"/api/guides/{created['id']}/publish")

    fresh = author.get(f"/api/guides/{created['id']}").json()
    author.put(f"/api/guides/{created['id']}", json=document_from(fresh, steps=[step("Added after publish")]))

    assert [s["title"] for s in viewer.get(f"/api/guides/{created['slug']}").json()["steps"]] == ["Added after publish"]
