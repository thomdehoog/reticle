"""Shapes drawn over a step image.

An annotation is stored as data rather than burned into the pixels, which is
what keeps the upload intact and the shape editable — and what makes the
persistence its own failure surface. The shapes live on the media row, not on
the step, so they are saved by the same whole-document ``PUT`` as everything
else and replaced wholesale on each save. Get that wrong in either direction and
the editor either accumulates shapes an author deleted or silently drops the
ones they drew.

The colour is deliberately the bullet palette and nothing wider: a red shape on
the picture and the red bullet beside it are one instruction, and a colour that
exists only on the overlay breaks that pairing. The coordinates are fractions
for the same reason — bounded rather than clamped, because an author aiming at
something on the edge of an image legitimately drags a little past it, while a
value far outside is either a bug or an attempt to cover the whole page.
"""

from __future__ import annotations

import pytest
from ulid import ULID

from .conftest import annotated, annotation, create_guide, document_from, step, upload_media


def save_annotations(client, guide: dict, image: dict, *shapes: dict):
    return client.put(
        f"/api/guides/{guide['id']}",
        json=document_from(
            guide, steps=[step("Mount the sample", media=[annotated(image, *shapes)])]
        ),
    )


def stored(body: dict) -> list[dict]:
    return body["steps"][0]["media"][0]["annotations"]


def test_annotations_round_trip_through_the_document_save(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(
        author,
        created,
        image,
        annotation(shape="rectangle", color="red", x=0.1, y=0.2, width=0.3, height=0.4),
    )

    assert response.status_code == 200, response.text
    shape = stored(response.json())[0]
    assert set(shape) == {"id", "shape", "color", "x", "y", "width", "height"}
    assert shape["shape"] == "rectangle"
    assert shape["color"] == "red"
    assert (shape["x"], shape["y"], shape["width"], shape["height"]) == (0.1, 0.2, 0.3, 0.4)


def test_annotations_survive_a_reload(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    save_annotations(author, created, image, annotation(color="green"))

    reloaded = author.get(f"/api/guides/{created['id']}").json()

    assert [s["color"] for s in stored(reloaded)] == ["green"]


@pytest.mark.parametrize("shape", ["rectangle", "ellipse", "arrow"])
def test_every_shape_in_the_vocabulary_is_accepted(author, category, shape):
    created = create_guide(author, category.id)
    image = upload_media(author)

    body = save_annotations(author, created, image, annotation(shape=shape)).json()

    assert stored(body)[0]["shape"] == shape


def test_an_unknown_shape_is_rejected(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    assert save_annotations(author, created, image, annotation(shape="freehand")).status_code == 422


def test_the_drawing_order_is_preserved(author, category):
    """Shapes overlap, so which one is drawn last is which one is legible."""
    created = create_guide(author, category.id)
    image = upload_media(author)

    body = save_annotations(
        author,
        created,
        image,
        annotation(shape="rectangle", color="red"),
        annotation(shape="ellipse", color="blue"),
        annotation(shape="arrow", color="violet"),
    ).json()

    assert [s["shape"] for s in stored(body)] == ["rectangle", "ellipse", "arrow"]
    assert [s["color"] for s in stored(body)] == ["red", "blue", "violet"]


def test_a_client_supplied_annotation_id_is_honoured(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    shape_id = str(ULID())

    body = save_annotations(author, created, image, annotation(annotation_id=shape_id)).json()

    assert stored(body)[0]["id"] == shape_id


def test_an_unusable_annotation_id_is_replaced_rather_than_refusing_the_save(author, category):
    """The identifier is cosmetic here — the set is rewritten wholesale — so an
    editor that has not minted one yet must not lose the author's drawing."""
    created = create_guide(author, category.id)
    image = upload_media(author)

    body = save_annotations(author, created, image, annotation(annotation_id="not-a-ulid")).json()

    assert len(stored(body)) == 1
    assert stored(body)[0]["id"] != "not-a-ulid"


def test_each_save_replaces_the_whole_set_rather_than_appending(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    first = save_annotations(
        author,
        created,
        image,
        annotation(shape="rectangle"),
        annotation(shape="ellipse"),
    ).json()

    second = save_annotations(
        author, first, image, annotation(shape="arrow", color="orange")
    ).json()

    assert [s["shape"] for s in stored(second)] == ["arrow"]
    assert [s["color"] for s in stored(second)] == ["orange"]


def test_clearing_every_shape_leaves_the_image_in_place(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    first = save_annotations(author, created, image, annotation()).json()

    cleared = save_annotations(author, first, image).json()

    assert stored(cleared) == []
    assert cleared["steps"][0]["media"][0]["id"] == image["id"]


@pytest.mark.parametrize(
    "color",
    ["black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet"],
)
def test_the_whole_bullet_palette_is_available_to_a_shape(author, category, color):
    created = create_guide(author, category.id)
    image = upload_media(author)

    body = save_annotations(author, created, image, annotation(color=color)).json()

    assert stored(body)[0]["color"] == color


@pytest.mark.parametrize("color", ["chartreuse", "#ff0000", "warning", "purple"])
def test_a_colour_outside_the_bullet_palette_is_rejected(author, category, color):
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(author, created, image, annotation(color=color))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_shape_may_overhang_the_edge_of_the_image_slightly(author, category):
    """Aiming at a control hard against the border of a screenshot overshoots."""
    created = create_guide(author, category.id)
    image = upload_media(author)

    body = save_annotations(
        author,
        created,
        image,
        annotation(x=-0.04, y=0.9, width=0.2, height=0.14),
    ).json()

    assert (stored(body)[0]["x"], stored(body)[0]["y"]) == (-0.04, 0.9)


def test_an_arrow_may_point_left_and_up(author, category):
    """The head is the whole point of an arrow, so its extents carry a sign.

    An author pointing at something on the left of a screenshot drags leftwards.
    Refusing a negative extent would make that guide unsaveable from then on —
    every autosave rejected, with the editor able to say only "could not save".
    """
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(
        author,
        created,
        image,
        annotation(shape="arrow", x=0.8, y=0.8, width=-0.5, height=-0.5),
    )

    assert response.status_code == 200, response.text
    saved = stored(response.json())[0]
    assert (saved["width"], saved["height"]) == (-0.5, -0.5)


@pytest.mark.parametrize("shape", ["rectangle", "ellipse"])
def test_a_box_with_a_negative_extent_is_refused(author, category, shape):
    """Only an arrow has a direction; a box is stored from its top-left corner.

    The client normalises a drag before sending it, so a negative extent here is
    a client that has drifted from the shared geometry — and a rectangle with a
    negative width draws as nothing at all.
    """
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(
        author, created, image, annotation(shape=shape, x=0.5, y=0.5, width=-0.2, height=0.2)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_shape_that_would_sit_off_the_image_is_refused(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(
        author, created, image, annotation(x=0.9, y=0.9, width=0.5, height=0.5)
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "coordinates",
    [
        {"x": 2.5},
        {"x": -1.5},
        {"y": 42.0},
        {"width": 3.0},
        {"height": -2.5},
    ],
)
def test_a_shape_far_outside_the_image_is_rejected(author, category, coordinates):
    created = create_guide(author, category.id)
    image = upload_media(author)

    response = save_annotations(author, created, image, annotation(**coordinates))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_sixty_shapes_fit_and_a_sixty_first_does_not(author, category):
    created = create_guide(author, category.id)
    image = upload_media(author)
    sixty = [annotation(x=index / 100) for index in range(60)]

    accepted = save_annotations(author, created, image, *sixty)
    refused = save_annotations(author, accepted.json(), image, *sixty, annotation())

    assert accepted.status_code == 200
    assert len(stored(accepted.json())) == 60
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"


def test_shapes_are_kept_per_image_not_per_step(author, category):
    created = create_guide(author, category.id)
    first_image = upload_media(author)
    second_image = upload_media(author)

    body = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created,
            steps=[
                step(
                    "Two pictures",
                    media=[
                        annotated(first_image, annotation(shape="arrow", color="red")),
                        annotated(second_image),
                    ],
                )
            ],
        ),
    ).json()

    pictures = body["steps"][0]["media"]
    assert [s["shape"] for s in pictures[0]["annotations"]] == ["arrow"]
    assert pictures[1]["annotations"] == []


def test_annotations_are_captured_in_the_publish_snapshot(author, category):
    """A revision is what a citation of "version 1" resolves to, so a snapshot
    that dropped the overlay would answer a safety question with the wrong
    picture."""
    created = create_guide(author, category.id)
    image = upload_media(author)
    saved = save_annotations(
        author,
        created,
        image,
        annotation(shape="arrow", color="red", x=0.5, y=0.5, width=0.1, height=0.1),
    ).json()
    author.post(f"/api/guides/{saved['id']}/publish")

    reloaded = author.get(f"/api/guides/{created['id']}").json()
    save_annotations(author, reloaded, image, annotation(shape="ellipse", color="green"))

    snapshot = author.get(f"/api/guides/{created['id']}/revisions/1").json()

    assert [s["shape"] for s in snapshot["steps"][0]["media"][0]["annotations"]] == ["arrow"]
    assert snapshot["steps"][0]["media"][0]["annotations"][0]["color"] == "red"


def test_a_viewer_cannot_annotate(author, viewer, category):
    created = create_guide(author, category.id)
    image = upload_media(author)

    assert save_annotations(viewer, created, image, annotation()).status_code == 403
