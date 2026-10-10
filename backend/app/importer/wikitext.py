"""The vendor's wiki syntax, converted to what Reticle can display.

Reticle shows text in two ways, and they must not be confused:

* a wiki **page body** is Markdown (CommonMark plus GitHub tables and
  strikethrough), rendered to elements with raw HTML ignored;
* a **bullet**, a guide **introduction** and a **conclusion** are plain text,
  put on the page character for character.

So there are two targets. :func:`to_markdown` is for page bodies.
:func:`to_plain` and :func:`html_to_plain` are for the plain fields: emitting
``**bold**`` into a bullet would show the asterisks to every reader, so
emphasis is dropped there and a link becomes its text followed by its address.

The rule for anything unrecognised is that it is never silently lost. An
unknown ``[tag|...]`` is kept as readable text and reported, so a person can
find it afterwards and decide what it should have been.

The syntax handled here is the one documented on the vendor's help pages and
observed in the facility's own content; ``docs/dozuki-api-notes.md`` lists
which parts were seen live and which are taken from the documentation.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from ..slugs import tag_slug

# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class Warning:
    """Something a person should look at after the import."""

    code: str
    message: str


@dataclass
class Conversion:
    text: str
    warnings: list[Warning] = field(default_factory=list)
    links_flattened: int = 0
    """Links that lost their target's clickability by landing in a plain-text field."""


# ---------------------------------------------------------------- link resolution


@dataclass(frozen=True)
class Target:
    """Where an internal link now points, and what the thing is called."""

    url: str
    title: str


def normalise_title(title: str) -> str:
    """A wiki title as it compares: URL forms and letter case folded away.

    The vendor writes the same page as ``Basic Guides``, ``Basic_Guides`` and
    ``Basic+Guides`` depending on where the link was built.
    """
    cleaned = unquote(title).replace("_", " ").replace("+", " ")
    return " ".join(cleaned.split()).casefold()


NAMESPACE_ALIASES = {
    "category": "CATEGORY",
    "c": "CATEGORY",
    "device": "CATEGORY",
    "topic": "CATEGORY",
    "wiki": "WIKI",
    "info": "INFO",
    "item": "ITEM",
}

UNPREFIXED_ORDER = ("WIKI", "CATEGORY", "ITEM", "INFO")

SITE_PATH_NAMESPACES = {"c": "CATEGORY", "wiki": "WIKI", "info": "INFO", "item": "ITEM", "topic": "CATEGORY", "device": "CATEGORY"}


@dataclass
class LinkResolver:
    """What the converter knows about the rest of the import.

    Filled in by the loader before any text is converted: every guide and page
    is given its Reticle slug first, so a link to something that is imported
    later in the same run still resolves.
    """

    guides: dict[int, Target] = field(default_factory=dict)
    wikis: dict[tuple[str, str], Target] = field(default_factory=dict)
    images: dict[int, str] = field(default_factory=dict)
    site_hosts: frozenset[str] = frozenset()

    def add_wiki(self, namespace: str, title: str, target: Target) -> None:
        self.wikis[(namespace.upper(), normalise_title(title))] = target

    def wiki(self, namespace: str | None, title: str) -> Target | None:
        key = normalise_title(title)
        if namespace is not None:
            return self.wikis.get((namespace.upper(), key))
        for candidate in UNPREFIXED_ORDER:
            found = self.wikis.get((candidate, key))
            if found is not None:
                return found
        return None

    def wiki_link(self, reference: str) -> Target | None:
        """Resolve the inside of ``[[...]]``, with or without a namespace prefix."""
        prefix, separator, rest = reference.partition(":")
        if separator and prefix.strip().lower() in NAMESPACE_ALIASES:
            found = self.wiki(NAMESPACE_ALIASES[prefix.strip().lower()], rest.strip())
            if found is not None:
                return found
        return self.wiki(None, reference.strip())

    def is_site_url(self, url: str) -> bool:
        if url.startswith("/") and not url.startswith("//"):
            return True
        host = (urlsplit(url).hostname or "").lower()
        return bool(host) and host in self.site_hosts

    def site_url(self, url: str) -> Target | None:
        """Resolve a link that points back at the vendor site itself.

        ``/Guide/<title>/<id>`` carries the guide id as its last numeric
        segment; ``/c/<Title>``, ``/Wiki/<Title>`` and ``/Info/<Title>`` carry a
        wiki title.
        """
        segments = [segment for segment in urlsplit(url).path.split("/") if segment]
        if not segments:
            return None
        head = segments[0].lower()
        if head == "guide":
            for segment in reversed(segments[1:]):
                if segment.isdigit():
                    return self.guides.get(int(segment))
            return None
        namespace = SITE_PATH_NAMESPACES.get(head)
        if namespace is not None and len(segments) >= 2:
            return self.wiki(namespace, "/".join(segments[1:]))
        return None


# ---------------------------------------------------------------- syntax tree


@dataclass
class Text:
    value: str


@dataclass
class Styled:
    kind: str
    children: list


@dataclass
class Code:
    value: str


@dataclass
class Link:
    url: str
    children: list
    internal: bool = False
    title: str = ""


@dataclass
class Image:
    image_id: int
    caption: str = ""
    link: str = ""


@dataclass
class Break:
    pass


@dataclass
class Heading:
    level: int
    inline: list


@dataclass
class Paragraph:
    inline: list


@dataclass
class ListItem:
    depth: int
    ordered: bool
    inline: list


@dataclass
class ItemList:
    items: list[ListItem]


@dataclass
class Cell:
    header: bool
    inline: list


@dataclass
class Table:
    alignments: list[str]
    rows: list[list[Cell]]


@dataclass
class CodeBlock:
    value: str


@dataclass
class GuideList:
    tags: list[str]
    heading: str = ""


# ---------------------------------------------------------------- parsing

COMMENT = re.compile(r"\[comment\](.*?)\[/comment\]", re.DOTALL | re.IGNORECASE)
CODE_BLOCK = re.compile(r"\[code\](.*?)\[/code\]", re.DOTALL | re.IGNORECASE)
HEADING = re.compile(r"^(={1,6})\s*(.*?)\s*\1\s*$")
LIST_ITEM = re.compile(r"^([*#]+)\s+(.*)$")
GUIDELIST_TAG = re.compile(r"\[guidelist(\|[^\[\]]*)?\]", re.IGNORECASE)
IMAGE_TAG = re.compile(r"\[image\|\s*(\d+)\s*(?:\|[^\[\]]*)?\]", re.IGNORECASE)
TABLE_OPTION = re.compile(r"^\|\s*(width|format|class|style|border|align|caption)\s*=\s*(.*)$", re.IGNORECASE)
CELL_ATTRIBUTES = re.compile(r"^\s*<<(.*?)>>\s*")
FORMAT_COLUMN = re.compile(r"^\s*(?:\d+(?:\.\d+)?%?)?\s*([lcr])?[mbt]?\s*$", re.IGNORECASE)

INLINE = re.compile(
    r"""
      \[raw\](?P<raw>.*?)\[/raw\]
    | ``(?P<mono>.+?)``
    | \[\[(?P<wikilink>[^\[\]\n]+)\]\]
    | \[(?P<tag>[^\[\]\n]+)\]
    | '''''(?P<bolditalic>.+?)'''''
    | '''(?P<bold>.+?)'''
    | ''(?P<italic>.+?)''
    | \*\*\*(?=\S)(?P<starbold>.+?)(?<=\S)\*\*\*
    | \+\+(?=\S)(?P<underline>.+?)(?<=\S)\+\+
    | ~~(?=\S)(?P<strike>.+?)(?<=\S)~~
    | \^\^(?P<sup>[^\^\n]+?)\^\^
    | ,,(?=\S)(?P<sub>[^,\n]+?),,
    | (?P<url>https?://[^\s<>\[\]|]+)
    """,
    re.VERBOSE | re.IGNORECASE,
)

STYLE_GROUPS = {
    "bolditalic": "bolditalic",
    "bold": "bold",
    "italic": "italic",
    "starbold": "bold",
    "underline": "underline",
    "strike": "strike",
    "sup": "sup",
    "sub": "sub",
}

TRAILING_PUNCTUATION = ".,;:!?'\""

LINK_OPTIONS = ("new_window=", "nofollow=", "target=")


def referenced_image_ids(text: str | None) -> list[int]:
    """Every ``[image|<id>]`` in a piece of wiki text, in order of appearance.

    The exporter uses this to know which files a page needs before anything is
    converted.
    """
    if not text:
        return []
    return [int(match.group(1)) for match in IMAGE_TAG.finditer(text)]


class _Parser:
    def __init__(self, resolver: LinkResolver) -> None:
        self.resolver = resolver
        self.warnings: list[Warning] = []

    def warn(self, code: str, message: str) -> None:
        self.warnings.append(Warning(code, message))

    # ------------------------------------------------------------ blocks

    def parse(self, text: str) -> list:
        source = text.replace("\r\n", "\n").replace("\r", "\n")

        def drop_comment(match: re.Match) -> str:
            note = " ".join(match.group(1).split())
            if note:
                self.warn("comment_dropped", f"Editor-only comment not carried over: “{note}”")
            return ""

        source = COMMENT.sub(drop_comment, source)

        blocks: list = []
        position = 0
        for match in CODE_BLOCK.finditer(source):
            blocks.extend(self._blocks(source[position : match.start()]))
            blocks.append(CodeBlock(match.group(1).strip("\n")))
            position = match.end()
        blocks.extend(self._blocks(source[position:]))
        return blocks

    def _blocks(self, source: str) -> list:
        blocks: list = []
        paragraph: list[str] = []
        lines = source.split("\n")
        index = 0

        def flush() -> None:
            if paragraph:
                blocks.append(Paragraph(self.inline("\n".join(paragraph))))
                paragraph.clear()

        while index < len(lines):
            line = lines[index]
            stripped = line.strip()

            if not stripped:
                flush()
                index += 1
                continue

            if stripped.lower().startswith("{table"):
                flush()
                body: list[str] = []
                rest = stripped[len("{table") :].strip()
                if rest:
                    body.append(rest)
                index += 1
                while index < len(lines) and lines[index].strip() != "}":
                    body.append(lines[index])
                    index += 1
                index += 1
                blocks.append(self._table(body))
                continue

            heading = HEADING.match(stripped)
            if heading and heading.group(2).strip("= "):
                flush()
                blocks.append(Heading(len(heading.group(1)), self.inline(heading.group(2))))
                index += 1
                continue

            if LIST_ITEM.match(stripped):
                flush()
                items: list[ListItem] = []
                while index < len(lines):
                    item = LIST_ITEM.match(lines[index].strip())
                    if item is None:
                        break
                    marker = item.group(1)
                    items.append(ListItem(len(marker) - 1, marker[-1] == "#", self.inline(item.group(2))))
                    index += 1
                blocks.append(ItemList(items))
                continue

            position = 0
            for match in GUIDELIST_TAG.finditer(line):
                before = line[position : match.start()].strip()
                if before:
                    paragraph.append(before)
                flush()
                blocks.append(self._guidelist(match.group(1) or "", match.group(0)))
                position = match.end()
            after = line[position:].strip()
            if after:
                paragraph.append(after)
            index += 1

        flush()
        return blocks

    def _guidelist(self, options: str, original: str) -> GuideList | Paragraph:
        """``[guidelist|tags=StellUSZ|type=howto]``; ``tag=`` is accepted too."""
        tags: list[str] = []
        heading = ""
        for part in options.split("|"):
            key, separator, value = part.partition("=")
            key = key.strip().lower()
            value = value.strip()
            if not separator or not key:
                if part.strip():
                    self.warn("guidelist", f"Unrecognised guide-list option “{part.strip()}” in {original}")
                continue
            if key in {"tag", "tags"}:
                tags.extend(piece.strip() for piece in value.split(",") if piece.strip())
            elif key == "title":
                heading = value
            elif key == "type":
                if value.lower().replace("-", "") not in {"howto", ""}:
                    self.warn("guidelist", f"Guide-list type filter “{value}” has no equivalent and was dropped in {original}")
            else:
                self.warn("guidelist", f"Guide-list option “{key}={value}” has no equivalent and was dropped in {original}")

        slugs: list[str] = []
        for tag in tags:
            slug = tag_slug(tag)
            if slug and slug not in slugs:
                slugs.append(slug)
        if not slugs:
            self.warn("guidelist", f"Guide list without a usable tag kept as text: {original}")
            return Paragraph([Text(original)])
        if len(slugs) > 1:
            self.warn(
                "guidelist",
                f"Guide list asks for several tags ({', '.join(slugs)}). Reticle lists guides carrying ALL of them; "
                "check the page shows what the original did.",
            )
        return GuideList(slugs, heading)

    def _table(self, lines: list[str]) -> Table:
        alignments: list[str] = []
        rows: list[list[Cell]] = [[]]
        raw_cells: list[tuple[list[Cell], bool, list[str]]] = []
        started = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|--"):
                rows.append([])
                started = True
                continue
            option = TABLE_OPTION.match(stripped)
            if option and not started:
                if option.group(1).lower() == "format":
                    alignments = self._alignments(option.group(2))
                continue
            if stripped.startswith("|"):
                started = True
                header = stripped.startswith("|!")
                content = stripped[2:] if header else stripped[1:]
                raw_cells.append((rows[-1], header, [content.strip()]))
                continue
            if raw_cells and stripped:
                raw_cells[-1][2].append(stripped)

        for row, header, parts in raw_cells:
            content = " ".join(part for part in parts if part)
            attributes = CELL_ATTRIBUTES.match(content)
            if attributes:
                content = content[attributes.end() :]
                if re.search(r"(col|row)span", attributes.group(1), re.IGNORECASE):
                    self.warn(
                        "table_span",
                        f"A table cell spanning several columns or rows was flattened to one cell: “{content[:60]}”",
                    )
            row.append(Cell(header, self.inline(content, in_cell=True)))

        return Table(alignments, [row for row in rows if row])

    @staticmethod
    def _alignments(spec: str) -> list[str]:
        alignments: list[str] = []
        for column in spec.split(":"):
            match = FORMAT_COLUMN.match(column)
            letter = (match.group(1) or "").lower() if match else ""
            alignments.append({"l": "left", "c": "center", "r": "right"}.get(letter, ""))
        return alignments

    # ------------------------------------------------------------ inline

    def inline(self, text: str, in_cell: bool = False) -> list:
        nodes: list = []
        position = 0
        for match in INLINE.finditer(text):
            if match.start() > position:
                nodes.append(Text(text[position : match.start()]))
            position = match.end()
            kind = match.lastgroup
            value = match.group(kind)

            if kind == "raw":
                nodes.append(Text(value))
            elif kind == "mono":
                nodes.append(Code(value))
            elif kind == "wikilink":
                nodes.append(self._wikilink(value))
            elif kind == "tag":
                nodes.extend(self._tag(value, match.group(0), in_cell))
            elif kind == "url":
                url = value
                trailing = ""
                while url and (url[-1] in TRAILING_PUNCTUATION or (url[-1] == ")" and url.count("(") < url.count(")"))):
                    trailing = url[-1] + trailing
                    url = url[:-1]
                nodes.append(self.link(url, []))
                if trailing:
                    nodes.append(Text(trailing))
            else:
                nodes.append(Styled(STYLE_GROUPS[kind], self.inline(value, in_cell)))
        if position < len(text):
            nodes.append(Text(text[position:]))
        return nodes

    def link(self, url: str, children: list) -> Link:
        """A link by address: rewritten when it points back into the vendor site."""
        if self.resolver.is_site_url(url):
            target = self.resolver.site_url(url)
            if target is not None:
                return Link(target.url, children, internal=True, title=target.title)
            self.warn(
                "vendor_link",
                f"Link to the old site could not be mapped to imported content and will stop working: {url}",
            )
        return Link(url, children)

    def _wikilink(self, value: str) -> Link | Text:
        reference, separator, label = value.partition("|")
        target = self.resolver.wiki_link(reference)
        shown = label.strip() if separator and label.strip() else reference.strip()
        if target is None:
            self.warn("unresolved_link", f"Internal link to “{reference.strip()}” matches no imported page; kept as text.")
            return Text(shown)
        return Link(target.url, self.inline(shown), internal=True, title=target.title)

    def _tag(self, value: str, original: str, in_cell: bool) -> list:
        parts = [part.strip() for part in value.split("|")]
        head = parts[0]
        keyword = head.lower()

        if keyword == "br" and len(parts) == 1:
            return [Break()]

        if re.match(r"^https?://", head, re.IGNORECASE):
            return [self.link(head, self._label(parts[1:]))]

        if keyword == "link" and len(parts) >= 2:
            return [self.link(parts[1], self._label(parts[2:]))]

        if keyword == "mailto" and len(parts) >= 2:
            return [Link(f"mailto:{parts[1]}", self._label(parts[2:]) or [Text(parts[1])])]

        if keyword == "guide" and len(parts) >= 2 and parts[1].isdigit():
            target = self.resolver.guides.get(int(parts[1]))
            label = [part for part in parts[2:] if not part.lower().startswith("stepid=")]
            if target is None:
                self.warn("unresolved_link", f"Link to guide {parts[1]} matches no imported guide; kept as text.")
                return [Text(label[0] if label else f"guide {parts[1]}")]
            children = self.inline(label[0]) if label else [Text(target.title)]
            return [Link(target.url, children, internal=True, title=target.title)]

        if keyword == "image" and len(parts) >= 2 and parts[1].isdigit():
            options = dict(part.partition("=")[::2] for part in parts[2:] if "=" in part)
            return [Image(int(parts[1]), options.get("caption", "").strip(), options.get("link", "").strip())]

        if keyword == "video" and len(parts) >= 2:
            self.warn("video_embed", f"Embedded video became a plain link: {parts[1]}")
            return [Link(parts[1], [Text("Video")])]

        if keyword == "guidelist":
            block = self._guidelist(value[len(head) :], original)
            if isinstance(block, GuideList):
                self.warn(
                    "guidelist",
                    "A guide list inside a table cell or list item cannot be embedded there; replaced by a tag link: "
                    + original,
                )
                return [Link(f"/t/{block.tags[0]}", [Text(block.heading or f"Guides tagged {', '.join(block.tags)}")], internal=True)]
            return block.inline

        if keyword == "redirect" and len(parts) >= 2:
            target = self.resolver.wiki_link(parts[1])
            self.warn("redirect", f"This page was a redirect to “{parts[1]}” on the old site.")
            if target is None:
                return [Text(f"Redirects to {parts[1]}")]
            return [Text("Redirects to "), Link(target.url, [Text(target.title or parts[1])], internal=True, title=target.title)]

        if "|" in value and re.match(r"^[a-z][a-z0-9_]*$", keyword):
            self.warn("unknown_markup", f"Unrecognised markup kept as text: {original}")
        return [Text(original)]

    def _label(self, parts: list[str]) -> list:
        for part in parts:
            if part and not part.lower().startswith(LINK_OPTIONS):
                return self.inline(part)
        return []


# ---------------------------------------------------------------- Markdown

ESCAPED = re.compile(r"([\\`*_\[\]<>~])")
ENTITY = re.compile(r"&(?=#?[A-Za-z0-9]+;)")
BLOCK_START = re.compile(r"^(#{1,6}(?=\s|$)|[+-](?=\s))")
ORDERED_START = re.compile(r"^(\d+)[.)](?=\s)")
RULE_LINE = re.compile(r"^([-=])(\s*\1)*\s*$")


def escape_markdown(text: str) -> str:
    """Make literal text survive a Markdown renderer as the same characters."""
    return ENTITY.sub(r"\\&", ESCAPED.sub(r"\\\1", text))


def _escape_line_start(line: str) -> str:
    """Stop a line of prose from being read as a heading, a list or a rule.

    Leading whitespace goes as well: four spaces would make it a code block.
    """
    line = line.lstrip()
    if RULE_LINE.match(line) or BLOCK_START.match(line):
        return "\\" + line
    ordered = ORDERED_START.match(line)
    if ordered:
        return f"{ordered.group(1)}\\{line[ordered.end(1):]}"
    return line


def _escape_line_starts(text: str) -> str:
    return "\n".join(_escape_line_start(line) for line in text.split("\n"))


def _link_destination(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")


def _fence(value: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    return "`" * max(3, longest + 1)


class _Markdown:
    def __init__(self, resolver: LinkResolver, warnings: list[Warning]) -> None:
        self.resolver = resolver
        self.warnings = warnings

    def inline(self, nodes: list, in_cell: bool = False) -> str:
        out: list[str] = []
        for node in nodes:
            if isinstance(node, Text):
                text = escape_markdown(node.value)
                if in_cell:
                    text = text.replace("|", "\\|").replace("\n", " ")
                out.append(text)
            elif isinstance(node, Styled):
                inner = self.inline(node.children, in_cell)
                if not inner.strip():
                    out.append(inner)
                elif node.kind == "bold":
                    out.append(f"**{inner}**")
                elif node.kind in {"italic", "underline"}:
                    out.append(f"*{inner}*")
                elif node.kind == "bolditalic":
                    out.append(f"***{inner}***")
                elif node.kind == "strike":
                    out.append(f"~~{inner}~~")
                elif node.kind == "sup":
                    out.append(f"^{inner}")
                else:
                    out.append(inner)
            elif isinstance(node, Code):
                value = node.value.replace("\n", " ")
                if in_cell:
                    value = value.replace("|", "\\|")
                fence = "`" * (max((len(run) for run in re.findall(r"`+", value)), default=0) + 1)
                padding = " " if value.startswith("`") or value.endswith("`") else ""
                out.append(f"{fence}{padding}{value}{padding}{fence}")
            elif isinstance(node, Link):
                label = self.inline(node.children, in_cell) or escape_markdown(node.url.removeprefix("mailto:"))
                out.append(f"[{label}]({_link_destination(node.url)})")
            elif isinstance(node, Image):
                out.append(self.image(node))
            else:
                out.append(" " if in_cell else "\\\n")
        return "".join(out)

    def image(self, node: Image) -> str:
        media_id = self.resolver.images.get(node.image_id)
        if media_id is None:
            self.warnings.append(
                Warning("missing_image", f"Image {node.image_id} is not in the archive; a placeholder was left in the text.")
            )
            return escape_markdown(f"[missing image {node.image_id}]")
        alt = escape_markdown(node.caption).replace("\n", " ")
        rendered = f"![{alt}](/api/media/{media_id})"
        if node.link:
            rendered = f"[{rendered}]({_link_destination(node.link)})"
        return rendered

    def block(self, block: object) -> str:
        if isinstance(block, Heading):
            text = self.inline(block.inline).replace("\\\n", " ").replace("\n", " ").strip()
            return f"{'#' * block.level} {text}"
        if isinstance(block, Paragraph):
            text = _escape_line_starts(self.inline(block.inline)).strip()
            only = block.inline[0] if len(block.inline) == 1 else None
            if isinstance(only, Image) and only.caption and only.image_id in self.resolver.images:
                text += f"\n\n*{escape_markdown(only.caption)}*"
            return text
        if isinstance(block, ItemList):
            lines = []
            for item in block.items:
                marker = "1." if item.ordered else "-"
                text = self.inline(item.inline).replace("\\\n", " ").replace("\n", " ").strip()
                lines.append(f"{'    ' * item.depth}{marker} {text}")
            return "\n".join(lines)
        if isinstance(block, Table):
            return self.table(block)
        if isinstance(block, CodeBlock):
            fence = _fence(block.value)
            return f"{fence}\n{block.value}\n{fence}"
        assert isinstance(block, GuideList)
        lines = ["```guidelist", f"tags: {', '.join(block.tags)}"]
        if block.heading:
            lines.append(f"heading: {' '.join(block.heading.split())}")
        lines.append("```")
        return "\n".join(lines)

    def table(self, table: Table) -> str:
        if not table.rows:
            return ""
        width = max(len(row) for row in table.rows)
        rows = [list(row) + [Cell(False, [])] * (width - len(row)) for row in table.rows]

        def render(row: list[Cell], header_row: bool) -> str:
            cells = []
            for cell in row:
                text = self.inline(cell.inline, in_cell=True).strip()
                if cell.header and not header_row and text:
                    text = f"**{text}**"
                cells.append(text)
            return "| " + " | ".join(cells) + " |"

        has_header = all(cell.header for cell in table.rows[0])
        header = render(rows[0], True) if has_header else "| " + " | ".join([""] * width) + " |"
        body = rows[1:] if has_header else rows

        rule = []
        for column in range(width):
            alignment = table.alignments[column] if column < len(table.alignments) else ""
            rule.append({"left": ":---", "center": ":---:", "right": "---:"}.get(alignment, "---"))
        lines = [header, "| " + " | ".join(rule) + " |"]
        lines.extend(render(row, False) for row in body)
        return "\n".join(lines)


def to_markdown(text: str | None, resolver: LinkResolver | None = None) -> Conversion:
    """Vendor wiki text to the Markdown a Reticle page body is written in."""
    resolver = resolver or LinkResolver()
    parser = _Parser(resolver)
    blocks = parser.parse(text or "")
    renderer = _Markdown(resolver, parser.warnings)
    rendered = [renderer.block(block) for block in blocks]
    body = "\n\n".join(part for part in rendered if part.strip())
    return Conversion(body + ("\n" if body else ""), parser.warnings)


# ---------------------------------------------------------------- plain text


PLAIN_BULLETS = ("•", "◦", "▪")
"""Leading whitespace does not survive in a plain field, so depth is shown by the marker."""


class _Plain:
    def __init__(self, resolver: LinkResolver, warnings: list[Warning]) -> None:
        self.resolver = resolver
        self.warnings = warnings
        self.links_flattened = 0

    def link(self, url: str, label: str, internal: bool, title: str) -> str:
        """A link with nowhere to be clickable: its text, and its address if that helps."""
        self.links_flattened += 1
        label = " ".join(label.split())
        if internal:
            return label or title or url
        address = url.removeprefix("mailto:")
        if not label or label == address or label == url:
            return address
        return f"{label} ({address})"

    def inline(self, nodes: list) -> str:
        out: list[str] = []
        for node in nodes:
            if isinstance(node, Text):
                out.append(node.value)
            elif isinstance(node, Styled):
                out.append(("^" if node.kind == "sup" else "") + self.inline(node.children))
            elif isinstance(node, Code):
                out.append(node.value)
            elif isinstance(node, Link):
                out.append(self.link(node.url, self.inline(node.children), node.internal, node.title))
            elif isinstance(node, Image):
                self.warnings.append(
                    Warning(
                        "inline_image",
                        f"Image {node.image_id} sat inside text that Reticle shows as plain text; it was left out.",
                    )
                )
                out.append(f"[image: {node.caption}]" if node.caption else "[image]")
            else:
                out.append("\n")
        return "".join(out)

    def block(self, block: object) -> str:
        if isinstance(block, (Heading, Paragraph)):
            return self.inline(block.inline)
        if isinstance(block, ItemList):
            lines = []
            counters: dict[int, int] = {}
            for item in block.items:
                for deeper in [depth for depth in counters if depth > item.depth]:
                    del counters[deeper]
                if item.ordered:
                    counters[item.depth] = counters.get(item.depth, 0) + 1
                    marker = f"{counters[item.depth]}."
                else:
                    counters.pop(item.depth, None)
                    marker = PLAIN_BULLETS[min(item.depth, len(PLAIN_BULLETS) - 1)]
                lines.append(f"{marker} {self.inline(item.inline).strip()}")
            return "\n".join(lines)
        if isinstance(block, Table):
            self.warnings.append(
                Warning("table_flattened", "A table sat inside text that Reticle shows as plain text; its rows became lines.")
            )
            return "\n".join(" | ".join(self.inline(cell.inline).strip() for cell in row) for row in block.rows)
        if isinstance(block, CodeBlock):
            return block.value
        assert isinstance(block, GuideList)
        self.warnings.append(
            Warning("guidelist", "A guide list sat inside text that Reticle shows as plain text; it became a sentence.")
        )
        return f"{block.heading + ': ' if block.heading else ''}Guides tagged {', '.join(block.tags)}"


def tidy_plain(text: str) -> str:
    """Trim each line, collapse runs of spaces, and allow at most one blank line."""
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def to_plain(text: str | None, resolver: LinkResolver | None = None) -> Conversion:
    """Vendor wiki text to plain text, for the fields Reticle shows verbatim."""
    resolver = resolver or LinkResolver()
    parser = _Parser(resolver)
    blocks = parser.parse(text or "")
    renderer = _Plain(resolver, parser.warnings)
    rendered = [renderer.block(block) for block in blocks]
    body = tidy_plain("\n\n".join(part for part in rendered if part.strip()))
    return Conversion(body, parser.warnings, renderer.links_flattened)


# ---------------------------------------------------------------- rendered HTML

BLOCK_ELEMENTS = frozenset({"p", "div", "ul", "ol", "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6"})
LINE_ELEMENTS = frozenset({"li", "tr"})
SILENT_ELEMENTS = frozenset({"script", "style", "svg"})
MEDIA_ELEMENTS = frozenset({"img", "iframe", "video", "audio", "object", "embed"})


class _HtmlToPlain(HTMLParser):
    """Flatten the vendor's own rendering of a line to the text a reader saw.

    Every payload carries the rendered HTML next to the wiki source. For a
    plain-text target that rendering is the safer input: the vendor has already
    resolved whatever syntax its editors produce, including forms that are on no
    help page, so all that is left to do is take the tags off.
    """

    def __init__(self, renderer: _Plain, parser: _Parser) -> None:
        super().__init__(convert_charrefs=True)
        self.renderer = renderer
        self.parser = parser
        self.out: list[str] = []
        self.silent = 0
        self.anchor: tuple[str, int] | None = None

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag in SILENT_ELEMENTS:
            self.silent += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag in BLOCK_ELEMENTS:
            self.out.append("\n\n")
        elif tag in LINE_ELEMENTS:
            self.out.append("\n• " if tag == "li" else "\n")
        elif tag in {"td", "th"}:
            self.out.append(" ")
        elif tag == "a":
            self.anchor = (dict(attributes).get("href") or "", len(self.out))
        elif tag in MEDIA_ELEMENTS:
            alt = (dict(attributes).get("alt") or "").strip()
            self.parser.warn(
                "inline_image", f"A <{tag}> element sat inside text that Reticle shows as plain text; it was left out."
            )
            self.out.append(f"[{alt}]" if alt else "")

    def handle_startendtag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attributes)
        if tag in SILENT_ELEMENTS:
            self.silent -= 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SILENT_ELEMENTS:
            self.silent = max(self.silent - 1, 0)
        elif tag in BLOCK_ELEMENTS:
            self.out.append("\n\n")
        elif tag == "a" and self.anchor is not None:
            href, start = self.anchor
            self.anchor = None
            label = "".join(self.out[start:])
            del self.out[start:]
            if not href or href.startswith("#"):
                self.out.append(label)
                return
            link = self.parser.link(href, [])
            self.out.append(self.renderer.link(link.url, label, link.internal, link.title))

    def handle_data(self, data: str) -> None:
        if not self.silent:
            self.out.append(data)


def html_to_plain(html: str | None, resolver: LinkResolver | None = None) -> Conversion:
    """The vendor's rendered HTML fragment to plain text."""
    resolver = resolver or LinkResolver()
    parser = _Parser(resolver)
    renderer = _Plain(resolver, parser.warnings)
    flattener = _HtmlToPlain(renderer, parser)
    flattener.feed(html or "")
    flattener.close()
    return Conversion(tidy_plain("".join(flattener.out)), parser.warnings, renderer.links_flattened)
