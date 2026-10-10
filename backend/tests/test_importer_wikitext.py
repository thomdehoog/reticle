"""The vendor's wiki syntax, converted to what Reticle displays.

Two targets, tested separately because confusing them is the bug: a page body
is Markdown, while a bullet, an introduction and a conclusion are shown as
plain text and must contain no markup at all.
"""

from __future__ import annotations

import pytest

from app.importer.wikitext import (
    LinkResolver,
    Target,
    escape_markdown,
    html_to_plain,
    normalise_title,
    referenced_image_ids,
    to_markdown,
    to_plain,
)

MEDIA_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.fixture()
def resolver() -> LinkResolver:
    found = LinkResolver(
        guides={15: Target("/g/how-to-get-there", "How to get there")},
        images={900: MEDIA_ID},
        site_hosts=frozenset({"zmb.dozuki.com"}),
    )
    found.add_wiki("CATEGORY", "Basic Guides", Target("/c/confocal-microscopy", "Confocal Microscopy"))
    found.add_wiki("WIKI", "Booking Rules", Target("/w/booking-rules", "Booking Rules"))
    found.add_wiki("INFO", "House Style", Target("/w/house-style", "House Style"))
    return found


def markdown(text: str, resolver: LinkResolver | None = None) -> str:
    return to_markdown(text, resolver).text


def codes(conversion) -> list[str]:
    return [warning.code for warning in conversion.warnings]


# ---------------------------------------------------------------- headings and paragraphs


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("== Abberior STED (Irchel) ==", "## Abberior STED (Irchel)\n"),
        ("=== Deeper ===", "### Deeper\n"),
        ("====== Deepest ======", "###### Deepest\n"),
        ("= Page title =", "# Page title\n"),
        ("==Tight==", "## Tight\n"),
        ("== Lightsheet 🔬 ==", "## Lightsheet 🔬\n"),
    ],
)
def test_headings_keep_their_level(source, expected):
    assert markdown(source) == expected


def test_a_heading_may_contain_inline_markup():
    assert markdown("== The '''main''' room ==") == "## The **main** room\n"


def test_a_line_of_only_equals_signs_is_not_a_heading_or_a_markdown_underline():
    assert markdown("Title\n=====") == "Title\n\\=====\n"


def test_paragraphs_are_separated_by_blank_lines_and_keep_their_line_breaks():
    assert markdown("First line\nsecond line\n\n\nNext paragraph") == "First line\nsecond line\n\nNext paragraph\n"


def test_windows_line_endings_are_normalised():
    assert markdown("One\r\n\r\nTwo\rThree") == "One\n\nTwo\nThree\n"


def test_empty_and_missing_text_convert_to_nothing():
    assert markdown("") == ""
    assert to_markdown(None).text == ""
    assert to_plain(None).text == ""
    assert html_to_plain(None).text == ""


def test_an_explicit_line_break_becomes_a_hard_break():
    assert markdown("Line one[br]Line two") == "Line one\\\nLine two\n"


# ---------------------------------------------------------------- inline styles


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("'''bold'''", "**bold**"),
        ("''italic''", "*italic*"),
        ("'''''both'''''", "***both***"),
        ("***Important***", "**Important**"),
        ("++underlined++", "*underlined*"),
        ("~~struck~~", "~~struck~~"),
        ("x^^2^^", "x^2"),
        ("H,,2,,O", "H2O"),
        ("``config.py``", "`config.py`"),
        ("``a `tick` inside``", "``a `tick` inside``"),
    ],
)
def test_inline_styles(source, expected):
    assert markdown(f"Say {source} here") == f"Say {expected} here\n"


def test_styles_nest():
    assert markdown("'''bold with ''italic'' inside'''") == "**bold with *italic* inside**\n"


def test_raw_text_is_not_formatted():
    assert markdown("[raw]'''not bold''' and [guide|1][/raw]") == "'''not bold''' and \\[guide|1\\]\n"


def test_c_plus_plus_is_not_mistaken_for_underline():
    assert markdown("C++ and C++ again") == "C++ and C++ again\n"


def test_an_empty_style_span_leaves_no_stray_markers():
    assert markdown("'''   '''").strip() == ""


# ---------------------------------------------------------------- escaping


def test_literal_markdown_characters_are_escaped():
    assert markdown("Use *.tif files, a_b_c, <b>tags</b> and `ticks`") == (
        "Use \\*.tif files, a\\_b\\_c, \\<b\\>tags\\</b\\> and \\`ticks\\`\n"
    )


def test_text_that_looks_like_an_html_entity_stays_literal():
    assert markdown("AT&amp;T & more") == "AT\\&amp;T & more\n"
    assert escape_markdown("5 > 3 ~ ok") == "5 \\> 3 \\~ ok"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1. not a list", "1\\. not a list"),
        ("2) nor this", "2\\) nor this"),
        ("- a dash", "\\- a dash"),
        ("+ a plus", "\\+ a plus"),
        ("---", "\\---"),
        ("    indented", "indented"),
        ("#hashtag", "#hashtag"),
    ],
)
def test_prose_cannot_turn_into_markdown_structure(source, expected):
    assert markdown(f"Before\n{source}") == f"Before\n{expected}\n"


# ---------------------------------------------------------------- links


def test_external_links_keep_their_address(resolver):
    assert markdown("[https://svi.nl/NyquistCalculator|SVI Nyquist Calculator]", resolver) == (
        "[SVI Nyquist Calculator](https://svi.nl/NyquistCalculator)\n"
    )


def test_the_keyword_form_of_an_external_link(resolver):
    assert markdown("[link|https://svi.nl/HowtoCiteHuygens|cite Huygens]", resolver) == (
        "[cite Huygens](https://svi.nl/HowtoCiteHuygens)\n"
    )


def test_link_options_are_not_taken_for_the_link_text(resolver):
    assert markdown("[https://example.org|new_window=true]", resolver) == "[https://example.org](https://example.org)\n"
    assert markdown("[https://example.org|new_window=true|Example]", resolver) == "[Example](https://example.org)\n"


def test_a_bare_url_becomes_a_link_without_its_trailing_punctuation(resolver):
    assert markdown("See https://example.org/a_b(1).", resolver) == "See [https://example.org/a\\_b(1)](https://example.org/a_b%281%29).\n"
    assert markdown("(see https://example.org/x)", resolver) == "(see [https://example.org/x](https://example.org/x))\n"


def test_a_link_address_with_spaces_and_brackets_is_encoded(resolver):
    assert markdown("[https://example.org/a b<c>|file]", resolver) == "[file](https://example.org/a%20b%3Cc%3E)\n"


def test_mail_links(resolver):
    assert markdown("[mailto|help@zmb.example]", resolver) == "[help@zmb.example](mailto:help@zmb.example)\n"
    assert markdown("[mailto|help@zmb.example|Write to us]", resolver) == "[Write to us](mailto:help@zmb.example)\n"


def test_a_guide_link_is_rewritten_to_the_reticle_address(resolver):
    assert markdown("[guide|15]", resolver) == "[How to get there](/g/how-to-get-there)\n"
    assert markdown("[guide|15|the way in]", resolver) == "[the way in](/g/how-to-get-there)\n"
    assert markdown("[guide|15|step two|stepid=212]", resolver) == "[step two](/g/how-to-get-there)\n"
    assert markdown("[guide|15|stepid=212]", resolver) == "[How to get there](/g/how-to-get-there)\n"


def test_a_link_to_a_guide_that_was_not_imported_is_kept_as_text_and_reported(resolver):
    conversion = to_markdown("[guide|999|the missing one] and [guide|998]", resolver)

    assert conversion.text == "the missing one and guide 998\n"
    assert codes(conversion) == ["unresolved_link", "unresolved_link"]


def test_wiki_links_resolve_by_namespace_and_title(resolver):
    assert markdown("[[Booking Rules]]", resolver) == "[Booking Rules](/w/booking-rules)\n"
    assert markdown("[[Category:Basic Guides|confocal]]", resolver) == "[confocal](/c/confocal-microscopy)\n"
    assert markdown("[[Basic_Guides]]", resolver) == "[Basic\\_Guides](/c/confocal-microscopy)\n"
    assert markdown("[[info:house style|style]]", resolver) == "[style](/w/house-style)\n"


def test_a_colon_in_a_title_is_not_always_a_namespace(resolver):
    resolver.add_wiki("WIKI", "Note: read first", Target("/w/note-read-first", "Note: read first"))

    assert markdown("[[Note: read first]]", resolver) == "[Note: read first](/w/note-read-first)\n"


def test_an_unresolved_wiki_link_keeps_its_text(resolver):
    conversion = to_markdown("[[A page that was never written|that page]] [[Category:No such category]]", resolver)

    assert conversion.text == "that page Category:No such category\n"
    assert codes(conversion) == ["unresolved_link", "unresolved_link"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://zmb.dozuki.com/Guide/Leica+Stellaris/15", "/g/how-to-get-there"),
        ("https://zmb.dozuki.com/Guide/15", "/g/how-to-get-there"),
        ("https://zmb.dozuki.com/c/Basic_Guides", "/c/confocal-microscopy"),
        ("https://ZMB.dozuki.com/Wiki/Booking%20Rules", "/w/booking-rules"),
    ],
)
def test_links_back_into_the_old_site_are_rewritten(resolver, url, expected):
    conversion = to_markdown(f"[{url}|there]", resolver)

    assert conversion.text == f"[there]({expected})\n"
    assert conversion.warnings == []


@pytest.mark.parametrize(
    "url",
    ["https://zmb.dozuki.com/Guide/Gone/999", "https://zmb.dozuki.com/Guide/login", "https://zmb.dozuki.com/Team/3", "https://zmb.dozuki.com/", "https://zmb.dozuki.com/c"],
)
def test_an_unmappable_link_to_the_old_site_is_kept_and_reported(resolver, url):
    conversion = to_markdown(f"[{url}|there]", resolver)

    assert conversion.text == f"[there]({url})\n"
    assert codes(conversion) == ["vendor_link"]


def test_links_to_other_sites_are_left_alone(resolver):
    assert to_markdown("[https://www.dozuki.com/Guide/x/15|elsewhere]", resolver).text == "[elsewhere](https://www.dozuki.com/Guide/x/15)\n"
    assert not resolver.is_site_url("//evil.example/Guide/1/15")


def test_title_normalisation_folds_url_forms():
    assert normalise_title("Basic_Guides") == normalise_title("basic+guides") == normalise_title(" Basic%20Guides ") == "basic guides"


# ---------------------------------------------------------------- lists


def test_bulleted_and_numbered_lists_nest():
    assert markdown("* Prepare\n** Buffers\n*** Tris\n* Run\n# First\n## Sub\n# Second") == (
        "- Prepare\n    - Buffers\n        - Tris\n- Run\n1. First\n    1. Sub\n1. Second\n"
    )


def test_a_list_item_is_inline_markup_on_one_line():
    assert markdown("* '''Bold''' item[br]continued") == "- **Bold** item continued\n"


def test_starred_bold_at_the_start_of_a_line_is_not_a_list():
    assert markdown("***Warning*** hot surface") == "**Warning** hot surface\n"


# ---------------------------------------------------------------- tables


TABLE = "{table\n|width=50%\n|format=30%l:c:20%r\n|! Marker\n|! Dilution\n|! Note\n|--\n| CD3\n| 1:100\n| a|b\n|--\n| CD8\n| '''1:200'''\n}"


def test_a_table_becomes_a_gfm_table_with_alignment():
    assert markdown(TABLE) == (
        "| Marker | Dilution | Note |\n"
        "| :--- | :---: | ---: |\n"
        "| CD3 | 1:100 | a\\|b |\n"
        "| CD8 | **1:200** |  |\n"
    )


def test_a_table_without_a_header_row_gets_an_empty_one():
    assert markdown("{table\n| a\n| b\n|--\n| c\n| d\n}") == "|  |  |\n| --- | --- |\n| a | b |\n| c | d |\n"


def test_row_header_cells_are_emphasised_and_multi_line_cells_are_joined():
    assert markdown("{table\n|! Name\n| first line\nsecond line\n}") == "|  |  |\n| --- | --- |\n| **Name** | first line second line |\n"


def test_cell_attributes_are_dropped_and_spans_reported():
    conversion = to_markdown('{table\n|! A\n|! B\n|--\n| <<colspan="2">> wide\n|--\n| <<bgcolor="#f00">> red\n| x\n}')

    assert conversion.text == "| A | B |\n| --- | --- |\n| wide |  |\n| red | x |\n"
    assert codes(conversion) == ["table_span"]


def test_an_image_grid_table(resolver):
    assert markdown("{table\n| [image|900|size=small]\n| [image|900|caption=Right]\n}", resolver) == (
        f"|  |  |\n| --- | --- |\n| ![](/api/media/{MEDIA_ID}) | ![Right](/api/media/{MEDIA_ID}) |\n"
    )


def test_an_unterminated_or_empty_table_does_not_swallow_the_page():
    assert markdown("{table\n}\n\nAfter") == "After\n"
    assert markdown("Before\n{table |format=l\n|! Only\n") == "Before\n\n| Only |\n| :--- |\n"


def test_a_code_span_inside_a_table_cell_escapes_its_pipes():
    assert markdown("{table\n|! Cmd\n|--\n| ``a|b``[br]x\n}") == "| Cmd |\n| --- |\n| `a\\|b` x |\n"


# ---------------------------------------------------------------- images, video, code


def test_an_image_points_at_the_imported_media(resolver):
    assert markdown("[image|900]", resolver) == f"![](/api/media/{MEDIA_ID})\n"
    assert markdown("[image|900|size=large|align=center|caption=The panel]", resolver) == (
        f"![The panel](/api/media/{MEDIA_ID})\n\n*The panel*\n"
    )
    assert markdown("[image|900|link=https://example.org]", resolver) == f"[![](/api/media/{MEDIA_ID})](https://example.org)\n"


def test_an_image_that_is_not_in_the_archive_leaves_a_placeholder(resolver):
    conversion = to_markdown("Look: [image|4711|caption=Gone]", resolver)

    assert conversion.text == "Look: \\[missing image 4711\\]\n"
    assert codes(conversion) == ["missing_image"]


def test_image_ids_are_found_for_the_exporter():
    assert referenced_image_ids("[image|12] text [image| 34 |size=small] [IMAGE|56|caption=x] [image|abc]") == [12, 34, 56]
    assert referenced_image_ids(None) == []


def test_an_external_video_becomes_a_link():
    conversion = to_markdown("[video|https://www.youtube.com/embed/abc|size=small]")

    assert conversion.text == "[Video](https://www.youtube.com/embed/abc)\n"
    assert codes(conversion) == ["video_embed"]


def test_a_code_block_is_fenced_and_left_untouched():
    assert markdown("Run:\n[code]\nx = '''1'''\n[guide|15]\n[/code]\nDone") == "Run:\n\n```\nx = '''1'''\n[guide|15]\n```\n\nDone\n"
    assert markdown("[code]a ``` b[/code]") == "````\na ``` b\n````\n"


def test_editor_comments_are_dropped_and_reported():
    conversion = to_markdown("Visible [comment]check\nthis later[/comment]text[comment] [/comment]")

    assert conversion.text == "Visible text\n"
    assert [warning.message for warning in conversion.warnings] == ["Editor-only comment not carried over: “check this later”"]


# ---------------------------------------------------------------- guide lists


def test_the_guide_list_widget_becomes_reticles_fenced_block():
    assert markdown("== Leica Stellaris 5 inverse (USZ) ==\n\n[guidelist|tags=StellUSZ|type=howto]") == (
        "## Leica Stellaris 5 inverse (USZ)\n\n```guidelist\ntags: stellusz\n```\n"
    )


def test_the_documented_tag_spelling_and_a_title_are_accepted():
    assert markdown("[guidelist|tag=LAS X|title=All  LAS X guides]") == "```guidelist\ntags: las-x\nheading: All LAS X guides\n```\n"


def test_several_tags_are_kept_and_flagged_for_checking():
    conversion = to_markdown("[guidelist|tags=SP8, Leica,sp8]")

    assert conversion.text == "```guidelist\ntags: sp8, leica\n```\n"
    assert codes(conversion) == ["guidelist"]


def test_a_guide_list_in_the_middle_of_a_line_is_lifted_out():
    assert markdown("Before [guidelist|tags=A] between [guidelist|tags=B] after") == (
        "Before\n\n```guidelist\ntags: a\n```\n\nbetween\n\n```guidelist\ntags: b\n```\n\nafter\n"
    )


def test_guide_list_options_without_an_equivalent_are_reported():
    conversion = to_markdown("[guidelist|tags=A|item=Stellaris|type=teardown|bogus|limit=]")

    assert conversion.text == "```guidelist\ntags: a\n```\n"
    assert codes(conversion) == ["guidelist"] * 4


def test_a_guide_list_without_a_usable_tag_is_kept_as_text():
    for source in ("[guidelist]", "[guidelist|type=howto]", "[guidelist|tags=!!!]"):
        conversion = to_markdown(source)
        assert conversion.text == escape_markdown(source) + "\n"
        assert "guidelist" in codes(conversion)


def test_a_guide_list_inside_a_table_cell_becomes_a_tag_link():
    conversion = to_markdown("{table\n| [guidelist|tags=SP8|title=SP8 guides]\n| [guidelist|tags=Stell]\n| [guidelist]\n}")

    assert conversion.text == "|  |  |  |\n| --- | --- | --- |\n| [SP8 guides](/t/sp8) | [Guides tagged stell](/t/stell) | \\[guidelist\\] |\n"
    assert codes(conversion).count("guidelist") == 3


# ---------------------------------------------------------------- unknown constructs


def test_unknown_tags_are_preserved_as_text_and_reported():
    conversion = to_markdown("A [quiz|3] and a [wikilist|a,b|namespace=WIKI] and [product|IF145|kit]")

    assert conversion.text == "A \\[quiz|3\\] and a \\[wikilist|a,b|namespace=WIKI\\] and \\[product|IF145|kit\\]\n"
    assert codes(conversion) == ["unknown_markup"] * 3


def test_square_brackets_in_ordinary_prose_are_not_reported():
    conversion = to_markdown("Press [Enter] or choose [x, y] (see ref [12]).")

    assert conversion.text == "Press \\[Enter\\] or choose \\[x, y\\] (see ref \\[12\\]).\n"
    assert conversion.warnings == []


def test_malformed_known_tags_fall_back_to_text():
    conversion = to_markdown("[guide|abc] [image|x] [link] [mailto] [video] [redirect]")

    assert conversion.text == "\\[guide|abc\\] \\[image|x\\] \\[link\\] \\[mailto\\] \\[video\\] \\[redirect\\]\n"
    assert codes(conversion) == ["unknown_markup"] * 2


def test_a_redirect_page_says_where_it_went(resolver):
    resolved = to_markdown("[redirect|Category:Basic Guides]", resolver)
    unresolved = to_markdown("[redirect|Somewhere else]", resolver)

    assert resolved.text == "Redirects to [Confocal Microscopy](/c/confocal-microscopy)\n"
    assert unresolved.text == "Redirects to Somewhere else\n"
    assert codes(resolved) == codes(unresolved) == ["redirect"]


# ---------------------------------------------------------------- plain text


def test_plain_text_drops_every_marker():
    conversion = to_plain("'''Bold''', ''italic'', ***star***, ++under++, ~~gone~~, ``mono``, x^^2^^, H,,2,,O[br]next")

    assert conversion.text == "Bold, italic, star, under, gone, mono, x^2, H2O\nnext"
    assert conversion.warnings == []


def test_plain_text_spells_out_external_links(resolver):
    conversion = to_plain("See [https://svi.nl/x|the calculator], https://example.org and [mailto|help@zmb.example].", resolver)

    assert conversion.text == "See the calculator (https://svi.nl/x), https://example.org and help@zmb.example."
    assert conversion.links_flattened == 3


def test_plain_text_names_internal_targets_instead_of_showing_a_path(resolver):
    assert to_plain("Start with [guide|15] or [[Category:Basic Guides|the confocal page]].", resolver).text == (
        "Start with How to get there or the confocal page."
    )


def test_plain_text_flattens_structure(resolver):
    conversion = to_plain(
        "== Heading ==\n\n* one\n** nested\n# first\n# second\n\n{table\n|! A\n|! B\n|--\n| 1\n| 2\n}\n\n"
        "[code]raw[/code]\n\n[guidelist|tags=SP8|title=SP8]\n\n[image|900|caption=Fig]  [image|900]",
        resolver,
    )

    assert conversion.text == "Heading\n\n• one\n◦ nested\n1. first\n2. second\n\nA | B\n1 | 2\n\nraw\n\nSP8: Guides tagged sp8\n\n[image: Fig] [image]"
    assert codes(conversion) == ["table_flattened", "guidelist", "inline_image", "inline_image"]


def test_plain_numbering_restarts_after_bullets():
    assert to_plain("# a\n# b\n* x\n# c").text == "1. a\n2. b\n• x\n1. c"
    assert to_plain("# a\n## inner\n# b").text == "1. a\n1. inner\n2. b"


def test_plain_text_collapses_whitespace():
    assert to_plain("  A   lot\tof    space  \n\n\n\n\nEnd ").text == "A lot of space\n\nEnd"


# ---------------------------------------------------------------- rendered HTML


def test_rendered_html_is_flattened_to_what_the_reader_saw(resolver):
    conversion = html_to_plain(
        '<p>Go <strong>now</strong> to <a href="https://svi.nl/x" rel="nofollow">SVI &quot;calc&quot;</a><br/>'
        'and <a href="https://zmb.dozuki.com/Guide/Foo/15">this guide</a>, or <a href="#top">up</a>.</p>'
        "<ul><li>first</li><li>second</li></ul>",
        resolver,
    )

    assert conversion.text == 'Go now to SVI "calc" (https://svi.nl/x)\nand this guide, or up.\n\n• first\n• second'
    assert conversion.links_flattened == 2
    assert conversion.warnings == []


def test_a_rendered_relative_link_into_the_old_site_resolves(resolver):
    assert html_to_plain('<a href="/Info/House+Style">the style guide</a>', resolver).text == "the style guide"
    assert html_to_plain('<a href="/Info/House+Style"></a>', resolver).text == "House Style"


def test_rendered_html_entities_and_plain_fragments():
    assert html_to_plain("Mind the &quot;laser&quot; &amp; 5 &lt; 6").text == 'Mind the "laser" & 5 < 6'


def test_a_rendered_link_whose_text_is_its_address_is_not_repeated(resolver):
    assert html_to_plain('<a href="https://example.org">https://example.org</a> and <a href="https://example.org/b"></a>', resolver).text == (
        "https://example.org and https://example.org/b"
    )


def test_a_rendered_link_to_an_unmapped_page_of_the_old_site_is_reported(resolver):
    conversion = html_to_plain('<a href="https://zmb.dozuki.com/Team/3">the team</a>', resolver)

    assert conversion.text == "the team (https://zmb.dozuki.com/Team/3)"
    assert codes(conversion) == ["vendor_link"]


def test_rendered_html_drops_scripts_styles_and_reports_media(resolver):
    conversion = html_to_plain(
        '<div>Text<script>alert(1)</script><style>p{}</style><svg/><svg><path d=""/></svg>'
        '<img src="x.png" alt="A diagram"><img src="y.png"/><iframe src="z"></iframe></div>'
        "<table><tr><td>a</td><th>b</th></tr><tr><td>c</td></tr></table>",
        resolver,
    )

    assert conversion.text == "Text[A diagram]\n\na b\nc"
    assert codes(conversion) == ["inline_image"] * 3
