"""The limits a client should know before it sends anything.

The upload limits are the operator's to set, and the browser used to carry its
own copy of the defaults. On a server configured for 500 MB videos the editor
then refused, in the server's name, files the server would have taken; on one
configured for less it let people upload for ten minutes to be told no. This
endpoint is the one place the effective numbers are published.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter

from ..auth import AnyUser
from ..schemas import ConfigOut
from ..settings import get_settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigOut)
def read_config(user: AnyUser) -> ConfigOut:
    """The limits in force, and nothing else.

    Behind the login like everything else, and deliberately an explicit list
    rather than a dump of the settings object: that object also holds the
    secret key and the first administrator's password.
    """
    settings = get_settings()
    return ConfigOut(
        max_image_bytes=settings.max_upload_bytes,
        max_video_bytes=settings.max_video_bytes,
        max_media_per_step=settings.max_media_per_step,
    )
