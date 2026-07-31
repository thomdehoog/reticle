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

Content is imported through the **official vendor API or a vendor-provided
export**, using ZMB's own account credentials, and only for content ZMB owns.

Bulk scraping of the hosted site is deliberately **not** used: it is the route
most likely to conflict with a vendor's terms of service, and it is unnecessary
when a supported export path exists.

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
