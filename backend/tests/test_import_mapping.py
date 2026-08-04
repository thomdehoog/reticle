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
    map_bullet,
    map_difficulty,
    map_guide,
    map_page,
    map_step_media,
    map_tags,
    map_time_required,
    parse_markup,
    resolve_guide_embeds,
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
        # What the site writes where an author gave no estimate. An absent value
        # spelled in words, not an unreadable one — reporting it as unmapped
        # stopped the run over a guide with nothing to lose.
        ("No estimate", (None, None)),
        ("no estimate", (None, None)),
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


def test_a_bullet_written_in_wiki_syntax_arrives_as_rich_text():
    """`text_raw` is the vendor's wiki syntax, not HTML.

    Stripping tags left it exactly as it was, so a reader met
    ``'''widefield'''`` and ``[https://svi.nl|SVI]`` in the middle of a
    sentence. Reticle renders a bullet as rich text, which is what those
    constructs mean.
    """
    bullet, problems = map_bullet(
        {"text_raw": "Use '''widefield''' and see [https://svi.nl|the manual]."}, "s1"
    )

    assert problems == []
    assert bullet is not None
    assert bullet.text == "Use **widefield** and see [the manual](https://svi.nl)."


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("[https://svi.nl/HomePage|SVI Huygens]", "[SVI Huygens](https://svi.nl/HomePage)"),
        ("[link|https://svi.nl/cite|cite Huygens]", "[cite Huygens](https://svi.nl/cite)"),
        ("[link|https://svi.nl/cite]", "[https://svi.nl/cite](https://svi.nl/cite)"),
        ("[mailto|it@zmb.uzh.ch]", "[it@zmb.uzh.ch](mailto:it@zmb.uzh.ch)"),
        ("[mailto|it@zmb.uzh.ch|the IT desk]", "[the IT desk](mailto:it@zmb.uzh.ch)"),
    ],
)
def test_the_link_spellings_the_corpus_actually_writes(source, expected):
    """Counted across the sample: fifteen ``[link|..]``, nine ``[url|label]``,
    three ``[mailto|..]`` — and no ``[[target|label]]`` anywhere, which is the
    only form the converter used to know."""
    assert wiki_to_markdown(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "[guide|26|new_window=true]",
        "[guidelist|tags=ASTED|type=howto]",
        "[image|13484|align=center]",
    ],
)
def test_a_construct_that_is_not_a_link_is_left_for_the_code_that_understands_it(source):
    """These share a link's shape and are not links.

    A guide embed becomes a Reticle block once the import knows what id 26 has
    turned into, and a guide list becomes a tag-filtered listing. Matching them
    here on "anything before a pipe" would have turned both into dead links.
    """
    assert wiki_to_markdown(source) == source


def test_an_empty_bullet_is_dropped_without_complaint():
    bullet, problems = map_bullet({"text_raw": "   ", "bullet": "black"}, "s1")
    assert bullet is None
    assert problems == []


# --- annotations ----------------------------------------------------------


"""Every string in this section is copied from a live image record.

The mapping used to accept a list of dictionaries in any of several shapes,
because nobody had seen the real thing. The real thing is a delimited string on
a document the importer was not fetching, so the flexible version had nothing to
be flexible about and every annotation in the corpus was dropped. These are the
shapes that actually occur.
"""


def test_a_rectangle_is_two_points_and_becomes_a_corner_and_a_size():
    """Read as a corner and a size, 36 of the sample's rectangles leave the picture."""
    mapped, problems = parse_markup(";rectangle,828x1164,586x430,red;", 4032, 3024, "image 12628")

    assert problems == []
    assert len(mapped) == 1
    shape = mapped[0]
    assert shape.shape == "rectangle"
    assert shape.color == "red"
    # Normalised to the top-left corner, so the drag direction stops mattering.
    assert shape.x == pytest.approx(586 / 4032)
    assert shape.y == pytest.approx(430 / 3024)
    assert shape.width == pytest.approx(242 / 4032)
    assert shape.height == pytest.approx(734 / 3024)


def test_an_arrow_keeps_the_direction_it_was_drawn_in():
    """A signed vector, because which end has the head is the whole point.

    This one is drawn right to left, which is the case that a rule demanding
    positive extents once made permanently unsaveable.
    """
    mapped, problems = parse_markup(
        ";arrow,2544.9731115392738x2220.324324324324,932.2163895943447x2208.5092567642882,red;",
        4032,
        3024,
        "image 507",
    )

    assert problems == []
    assert mapped[0].shape == "arrow"
    assert mapped[0].width < 0
    assert mapped[0].x == pytest.approx(2544.9731115392738 / 4032)


def test_a_circle_is_a_centre_and_a_radius():
    """The one entry whose second field is a single number rather than a pair."""
    mapped, problems = parse_markup(";circle,368x263,251,red;", 4032, 3024, "image 1")

    assert problems == []
    assert mapped[0].shape == "ellipse"
    assert mapped[0].x == pytest.approx((368 - 251) / 4032)
    assert mapped[0].width == pytest.approx(502 / 4032)


def test_several_shapes_in_one_string_all_arrive():
    mapped, problems = parse_markup(
        ";rectangle,828x1164,586x430,red;arrow,2272.5x1096.5,2558.6x1552.9,red;",
        4032,
        3024,
        "image 12628",
    )

    assert problems == []
    assert [shape.shape for shape in mapped] == ["rectangle", "arrow"]


def test_the_crop_window_is_not_an_annotation():
    """It is the frame the photograph was cropped to, which the stored image
    already reflects — drawn, it would ring the whole picture."""
    mapped, problems = parse_markup(";crop,-1176x0,5376x4032;", 4032, 3024, "image 1")

    assert (mapped, problems) == ([], [])


def test_a_deleted_set_of_shapes_leaves_null_behind_and_is_not_a_problem():
    assert parse_markup(";null;", 4032, 3024, "image 1") == ([], [])
    assert parse_markup(None, 4032, 3024, "image 1") == ([], [])


def test_the_camel_case_colour_the_site_writes_is_recognised():
    """The site writes `lightBlue`; Reticle calls it `light_blue`."""
    mapped, problems = parse_markup(";circle,764x1200,220,lightBlue;", 4032, 3024, "image 1")

    assert problems == []
    assert mapped[0].color == "light_blue"


def test_a_shape_off_the_picture_is_reported_rather_than_clamped():
    """About a fifth of the sample's shapes land outside their image.

    Why is not yet known, and neither answer is safe to assume: clamping moves
    the shape off whatever it points at, and passing it through unchanged puts a
    value outside the range the schema accepts, which refuses every later save
    of the guide holding it. So it is reported and the run does not reconcile.
    """
    mapped, problems = parse_markup(";arrow,100x100,99999x99999,red;", 4032, 3024, "image 1")

    assert mapped == []
    assert problems and problems[0].kind == "markup_off_the_image"


def test_an_unknown_shape_is_reported_rather_than_approximated():
    mapped, problems = parse_markup(";freehand,1x1,2x2,red;", 4032, 3024, "image 1")

    assert mapped == []
    assert problems and problems[0].kind == "markup_shape"


def test_an_unknown_colour_is_reported():
    mapped, problems = parse_markup(";rectangle,10x10,20x20,chartreuse;", 4032, 3024, "image 1")

    assert mapped == []
    assert problems and problems[0].kind == "markup_colour"


def test_an_image_with_no_usable_size_cannot_be_normalised_and_says_so():
    """Fractions need a denominator; a shape divided by nothing is not a shape."""
    mapped, problems = parse_markup(";rectangle,10x10,20x20,red;", 0, 3024, "image 1")

    assert mapped == []
    assert problems and problems[0].kind == "markup_image_size"


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
    # Empty from the payload alone: a guide document carries no `tags` key, and
    # the groups it belongs to are a separate request the run makes. Asserted
    # rather than omitted, because reading them from here is exactly the mistake
    # that reported "0 tags" against a corpus of eighty-nine.
    assert mapped.tags == []
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
    # Annotations are not among them: they live on the image document, not on
    # the guide payload, and the run attaches them once it has fetched it.
    assert step.images[0].annotations == []


def test_a_guides_front_matter_is_translated_out_of_wiki_syntax():
    """The introduction and the conclusion are wiki source like a page's body.

    They were run through the HTML stripper, which leaves wiki syntax alone, so
    a guide's first paragraph reached the reader full of markers. Both are
    translated the same way a wiki page's body already was.
    """
    payload = _guide_payload()
    payload["introduction_raw"] = "Uses '''Huygens''' — see [https://svi.nl|the site]."
    payload["conclusion_raw"] = "Cite it with [https://svi.nl/cite|these words]."

    mapped, problems = map_guide(payload)

    assert problems == []
    assert mapped.introduction == "Uses **Huygens** — see [the site](https://svi.nl)."
    assert mapped.conclusion == "Cite it with [these words](https://svi.nl/cite)."


def test_a_private_guide_is_marked_private_so_it_does_not_arrive_published():
    payload = _guide_payload()
    payload["public"] = False
    mapped, _ = map_guide(payload)
    assert mapped.is_public is False


def test_a_featured_guide_arrives_as_a_quick_link():
    """The site puts it in front of people, so Reticle does too.

    This field was dropped until Reticle had somewhere to put it, and a guide
    the facility had deliberately promoted would have arrived indistinguishable
    from the eighty others in its category.
    """
    payload = _guide_payload()
    payload["featured_guide"] = True

    mapped, problems = map_guide(payload)

    assert mapped.is_quick_link is True
    assert problems == []


def test_a_guide_the_site_does_not_feature_is_not_a_quick_link():
    mapped, problems = map_guide(_guide_payload())

    assert mapped.is_quick_link is False
    assert problems == []


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


def test_a_category_carries_its_own_description_across():
    """The words in the banner across the top of a section.

    Every one of ZMB's fifteen sections publishes this, and it is the only
    sentence about a section anybody wrote.
    """
    mapped, _ = map_page(
        {
            "wikiid": 77,
            "namespace": "CATEGORY",
            "title": "Widefield Microscopy",
            "description": "Fluorescence widefield systems are well suited for imaging.",
        }
    )
    assert mapped.summary == "Fluorescence widefield systems are well suited for imaging."


def test_a_page_takes_the_largest_rendition_of_its_own_picture():
    """The same rule a step image follows, for the same reason.

    The vendor offers the picture at eight sizes and names the display-sized
    one first; importing that would carry the photograph across at the size it
    happened to be shown at rather than the size it was taken at.
    """
    mapped, _ = map_page(
        {
            "wikiid": 77,
            "namespace": "CATEGORY",
            "title": "Widefield Microscopy",
            "image": {
                "id": 4165,
                "thumbnail": "https://example.test/small.jpg",
                "standard": "https://example.test/standard.jpg",
                "original": "https://example.test/original.jpg",
            },
        }
    )
    assert mapped.image is not None
    assert mapped.image.url == "https://example.test/original.jpg"
    assert mapped.image.source_id == "4165"


def test_a_page_with_no_picture_is_ordinary_and_silent():
    """Most articles have none, and that is not a defect to report."""
    mapped, problems = map_page({"wikiid": 78, "namespace": "WIKI", "title": "Immersion oil"})
    assert mapped.image is None
    assert problems == []


def test_a_picture_the_mapping_cannot_read_costs_the_page_nothing():
    """An image object with no usable URL in it leaves the page importable.

    The words are the page; losing the photograph at the top should not take
    the procedure underneath with it.
    """
    mapped, problems = map_page(
        {
            "wikiid": 79,
            "namespace": "CATEGORY",
            "title": "CryoEM",
            "description": "Vitrification and screening.",
            "image": {"id": 12, "thumbnail": "/relative/not/absolute.jpg"},
        }
    )
    assert mapped.image is None
    assert mapped.summary == "Vitrification and screening."
    assert problems == []


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


def test_a_guide_embed_survives_the_wiki_conversion_untouched():
    """The conversion is pure and cannot know what id 1234 became.

    It leaves the vendor's marker exactly as written so that
    :func:`resolve_guide_embeds` — which is handed the id-to-slug mapping the
    import builds — can translate it once that mapping exists.
    """
    source = "Intro\n[guide|1234|Align the laser]\nmore"

    assert wiki_to_markdown(source) == source


# --- guide embeds ---------------------------------------------------------


def test_an_embed_naming_an_imported_guide_becomes_a_guide_block():
    resolution = resolve_guide_embeds("[guide|1234|Align the laser]", {"1234": "align-the-laser"})

    assert resolution.body == "```guide\nalign-the-laser\n```"
    assert resolution.resolved == ["1234"]
    assert resolution.unresolved == []


def test_an_embed_naming_a_guide_the_import_does_not_have_is_left_as_written():
    """It must not vanish and must not become a block pointing at nothing.

    A block naming a slug nothing answers to renders as nothing at all to a
    reader, and a plain title reads as finished prose — either way nobody would
    ever find it. The vendor's marker still carries the id, so a reviewer can
    look the guide up on the source site.
    """
    resolution = resolve_guide_embeds("[guide|9999|Deleted procedure]", {"1234": "align"})

    assert resolution.body == "[guide|9999|Deleted procedure]"
    assert resolution.resolved == []
    assert resolution.unresolved == ["[guide|9999|Deleted procedure]"]


def test_several_embeds_on_one_page_are_each_resolved_on_their_own():
    """ZMB's "access your data" page is nothing but these, one per platform."""
    body = "Windows:\n\n[guide|1|Windows]\n\nMac:\n\n[guide|2|Mac]\n\nLinux:\n\n[guide|3|Linux]"

    resolution = resolve_guide_embeds(body, {"1": "data-windows", "3": "data-linux"})

    assert resolution.body == (
        "Windows:\n\n```guide\ndata-windows\n```\n\nMac:\n\n[guide|2|Mac]\n\n"
        "Linux:\n\n```guide\ndata-linux\n```"
    )
    assert resolution.resolved == ["1", "3"]
    assert resolution.unresolved == ["[guide|2|Mac]"]


def test_an_embed_inside_a_sentence_leaves_the_prose_on_either_side_alone():
    """A fenced block has to start its own line, so it is lifted out of the
    sentence rather than written into the middle of it."""
    resolution = resolve_guide_embeds(
        "Before booking, read [guide|1234|Align the laser] and bring your sample.",
        {"1234": "align-the-laser"},
    )

    assert resolution.body == (
        "Before booking, read\n\n```guide\nalign-the-laser\n```\n\nand bring your sample."
    )


def test_an_embed_with_no_title_after_the_id_is_resolved_too():
    resolution = resolve_guide_embeds("[guide|1234]", {"1234": "align-the-laser"})

    assert resolution.body == "```guide\nalign-the-laser\n```"


def test_a_page_with_no_embeds_is_returned_unchanged():
    resolution = resolve_guide_embeds("## Heading\n\nOrdinary prose.", {"1234": "align"})

    assert resolution.body == "## Heading\n\nOrdinary prose."
    assert resolution.resolved == []
    assert resolution.unresolved == []
