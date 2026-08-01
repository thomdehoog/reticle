# Provenance and licensing

## Reticle is an independent implementation

Reticle is written from scratch for the Center for Microscopy and Image Analysis
(ZMB), University of Zurich. It is not derived from, and contains no code from,
any commercial guide-authoring product.

Specifically, this project contains **no** third-party proprietary:

- source code, markup, stylesheets or JavaScript,
- icon, logo or image assets,
- product names or trademarks,
- help-centre or documentation text.

All icon artwork, styling and page layout in this repository is original work.

Reticle is deliberately **not** a visual copy of any vendor's interface. It
implements the same functions and looks like itself. That is a design decision,
not only a legal one: a facility's documentation should look like the facility's
own, and a lookalike would invite the question of what else was copied.

Reticle implements *functionality* that other guide platforms also implement —
numbered procedural steps, annotated bullets, per-step images, categories,
draft/publish states. Functional concepts, workflows and conventions of this
kind are not protected by copyright; only a specific expression of them is, and
every line of expression here is our own.

## Guide content belongs to ZMB

The procedural content migrated into Reticle — guide text, photographs,
diagrams, protocols — is the work of ZMB staff and remains ZMB's property.
Moving it into self-hosted software is data portability, not redistribution of
anyone else's material.

## Content migration policy

Content is imported through the **official vendor API**, and only for content
ZMB owns. The importer lives in `backend/app/importer/`; `docs/MIGRATION.md`
describes exactly what it reads and what it writes.

Bulk scraping of the hosted site is deliberately **not** used. It is the route
most likely to conflict with a vendor's terms of service, and it is unnecessary
when a supported export path exists — the guide and wiki endpoints return
everything the site displays, in a form that does not have to be reverse
engineered from markup.

What the importer takes is **content**: text, images, video, annotation
geometry, tags and structure. What it never takes is **expression of the
interface**: no HTML, no stylesheet, no script, no icon, no font, no layout.
Rendered HTML in a payload is reduced to text and to Reticle's own structures on
the way in, so vendor markup cannot survive the crossing even accidentally.

Before running the importer, confirm that your account's terms permit export of
your own content. This is normal for a paid account, but it is worth a look at
the contract, and worth telling the vendor you are exercising it.

## Licence

Reticle itself is released under the MIT Licence — see `LICENSE`.

The MIT licence covers the *software*. It does not grant rights to ZMB guide
content, images or branding, which remain ZMB's and are not published under the
MIT terms by virtue of living in this repository.

---

This document records engineering decisions taken to keep the project clear of
third-party rights. It is not legal advice; if ZMB wants certainty about its
vendor contract, that is a question for UZH legal services.
