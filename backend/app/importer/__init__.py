"""The one-off content importer: a vendor site's own content, into Reticle.

Two phases, deliberately separate::

    python -m app.importer export --site zmb.dozuki.com --out <dir>
    python -m app.importer load --archive <dir>

``export`` copies everything the vendor's official API will hand over — the raw
JSON responses and the media files — into a self-contained directory. It needs
no Reticle database and it is the urgent half: the API stops answering when the
subscription lapses, and nothing in the contract obliges the vendor to return
the content afterwards. ``load`` reads that directory, at leisure and as often
as needed, and writes guides, pages, categories, tags and media through the
same code paths the application itself uses to save and publish.

Everything goes through the documented API with the site's own credentials.
Nothing here reads the vendor's HTML pages; see ``NOTICE.md``.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

TOOL_NAME = "reticle-importer"
TOOL_VERSION = "1.1.0"

ARCHIVE_FORMAT = 1
"""Bumped when the on-disk layout changes in a way an older ``load`` cannot read."""
