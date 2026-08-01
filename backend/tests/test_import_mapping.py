"""Guarding the migration against silent loss.

The whole corpus crosses this mapping once, and it crosses it on a day when the
subscription is about to lapse. Every failure this file guards against is the
same shape: the run finishes, the report says nothing, and something is missing
that nobody notices until somebody follows a procedure and the step they needed
is not there.

The cases that matter most are the ones nothing else would catch — a bullet
colour that arrives under a spelling the table does not hold, a time range that
parses to a single number, an annotation whose coordinates are percentages
rather than fractions, and vendor HTML surviving into a body it should never
reach.

Fixtures here are hand-built rather than recorded, because the site cannot be
reached from the build environment. They are therefore *permissive about shape*:
each one covers a form the payload plausibly takes, which is why several fields
are accepted under more than one name.
"""

from __future__ import annotations

import pytest

from app.importer.mapping import (
    guide_list_block,
    map_annotations,
    map_bullet,
    map_difficulty,
    map_guide,
    map_page,
    map_step_media,
    map_tags,
    map_time_required,
    slugify_tag,
    strip_markup,
    wiki_to_markdown,
)


# --- text -----------------------------------------------------------------


def test_markup_is_reduced_to_text_and_never_carried_across():
    """Paragraphs stay paragraphs: run together, an intro becomes one long line."""
    source = '<p class="intro">Switch the <b>key</b> to <i>on</i>.</p><p>Wait.</p>'
    assert strip_markup(source) == "Switch the key to on.\n\nWait."


def test_script_and_style_are_removed_with_their_contents():
    """Dropping only the tags would print a wall of JavaScript into a procedure."""
    source = "<style>.a{color:red}</style><p>Real text</p><script>alert(1)</script>"
    result = strip_markup(source)
    assert result == "Real text"
    assert "color" not in result and "alert" not in result


def test_entities_are_decoded():
    assert strip_markup("<p>10&nbsp;&mu;m &amp; 5&#37;</p>").replace("\xa0", " ") == "10 μm & 5%"


def test_empty_markup_is_empty_rather_than_none():
    assert strip_markup(None) == ""
    assert strip_markup("") == ""


# --- tags -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Stellaris 8", "stellaris-8"),
        ("  LAS X  ", "las-x"),
        ("Live-cell", "live-cell"),
        ("Präparation", "praparation"),
        ("Messgröße", "messgrosse"),
        ("Ångström", "angstrom"),
    ],
)
def test_tag_slugs_follow_the_same_rule_the_browser_uses(value, expected):
    assert slugify_tag(value) == expected


def test_tags_accept_a_list_of_strings_or_objects_and_collapse_duplicates():
    slugs, problems = map_tags(["Confocal", {"title": "Confocal"}, {"name": "Stellaris"}], "g1")
    assert slugs == ["confocal", "stellaris"]
    assert problems == []


def test_tags_accept_a_comma_separated_line():
    slugs, problems = map_tags("confocal, stellaris; startup", "g1")
    assert slugs == ["confocal", "stellaris", "startup"]
    assert problems == []


def test_an_unreadable_tag_is_reported_rather_than_dropped():
    slugs, problems = map_tags([{"unexpected": "shape"}], "g1")
    assert slugs == []
    assert problems and problems[0].kind == "tag"


# --- time -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30 minutes", (30, None)),
        ("30 - 90 minutes", (30, 90)),
        ("30 – 90 minutes", (30, 90)),
        ("1 hour", (60, None)),
        ("1 hour 30 minutes", (90, None)),
        ("1 - 2 hours", (60, 120)),
        ("30 minutes to 2 hours", (30, 120)),
        ("00:30", (30, None)),
        ("00:30 - 01:30", (30, 90)),
        ("2 days", (2880, None)),
        (1800, (30, None)),
        ({"min": 1800, "max": 5400}, (30, 90)),
        (None, (None, None)),
        ("", (None, None)),
    ],
)
def test_time_estimates_survive_as_the_range_they_were_written_as(raw, expected):
    low, high, problems = map_time_required(raw, "g1")
    assert (low, high) == expected
    assert problems == []


def test_an_unreadable_time_is_reported_not_guessed():
    low, high, problems = map_time_required("about a fortnight", "g1")
    assert (low, high) == (None, None)
    assert problems and problems[0].kind == "time_required"


# --- difficulty -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Very easy", "very_easy"),
        ("easy", "easy"),
        ("Moderate", "moderate"),
        ("Difficult", "difficult"),
        ("Very difficult", "very_difficult"),
        (None, "moderate"),
    ],
)
def test_difficulty_maps_to_the_five_levels(raw, expected):
    value, problems = map_difficulty(raw, "g1")
    assert value == expected
    assert problems == []


def test_an_unknown_difficulty_is_reported():
    """Quietly calling it moderate would misrepresent a procedure graded dangerous."""
    value, problems = map_difficulty("Extremely dangerous", "g1")
    assert value == "moderate"
    assert problems and problems[0].kind == "difficulty"


# --- bullets --------------------------------------------------------------


@pytest.mark.parametrize(
    "colour",
    ["black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet"],
)
def test_every_one_of_the_eight_colours_survives(colour):
    bullet, problems = map_bullet({"text_raw": "Turn the key.", "bullet": colour}, "s1")
    assert bullet is not None
    assert bullet.color == colour
    assert bullet.icon is None
    assert problems == []


@pytest.mark.parametrize(
    ("raw", "icon"),
    [("icon_note", "note"), ("icon_caution", "caution"), ("icon_reminder", "reminder")],
)
def test_flagged_bullets_keep_their_flag_and_gain_the_colour_it_renders_as(raw, icon):
    bullet, problems = map_bullet({"text_raw": "Careful.", "bullet": raw}, "s1")
    assert bullet is not None
    assert bullet.icon == icon
    assert bullet.color in {"blue", "orange", "violet"}
    assert problems == []


def test_alternative_colour_spellings_land_on_the_same_colour():
    for spelling in ("lightblue", "light_blue"):
        bullet, _ = map_bullet({"text_raw": "x", "bullet": spelling}, "s1")
        assert bullet is not None and bullet.color == "light_blue"


def test_an_unknown_bullet_colour_stops_the_bullet_rather_than_defaulting_it():
    """A colour silently turned black loses the link to its annotation."""
    bullet, problems = map_bullet({"text_raw": "x", "bullet": "teal"}, "s1")
    assert bullet is None
    assert problems and problems[0].kind == "bullet" and problems[0].value == "teal"


def test_indent_levels_beyond_two_are_clamped_and_reported():
    bullet, problems = map_bullet({"text_raw": "x", "bullet": "black", "level": 5}, "s1")
    assert bullet is not None and bullet.level == 2
    assert problems and problems[0].kind == "level"


def test_bullet_html_is_reduced_to_text():
    bullet, _ = map_bullet({"text_raw": "<b>Never</b> touch the lens."}, "s1")
    assert bullet is not None and bullet.text == "Never touch the lens."


def test_an_empty_bullet_is_dropped_without_complaint():
    bullet, problems = map_bullet({"text_raw": "   ", "bullet": "black"}, "s1")
    assert bullet is None
    assert problems == []


# --- annotations ----------------------------------------------------------


def test_annotations_survive_with_their_shape_and_colour():
    raw = [
        {"shape": "rectangle", "color": "red", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        {"shape": "circle", "color": "green", "x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1},
        {"shape": "arrow", "color": "blue", "x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5},
    ]
    mapped, problems = map_annotations(raw, "s1")
    assert [item.shape for item in mapped] == ["rectangle", "ellipse", "arrow"]
    assert [item.color for item in mapped] == ["red", "green", "blue"]
    assert problems == []


def test_percentage_coordinates_become_fractions():
    """Stored as 0..100 on one side and 0..1 on ours; a raw copy would be off-screen."""
    mapped, problems = map_annotations(
        [{"shape": "rect", "color": "red", "x": 10, "y": 20, "width": 30, "height": 40}], "s1"
    )
    assert problems == []
    assert (mapped[0].x, mapped[0].y, mapped[0].width, mapped[0].height) == (0.1, 0.2, 0.3, 0.4)


def test_two_corner_geometry_becomes_a_corner_and_a_size():
    mapped, problems = map_annotations(
        [{"shape": "rectangle", "color": "red", "x1": 0.1, "y1": 0.1, "x2": 0.6, "y2": 0.5}], "s1"
    )
    assert problems == []
    assert mapped[0].width == pytest.approx(0.5)
    assert mapped[0].height == pytest.approx(0.4)


def test_annotations_nested_under_a_shapes_key_are_found():
    mapped, _ = map_annotations(
        {"shapes": [{"shape": "arrow", "color": "red", "x": 0, "y": 0, "width": 1, "height": 1}]},
        "s1",
    )
    assert len(mapped) == 1


def test_an_unknown_shape_is_reported_rather_than_approximated():
    mapped, problems = map_annotations([{"shape": "freehand", "color": "red"}], "s1")
    assert mapped == []
    assert problems and problems[0].kind == "markup_shape"


def test_a_shape_with_no_usable_geometry_is_reported():
    mapped, problems = map_annotations([{"shape": "rectangle", "color": "red"}], "s1")
    assert mapped == []
    assert problems and problems[0].kind == "markup_geometry"


def test_no_markup_is_not_a_problem():
    assert map_annotations(None, "s1") == ([], [])
    assert map_annotations([], "s1") == ([], [])


# --- media ----------------------------------------------------------------


def test_the_largest_rendition_is_the_one_taken():
    """A screenshot of an acquisition dialog is useless at thumbnail size."""
    images, video, problems = map_step_media(
        [
            {
                "type": "image",
                "data": {
                    "id": 42,
                    "thumbnail": "https://example.test/t.jpg",
                    "standard": "https://example.test/s.jpg",
                    "original": "https://example.test/o.jpg",
                },
            }
        ],
        "s1",
    )
    assert problems == []
    assert video is None
    assert images[0].url == "https://example.test/o.jpg"
    assert images[0].source_id == "42"


def test_a_step_video_lands_in_the_video_slot_with_its_poster():
    images, video, problems = map_step_media(
        [
            {
                "type": "video",
                "data": {
                    "id": 7,
                    "encodings": [{"url": "https://example.test/clip.mp4"}],
                    "image": {"original": "https://example.test/poster.jpg"},
                },
            }
        ],
        "s1",
    )
    assert problems == []
    assert images == []
    assert video is not None
    assert video.url == "https://example.test/clip.mp4"
    assert video.poster_url == "https://example.test/poster.jpg"


def test_an_externally_hosted_embed_is_reported_because_it_cannot_be_self_hosted():
    images, video, problems = map_step_media([{"type": "embed", "data": {}}], "s1")
    assert (images, video) == ([], None)
    assert problems and problems[0].kind == "media_type"


def test_an_image_with_no_usable_url_is_reported():
    _, _, problems = map_step_media([{"type": "image", "data": {"id": 1}}], "s1")
    assert problems and problems[0].kind == "image_url"


# --- whole documents ------------------------------------------------------


def _guide_payload() -> dict:
    return {
        "guideid": 1234,
        "title": "Starting a Session on the Confocal",
        "summary": "<p>From booking to shutdown.</p>",
        "category": "Light Microscopy",
        "tags": ["Confocal", "Stellaris"],
        "difficulty": "Easy",
        "time_required": "30 - 90 minutes",
        "introduction_raw": "Assumes you hold a valid booking.",
        "conclusion_raw": "Report faults the same day.",
        "public": True,
        "steps": [
            {
                "stepid": 1,
                "orderby": 1,
                "title": "Power up in order",
                "lines": [
                    {"text_raw": "Switch on the mains strip.", "bullet": "black", "level": 0},
                    {"text_raw": "Never skip the self-test.", "bullet": "icon_caution", "level": 0},
                    {"text_raw": "The 405 needs ten minutes.", "bullet": "light_blue", "level": 1},
                ],
                "media": [
                    {
                        "type": "image",
                        "data": {
                            "id": 9001,
                            "original": "https://example.test/one.jpg",
                            "markup": [
                                {
                                    "shape": "rectangle",
                                    "color": "red",
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.2,
                                    "height": 0.2,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_a_whole_guide_maps_with_nothing_left_unrecognised():
    mapped, problems = map_guide(_guide_payload())
    assert problems == []
    assert mapped.source_id == "1234"
    assert mapped.title == "Starting a Session on the Confocal"
    assert mapped.summary == "From booking to shutdown."
    assert mapped.category_name == "Light Microscopy"
    assert mapped.tags == ["confocal", "stellaris"]
    assert mapped.difficulty == "easy"
    assert (mapped.time_min_minutes, mapped.time_max_minutes) == (30, 90)
    assert mapped.is_public is True
    assert len(mapped.steps) == 1

    step = mapped.steps[0]
    assert step.title == "Power up in order"
    assert [bullet.color for bullet in step.bullets] == ["black", "orange", "light_blue"]
    assert [bullet.icon for bullet in step.bullets] == [None, "caution", None]
    assert [bullet.level for bullet in step.bullets] == [0, 0, 1]
    assert len(step.images) == 1
    assert len(step.images[0].annotations) == 1
    assert step.images[0].annotations[0].color == "red"


def test_a_private_guide_is_marked_private_so_it_does_not_arrive_published():
    payload = _guide_payload()
    payload["public"] = False
    mapped, _ = map_guide(payload)
    assert mapped.is_public is False


def test_a_guide_with_no_title_still_gets_one():
    mapped, _ = map_guide({"guideid": 5, "steps": []})
    assert mapped.title == "Untitled 5"


def test_a_category_wiki_becomes_a_landing_page():
    mapped, problems = map_page(
        {
            "wikiid": 77,
            "namespace": "CATEGORY",
            "title": "Light Microscopy",
            "contents_raw": "== Before your first session ==\n\n'''Bring your sample.'''",
        }
    )
    assert problems == []
    assert mapped.is_landing is True
    assert mapped.category_name == "Light Microscopy"
    assert "## Before your first session" in mapped.body
    assert "**Bring your sample.**" in mapped.body


def test_an_ordinary_wiki_is_not_a_landing_page():
    mapped, _ = map_page({"wikiid": 78, "namespace": "WIKI", "title": "Immersion oil"})
    assert mapped.is_landing is False
    assert mapped.category_name is None


# --- wiki syntax ----------------------------------------------------------


def test_wiki_headings_bold_italic_and_lists_become_markdown():
    body = wiki_to_markdown("== Heading ==\n'''bold''' and ''italic''\n* one\n* two")
    assert "## Heading" in body
    assert "**bold**" in body
    assert "*italic*" in body
    assert "- one" in body and "- two" in body


def test_internal_links_are_rewritten_to_reticle_routes():
    assert "[Confocal](/w/confocal)" in wiki_to_markdown("[[Confocal]]")
    assert "[the page](/w/confocal)" in wiki_to_markdown("[[Confocal|the page]]")
    assert "[Cat](/w/light-microscopy)" in wiki_to_markdown("[[Category:Light Microscopy|Cat]]")


def test_external_links_stay_external():
    assert "[docs](https://zmb.uzh.ch)" in wiki_to_markdown("[[https://zmb.uzh.ch|docs]]")


def test_rendered_html_in_a_wiki_body_is_reduced_rather_than_carried():
    body = wiki_to_markdown('<div class="x"><p>Hello</p><script>alert(1)</script></div>')
    assert body == "Hello"


def test_the_guide_list_block_is_the_embed_the_reader_renders():
    assert guide_list_block(["confocal", "startup"], "Start-up") == (
        "```guidelist\ntags: confocal, startup\nheading: Start-up\n```"
    )


# --- discovering what nobody wrote down -----------------------------------


def test_a_field_the_importer_does_not_read_is_reported_as_a_question():
    """This is the only mechanical way to notice a feature the site has.

    A field nobody accounted for is simply not looked at, every count still
    balances, and the capability behind it is discovered years later by somebody
    wondering where it went.
    """
    payload = _guide_payload()
    payload["quiz"] = {"questions": []}
    _, problems = map_guide(payload)

    assert [item.value for item in problems if item.kind == "unknown_field"] == ["quiz"]


def test_fields_that_are_deliberately_not_carried_across_are_not_reported():
    """Otherwise the list is noise and stops being read."""
    payload = _guide_payload()
    payload.update({"url": "https://example.test/Guide/1234", "revisionid": 9, "view_count": 6745})
    _, problems = map_guide(payload)

    assert [item for item in problems if item.kind == "unknown_field"] == []


def test_an_unknown_field_on_a_step_or_a_bullet_is_reported_too():
    payload = _guide_payload()
    payload["steps"][0]["gadget"] = True
    payload["steps"][0]["lines"][0]["annotation_ref"] = 12
    _, problems = map_guide(payload)

    reported = {item.value for item in problems if item.kind == "unknown_field"}
    assert reported == {"gadget", "annotation_ref"}
