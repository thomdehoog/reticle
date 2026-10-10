"""The fixed tables of the import, and the conversion of image markers.

The marker tests work on real pixels. The payload alone does not say which
coordinate space a marker is in or which end of an arrow has the head, so the
converter checks its reading against the marked-up picture — and these tests
check that the check accepts what is right and refuses what is not.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.importer import mapping, markers

from .importer_site import MARKER_GREEN, MARKER_RED, FakeSite, draw_arrow, photo

# ---------------------------------------------------------------- tables


@pytest.mark.parametrize(
    ("vendor", "expected"),
    [
        ("Very easy", "very_easy"),
        ("Easy", "easy"),
        ("Moderate", "moderate"),
        ("Difficult", "difficult"),
        ("Very difficult", "very_difficult"),
        ("very_difficult", "very_difficult"),
        ("  VERY   EASY ", "very_easy"),
    ],
)
def test_the_difficulty_table(vendor, expected):
    assert mapping.difficulty(vendor) == (expected, True)


@pytest.mark.parametrize("vendor", ["Legendary", "", None, 3])
def test_an_unknown_difficulty_falls_back_to_moderate_and_says_so(vendor):
    assert mapping.difficulty(vendor) == ("moderate", False)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(300, 5), (1800, 30), (0, None), (None, None), ("junk", None), (-5, None), (20, 1), (90, 2), (10**9, 100_000), ("600", 10)],
)
def test_seconds_become_whole_minutes(seconds, expected):
    assert mapping.minutes(seconds) == expected


def test_the_time_range_is_ordered_and_open_ended_when_only_one_end_is_set():
    assert mapping.time_range(600, 1200) == (10, 20)
    assert mapping.time_range(0, 300) == (None, 5)
    assert mapping.time_range(1200, 600) == (10, 20)
    assert mapping.time_range(0, 0) == (None, None)


@pytest.mark.parametrize(
    ("vendor", "color", "icon"),
    [
        ("black", "black", None),
        ("red", "red", None),
        ("orange", "orange", None),
        ("yellow", "yellow", None),
        ("green", "green", None),
        ("light_blue", "light_blue", None),
        ("blue", "blue", None),
        ("violet", "violet", None),
        ("icon_note", "black", "note"),
        ("icon_caution", "black", "caution"),
        ("icon_reminder", "black", "reminder"),
    ],
)
def test_every_bullet_value_the_vendor_is_known_to_use(vendor, color, icon):
    assert mapping.bullet({"bullet": vendor}) == (color, icon, True)
    assert mapping.bullet({"bullet": vendor.upper()}) == (color, icon, True)


def test_an_unknown_bullet_takes_the_colour_of_its_style_or_black():
    assert mapping.bullet({"bullet": "custom_17", "bullet_style": {"bullet_color": "#16dc81"}}) == ("green", None, False)
    assert mapping.bullet({"bullet": "custom_17", "bullet_style": {"bullet_color": None}}) == ("black", None, False)
    assert mapping.bullet({"bullet": "icon_skull"}) == ("black", None, False)
    assert mapping.bullet({}) == ("black", None, False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("lightBlue", "light_blue"),
        ("light-blue", "light_blue"),
        ("RED", "red"),
        ("purple", "violet"),
        ("#c1280b", "red"),
        ("#FF9024", "orange"),
        ("15a1d6", "light_blue"),
        ("#000", "black"),
        ("#fe0", "yellow"),
        ("chartreuse", None),
        (None, None),
        ("#12", None),
    ],
)
def test_colours_by_name_and_by_nearest_hex(value, expected):
    assert mapping.color(value) == expected


@pytest.mark.parametrize(("value", "expected"), [(0, (0, True)), (2, (2, True)), (5, (2, False)), (-1, (0, False)), (None, (0, True)), ("x", (0, False)), ("1", (1, True))])
def test_indent_levels_are_held_to_reticles_three(value, expected):
    assert mapping.level(value) == expected


def test_timestamps():
    assert mapping.instant(1788435314).isoformat() == "2026-09-03T11:35:14+00:00"
    assert mapping.instant(0) is None
    assert mapping.instant(None) is None
    assert mapping.instant("soon") is None
    assert mapping.instant(1e30) is None


@pytest.mark.parametrize(
    "name",
    ["Confocal - hidden guides", "IT - hidden Guides", "Image processing - hiden", "hidden - Spatial", "Internal-hidden", "basics access and IT - hidden"],
)
def test_holding_categories_are_recognised_by_name(name):
    assert mapping.is_hidden_category(name)
    assert mapping.is_hidden_category(None, "Visible name", name)


@pytest.mark.parametrize("name", ["Basic Guides", "Light Microscopy", "Hiddensee excursion", "", None])
def test_ordinary_categories_are_not_hidden(name):
    assert not mapping.is_hidden_category(name)


def test_clipping_marks_what_it_cut():
    assert mapping.clip("short", 10) == ("short", False)
    assert mapping.clip("a long sentence here", 10) == ("a long se…", True)


# ---------------------------------------------------------------- reading the metadata


@pytest.fixture(scope="module")
def site() -> FakeSite:
    return FakeSite()


def meta(site: FakeSite, image_id: int) -> dict:
    return site.documents[f"/media/images/{image_id}"]


def picture(site: FakeSite, image_id: int) -> Image.Image:
    payload, _ = site.files[site.images[image_id]["original"]]
    image = Image.open(BytesIO(payload))
    image.load()
    return image


def marked(source: dict, **state) -> dict:
    """An image record with a clean source, for trying one ``markupState``."""
    return {"srcid": 1, "srcImageInfo": {"width": 800, "height": 600}, "width": 800, "height": 600, "markup": None, "markupState": state, **source}


def node(*records, crop=None) -> dict:
    state = {"annotations": {"type": "NODE_MARKUP", "version": "1", "data": list(records)}}
    if crop is not None:
        state["edits"] = {"type": "NODE_MARKUP", "version": "1", "data": {"crop": crop}}
    return state


def marker_js(*records, width=800, height=600, edits=None) -> dict:
    state = {"annotations": {"type": "MARKER_JS", "version": "2", "data": {"width": width, "height": height, "markers": list(records)}}}
    if edits is not None:
        state["edits"] = edits
    return state


ARROW = {"shape": "arrow", "xStart": 505, "yStart": 440, "xEnd": 185, "yEnd": 438, "color": "red"}
FRAME = {"typeName": "FrameMarker", "left": 10, "top": 20, "width": 100, "height": 50, "strokeColor": "#c1280b", "fillColor": "transparent", "rotationAngle": 0}


@pytest.mark.parametrize(
    "record",
    [
        {"markupState": None, "markup": None},
        {"markupState": {}},
        {"markupState": {"edits": {"type": "NODE_MARKUP", "data": {"crop": {"x": 1, "y": 0, "width": 5, "height": 5}}}}},
        {"markupState": {"annotations": {"type": "NODE_MARKUP", "data": []}}},
        {"markupState": {"annotations": {"type": "MARKER_JS", "data": {"width": 5, "height": 5, "markers": []}}}},
        {"markupState": "nonsense"},
        {"markup": ";crop,40x0,1106x830;"},
    ],
)
def test_an_image_without_markers_needs_no_conversion(record):
    plan = markers.interpret(record)

    assert not plan.has_markers
    assert plan.candidates == [] and plan.fallback_reason is None


def test_the_arrow_payload_recorded_from_the_live_site(site):
    plan = markers.interpret(meta(site, 507))

    assert plan.has_markers and plan.fallback_reason is None
    (candidate,) = plan.candidates
    assert candidate.crop == (0.0, 0.0, 800.0, 600.0)
    assert candidate.shapes == (markers.Shape("arrow", "red", 505.0, 440.0, 185.0, 438.0, head="unknown"),)


def test_a_crop_with_an_offset_yields_both_readings_of_the_coordinates(site):
    plan = markers.interpret(meta(site, 14438))

    source_space, cropped_space = plan.candidates
    assert source_space.crop == cropped_space.crop == (0.0, -40.75, 710.0, 532.5)
    assert source_space.shapes[0] == markers.Shape("rectangle", "red", 3.0, 29.0, 125.0, 207.0)
    assert cropped_space.shapes[0] == markers.Shape("rectangle", "red", 3.0, -11.75, 125.0, 166.25)


def test_the_newer_editor_scales_from_its_canvas_into_the_crop(site):
    (candidate,) = markers.interpret(meta(site, 22069)).candidates

    assert candidate.crop == pytest.approx((107.3225, 26.0028, 695.6694, 521.7520), abs=1e-3)
    frame = candidate.shapes[0]
    assert (frame.kind, frame.color) == ("rectangle", "red")
    assert (frame.x1, frame.y1, frame.x2, frame.y2) == pytest.approx((109.136, 277.081, 799.73, 306.107), abs=0.01)


def test_markers_without_a_clean_source_cannot_be_redrawn():
    plan = markers.interpret({"srcid": None, "markupState": node(ARROW)})

    assert plan.has_markers and plan.candidates == []
    assert "no clean source" in plan.fallback_reason


def test_the_legacy_markup_string_is_read_when_there_is_no_structured_state():
    record = {"srcid": 1, "srcImageInfo": {"width": 800, "height": 600},
              "markup": ";crop,0x0,800x600;arrow,505x440,185x438,red;rectangle,10x20,110x70,lightBlue;circle,400x300,50,green;"}

    (candidate,) = markers.interpret(record).candidates

    assert candidate.shapes == (
        markers.Shape("arrow", "red", 505.0, 440.0, 185.0, 438.0, head="unknown"),
        markers.Shape("rectangle", "light_blue", 10.0, 20.0, 110.0, 70.0),
        markers.Shape("ellipse", "green", 350.0, 250.0, 450.0, 350.0),
    )


def test_legacy_records_that_cannot_be_read_force_the_burned_in_picture():
    for markup in (";gap,1x1,2x2,red;", ";arrow,1x1;", ";circle,axb,5,red;"):
        plan = markers.interpret({"srcid": 1, "srcImageInfo": {"width": 800, "height": 600}, "markup": markup})
        assert plan.has_markers and plan.candidates == [] and "no Reticle equivalent" in plan.fallback_reason
    assert markers.parse_markup_string(";arrow,1x1,2x2;rectangle,1x1,3x3;circle,5x5,2;;") == {
        "annotations": {"type": "NODE_MARKUP", "data": [
            {"shape": "arrow", "xStart": 1.0, "yStart": 1.0, "xEnd": 2.0, "yEnd": 2.0, "color": None},
            {"shape": "rectangle", "x": 1.0, "y": 1.0, "width": 2.0, "height": 2.0, "color": None},
            {"shape": "circle", "x": 5.0, "y": 5.0, "radius": 2.0, "color": None},
        ]}
    }


def test_circles_in_either_layout_become_ellipses():
    by_radius, by_box = markers.interpret(
        marked({}, **node({"shape": "circle", "x": 400, "y": 300, "radius": 50, "color": "orange"}, {"shape": "ellipse", "x": 10, "y": 20, "width": 30, "height": 40, "color": "yellow"}))
    ).candidates[0].shapes

    assert by_radius == markers.Shape("ellipse", "orange", 350.0, 250.0, 450.0, 350.0)
    assert by_box == markers.Shape("ellipse", "yellow", 10.0, 20.0, 40.0, 60.0)


def test_the_newer_editors_ellipse_and_arrow_markers():
    plan = markers.interpret(marked({}, **marker_js(
        {"typeName": "EllipseFrameMarker", "left": 10, "top": 20, "width": 100, "height": 50, "strokeColor": "#16dc81"},
        {"typeName": "ArrowMarker", "x1": 1, "y1": 2, "x2": 30, "y2": 40, "strokeColor": "#15a1d6", "arrowType": "start"},
        {"typeName": "ArrowMarker", "x1": 1, "y1": 2, "x2": 30, "y2": 40, "strokeColor": "nonsense"},
    )))

    ellipse, backwards, forwards = plan.candidates[0].shapes
    assert ellipse == markers.Shape("ellipse", "green", 10.0, 20.0, 110.0, 70.0)
    assert (backwards.kind, backwards.color, backwards.head) == ("arrow", "light_blue", "start")
    assert (forwards.color, forwards.head) == ("red", "end")
    assert plan.notes == ["marker colour 'nonsense' is not a known colour; drawn in red"]


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (marker_js({"typeName": "TextMarker", "left": 1, "top": 1, "width": 5, "height": 5}), "marker type “TextMarker”"),
        (marker_js({**FRAME, "rotationAngle": 12}), "rotated FrameMarker"),
        (marker_js({**FRAME, "visualTransformMatrix": {"a": 2, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}}), "transformed FrameMarker"),
        (marker_js({**FRAME, "containerTransformMatrix": "skewed"}), "transformed FrameMarker"),
        (marker_js({**FRAME, "typeName": "EllipseMarker", "fillColor": "#ff0000"}), "filled EllipseMarker"),
        (marker_js({"typeName": "ArrowMarker", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "arrowType": "both"}), "arrow of type “both”"),
        (marker_js({**FRAME, "left": None}), "not a number"),
        (marker_js({**FRAME, "width": True}), "not a number"),
        (marker_js("FrameMarker"), "not an object"),
        (marker_js(FRAME, width=0), "canvas has no size"),
        (marker_js(FRAME, edits={"type": "CROPRO", "data": {"rotationAngle": 90}}), "rotated or flipped"),
        (marker_js(FRAME, edits={"type": "CROPRO", "data": {"flippedHorizontally": True}}), "rotated or flipped"),
        (marker_js(FRAME, edits={"type": "SOMETHING", "data": {}}), "edit type “SOMETHING”"),
        (marker_js(FRAME, edits={"type": "CROPRO"}), "edit record could not be read"),
        (marker_js(FRAME, edits={"type": "CROPRO", "data": {"cropRect": "all"}}), "crop record is not an object"),
        (node({"shape": "gap", "x": 1, "y": 1}), "marker shape “gap”"),
        (node({"color": "red"}), "marker shape “unknown”"),
        (node("arrow"), "not an object"),
        (node(ARROW, crop={"x": 0, "y": 0, "width": 0, "height": 10}), "crop has no area"),
        (node(*[ARROW] * 51), "51 markers"),
        ({"annotations": {"type": "NODE_MARKUP", "data": [ARROW]}, "edits": {"type": "NODE_MARKUP", "data": {"rotate": 90}}}, "image edit “rotate”"),
        ({"annotations": {"type": "FUTURE_FORMAT", "data": [ARROW]}}, "marker format “FUTURE_FORMAT”"),
    ],
)
def test_what_cannot_be_expressed_falls_back_with_a_reason(state, reason):
    plan = markers.interpret(marked({}, **state))

    assert plan.has_markers and plan.candidates == []
    assert reason in plan.fallback_reason


def test_a_source_without_a_size_cannot_be_used():
    plan = markers.interpret(marked({"srcImageInfo": {"width": 0, "height": 600}}, **node(ARROW)))

    assert "no size" in plan.fallback_reason


def test_the_newer_crop_record_is_scaled_to_the_source_and_may_be_absent():
    uncropped = markers.interpret(marked({}, **marker_js(FRAME, edits={"type": "CROPRO", "data": {"width": 800, "height": 600}})))
    halved = markers.interpret(marked({}, **marker_js(FRAME, width=200, height=150, edits={
        "type": "CROPRO", "data": {"width": 400, "height": 300, "cropRect": {"x": 100, "y": 50, "width": 200, "height": 150}}})))
    no_edits = markers.interpret(marked({}, **node(ARROW, crop=None), edits=None))

    assert uncropped.candidates[0].crop == (0.0, 0.0, 800.0, 600.0)
    assert halved.candidates[0].crop == (200.0, 100.0, 400.0, 300.0)
    assert halved.candidates[0].shapes[0].x1 == pytest.approx(220.0)
    assert no_edits.candidates[0].crop == (0.0, 0.0, 800.0, 600.0)


# ---------------------------------------------------------------- checking against the pixels


def test_an_arrow_is_confirmed_and_its_head_found_at_the_stored_end(site):
    realised = markers.realise(markers.interpret(meta(site, 507)), picture(site, 477), picture(site, 507))

    assert realised is not None and not realised.cropped
    assert realised.image.size == (800, 600)
    (arrow,) = realised.annotations
    assert arrow == {"shape": "arrow", "color": "red", "x": 0.63125, "y": 0.73333, "width": -0.4, "height": -0.00333}
    assert realised.score > 0.9 and realised.notes == []


def test_an_arrow_drawn_the_other_way_round_is_turned_round():
    clean = photo(800, 600, 1)
    burned = clean.copy()
    draw_arrow(burned, (185, 438), (505, 440), MARKER_RED)  # the head is at the stored *start*

    realised = markers.realise(markers.interpret(marked({}, **node(ARROW))), clean, burned)

    (arrow,) = realised.annotations
    assert (arrow["x"], arrow["width"]) == (0.23125, 0.4)


def test_the_arrow_head_can_be_forced_either_way(site):
    plan, clean, burned = markers.interpret(meta(site, 507)), picture(site, 477), picture(site, 507)

    forced_start = markers.realise(plan, clean, burned, arrow_head="start").annotations[0]
    forced_end = markers.realise(plan, clean, burned, arrow_head="end").annotations[0]

    assert (forced_start["x"], forced_start["width"]) == (0.23125, 0.4)
    assert (forced_end["x"], forced_end["width"]) == (0.63125, -0.4)


def test_a_line_with_no_visible_head_keeps_the_stored_direction_and_says_so():
    clean = photo(800, 600, 1)
    burned = clean.copy()
    ImageDraw.Draw(burned).line((505, 440, 185, 438), fill=MARKER_RED, width=8)

    realised = markers.realise(markers.interpret(marked({}, **node(ARROW))), clean, burned)

    assert realised.annotations[0]["width"] == -0.4
    assert realised.notes == ["an arrow's direction could not be read from the picture; its head was put at the stored end point"]


def test_a_padding_crop_keeps_the_whole_source_and_markers_in_source_pixels(site):
    realised = markers.realise(markers.interpret(meta(site, 14438)), picture(site, 14435), picture(site, 14438))

    assert realised.label == "markers in source-image pixels"
    assert not realised.cropped and realised.image.size == (710, 451)
    rectangle, arrow = realised.annotations
    assert rectangle == {"shape": "rectangle", "color": "red", "x": 0.00423, "y": 0.0643, "width": 0.17183, "height": 0.39468}
    assert (arrow["shape"], arrow["color"]) == ("arrow", "green")
    assert arrow["width"] < 0, "the head is on the left, where it was drawn"


def test_markers_stored_in_cropped_pixels_are_recognised_as_such():
    clean = photo(800, 600, 6)
    crop = {"x": 100, "y": 100, "width": 600, "height": 450}
    burned = clean.crop((100, 100, 700, 550))
    ImageDraw.Draw(burned).rectangle((50, 60, 250, 200), outline=MARKER_RED, width=6)
    record = marked({}, **node({"shape": "rectangle", "x": 50, "y": 60, "width": 200, "height": 140, "color": "red"}, crop=crop))

    realised = markers.realise(markers.interpret(record), clean, burned)

    assert realised.label == "markers in cropped-image pixels"
    assert realised.cropped and realised.image.size == (600, 450)
    assert realised.annotations[0] == {"shape": "rectangle", "color": "red", "x": 0.08333, "y": 0.13333, "width": 0.33333, "height": 0.31111}


def test_the_newer_editors_crop_is_applied_to_the_clean_source(site):
    realised = markers.realise(markers.interpret(meta(site, 22069)), picture(site, 22066), picture(site, 22069))

    assert realised.cropped and realised.image.size == (696, 522)
    (frame,) = realised.annotations
    assert frame["shape"] == "rectangle" and frame["color"] == "red"
    assert (frame["x"], frame["y"], frame["width"], frame["height"]) == pytest.approx((0.0026, 0.4812, 0.9927, 0.0556), abs=2e-3)


def test_an_ellipse_is_confirmed_against_its_outline():
    clean = photo(400, 300, 7)
    burned = clean.copy()
    ImageDraw.Draw(burned).ellipse((150, 100, 250, 200), outline=MARKER_GREEN, width=5)
    record = marked({"srcImageInfo": {"width": 400, "height": 300}}, **node({"shape": "circle", "x": 200, "y": 150, "radius": 50, "color": "green"}))

    realised = markers.realise(markers.interpret(record), clean, burned)

    assert realised.annotations == [{"shape": "ellipse", "color": "green", "x": 0.375, "y": 0.33333, "width": 0.25, "height": 0.33333}]


def test_metadata_that_does_not_match_the_picture_is_refused(site):
    assert markers.realise(markers.interpret(meta(site, 950)), picture(site, 949), picture(site, 950)) is None


def test_one_unsupported_marker_among_good_ones_is_enough_to_refuse():
    clean = photo(800, 600, 1)
    burned = clean.copy()
    draw_arrow(burned, (505, 440), (185, 438), MARKER_RED)
    phantom = {"shape": "rectangle", "x": 600, "y": 40, "width": 120, "height": 90, "color": "red"}

    assert markers.realise(markers.interpret(marked({}, **node(ARROW, phantom))), clean, burned) is None


def test_a_marked_picture_with_no_visible_markers_is_refused():
    clean = photo(800, 600, 1)

    assert markers.realise(markers.interpret(marked({}, **node(ARROW))), clean, clean.copy()) is None


def test_without_a_marked_picture_the_first_reading_is_taken_on_trust():
    realised = markers.realise(markers.interpret(marked({}, **node(ARROW))), photo(800, 600, 1), None)

    assert realised.score == 1.0
    assert realised.annotations[0]["width"] == -0.4


def test_markers_outside_the_visible_picture_are_left_out_or_end_the_conversion():
    clean = photo(800, 600, 1)
    outside = {"shape": "rectangle", "x": 900, "y": 700, "width": 50, "height": 50, "color": "red"}
    dot = {"shape": "arrow", "xStart": 10, "yStart": 10, "xEnd": 10, "yEnd": 10, "color": "red"}

    partly = markers.realise(markers.interpret(marked({}, **node(ARROW, outside, dot))), clean, None)
    wholly = markers.realise(markers.interpret(marked({}, **node(outside))), clean, None)

    assert len(partly.annotations) == 1
    assert partly.notes == ["a marker lay outside the visible picture and was left out"] * 2
    assert wholly is None


def test_a_crop_that_misses_the_picture_or_distorts_it_is_refused():
    clean = photo(800, 600, 1)
    beyond = marked({}, **node(ARROW, crop={"x": 5000, "y": 5000, "width": 100, "height": 100}))
    squashed = marked({}, **node(ARROW, crop={"x": 10, "y": 10, "width": 700, "height": 500}))

    assert markers.realise(markers.interpret(beyond), clean, clean.copy()) is None
    assert markers.realise(markers.interpret(squashed), clean, photo(700, 200, 1)) is None


def test_a_very_small_box_is_checked_as_a_filled_patch():
    clean = photo(800, 600, 1)
    burned = clean.copy()
    ImageDraw.Draw(burned).rectangle((400, 300, 412, 310), outline=MARKER_RED, width=4)
    tiny = {"shape": "rectangle", "x": 400, "y": 300, "width": 12, "height": 10, "color": "red"}

    realised = markers.realise(markers.interpret(marked({}, **node(tiny))), clean, burned)

    assert realised is not None and realised.annotations[0]["width"] == 0.015


def test_an_arrow_whose_head_the_payload_names_needs_no_note_when_the_picture_is_undecided():
    clean = photo(800, 600, 1)
    burned = clean.copy()
    ImageDraw.Draw(burned).line((100, 100, 400, 300), fill=MARKER_RED, width=8)
    arrow = {"typeName": "ArrowMarker", "x1": 100, "y1": 100, "x2": 400, "y2": 300, "strokeColor": "#c1280b", "arrowType": "start"}

    realised = markers.realise(markers.interpret(marked({}, **marker_js(arrow))), clean, burned)

    assert realised.notes == []
    assert (realised.annotations[0]["x"], realised.annotations[0]["width"]) == (0.5, -0.375), "the payload said the head is at the start"


def test_when_both_readings_fit_the_first_is_kept():
    """A one-pixel crop offset cannot be told apart by eye either; source pixels are the default."""
    clean = photo(800, 600, 1)
    crop = {"x": 1, "y": 0, "width": 799, "height": 600}
    burned = clean.crop((1, 0, 800, 600))
    ImageDraw.Draw(burned).rectangle((199, 150, 499, 400), outline=MARKER_RED, width=8)
    box = {"shape": "rectangle", "x": 200, "y": 150, "width": 300, "height": 250, "color": "red"}

    realised = markers.realise(markers.interpret(marked({}, **node(box, crop=crop))), clean, burned)

    assert realised.label == "markers in source-image pixels"
