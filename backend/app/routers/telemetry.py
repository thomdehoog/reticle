"""Where a browser-side crash goes.

Reticle catches render failures and shows a page instead of a blank tab, and
until now that was the end of it: the detail went to ``console.error``, which
lives on one person's laptop and is seen only if somebody thinks to open
devtools and describe what they see. In practice a rendering bug reached
whoever wrote it as "it did not work this morning", if at all.

This endpoint moves that into the same log stream as everything else, with a
request id, so a report is one line in the place the operator is already
looking.

The whole design consideration is that this accepts text from a client and
writes it to a log file. Three consequences, all handled below: the text is
truncated, newlines are removed so a caller cannot forge surrounding entries,
and it stays behind the login and inside the rate limiter's write budget so it
cannot be used to fill a disk.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..auth import AnyUser
from ..observability import request_id

router = APIRouter(prefix="/api/client-errors", tags=["telemetry"])

logger = logging.getLogger("reticle.client")

MAX_MESSAGE = 500
MAX_STACK = 4000
MAX_URL = 500


class ClientError(BaseModel):
    """What the error boundary knows and is willing to say.

    Deliberately not "whatever the client wants to send". No user text, no form
    values, no local storage — a crash report that scoops up the surrounding
    state is a crash report that eventually contains a password somebody was
    typing.
    """

    message: str = Field(max_length=MAX_MESSAGE)
    componentStack: str = Field(default="", max_length=MAX_STACK)
    url: str = Field(default="", max_length=MAX_URL)


def sanitised(value: str, limit: int) -> str:
    """One line, bounded.

    Newlines are what turn a logged string into forged log entries: a value
    containing ``\\n{"level":"INFO","message":"..."}`` reads back as a separate
    record. Replacing rather than rejecting keeps a genuine multi-line stack
    useful while making it a single entry.
    """
    collapsed = " ".join(value.replace("\r", " ").replace("\n", " ⏎ ").split())
    return collapsed[:limit]


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def report_client_error(report: ClientError, user: AnyUser) -> None:
    """Record a browser-side failure against the session that hit it.

    The user is identified by id rather than by name or address: enough to ask
    them what they were doing, and not a record of who was reading what.
    """
    logger.error(
        "client error",
        extra={
            "clientMessage": sanitised(report.message, MAX_MESSAGE),
            "componentStack": sanitised(report.componentStack, MAX_STACK),
            "clientUrl": sanitised(report.url, MAX_URL),
            "userId": user.id,
            "requestId": request_id.get(),
        },
    )
