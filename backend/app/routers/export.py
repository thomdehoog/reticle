"""Taking the corpus out.

ZMB is here because a hosted platform held their material behind an API that
ends with the subscription. The way out of Reticle is therefore an endpoint
rather than a favour: two of them, because the two things an operator wants are
genuinely different.

``GET /api/export`` is the document — every guide, page, category, tag and
account, in the same camelCase shapes the rest of the API serves. It is what a
destination system reads.

``GET /api/export/archive`` is the document plus every image and video, streamed
as a gzipped tar. It is what a person walks away with.

Both are administrator-only and both are audited. This is the entire
institute's documentation in one request, which makes it the most useful thing
in the application to somebody who should not have it — the restriction is not
bureaucracy, and the audit entry is how a download that should not have
happened is noticed afterwards.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import audit, exporter
from ..auth import AdminUser, DbDep, client_address
from ..db import utcnow
from ..settings import get_settings

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("", response_model=None)
def export_document(request: Request, db: DbDep, user: AdminUser) -> dict[str, Any]:
    """Everything, as JSON, without the files themselves.

    Media appear as metadata with a checksum and the path they occupy inside the
    archive, so this document and the archive describe the same export and a
    reader can tell which files it is still missing.
    """
    settings = get_settings()
    document = exporter.build_document(db, settings)

    audit.record(
        db,
        action="export.document",
        entity_type="export",
        entity_id=None,
        actor=user,
        ip_address=client_address(request),
        detail=document["reticleExport"]["counts"],
    )
    db.commit()
    return document


@router.get("/archive", response_model=None)
def export_archive(request: Request, db: DbDep, user: AdminUser) -> StreamingResponse:
    """The document and every file, streamed as ``.tar.gz``.

    Recorded before the stream starts rather than after it finishes: a download
    that is interrupted half way still happened, and an audit trail that only
    logs completed transfers is one an interrupted transfer hides in.
    """
    settings = get_settings()
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"reticle-export-{stamp}.tar.gz"

    audit.record(
        db,
        action="export.archive",
        entity_type="export",
        entity_id=None,
        actor=user,
        ip_address=client_address(request),
        detail={"filename": filename},
    )
    db.commit()

    return StreamingResponse(
        exporter.stream_archive(db, settings),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
