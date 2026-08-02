"""Runtime configuration, read once from the environment.

Nothing security-relevant has a usable default. ``secret_key`` in particular is
mandatory: a fallback value would be identical on every deployment, and since
it is the pepper for session-token hashes a shared default would let anyone who
obtained one installation's database forge sessions on another.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .images import MAX_IMAGE_PIXELS_DEFAULT

ENV_FILE_VARIABLE = "RETICLE_ENV_FILE"
DEFAULT_ENV_FILE = ".env"

WILDCARD_ORIGIN_REFUSAL = (
    "RETICLE_CORS_ORIGINS must not contain '*'. Reticle authenticates with cookies and sends "
    "Access-Control-Allow-Credentials, and a wildcard makes the server reflect whichever origin "
    "asks — so any page a signed-in colleague happens to visit could read every guide in the "
    "institute. List the exact origins instead, for example https://guides.zmb.uzh.ch."
)


class Settings(BaseSettings):
    """Every knob Reticle exposes, prefixed ``RETICLE_`` in the environment.

    The env file is read as ``utf-8-sig`` rather than ``utf-8``. Notepad and
    Windows PowerShell both write a byte-order mark by default, and a BOM
    attaches itself to the first variable name, so the first line of the file
    silently fails to load — which on this deployment is usually the secret key.
    """

    model_config = SettingsConfigDict(
        env_prefix="RETICLE_",
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    secret_key: str = Field(min_length=16)
    database_url: str = "sqlite:///./reticle.db"
    media_root: Path = Path("./media")

    # "local" or "s3". Local disk is right for one facility on one server; it
    # cannot be shared between processes and does not survive the instance
    # being replaced, which is what object storage is for. See app/storage.py.
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = ""
    s3_endpoint_url: str = ""  # set for MinIO or a non-AWS provider
    s3_region: str = ""

    debug: bool = False

    # DEBUG logs every SQL statement, which on this application means the full
    # text of a guide on every save. Useful for an afternoon, never in
    # production.
    log_level: str = "INFO"

    cookie_secure: bool = True
    cookie_domain: str | None = None
    session_lifetime_hours: int = 12

    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # A ceiling on everything that is not a login. Set where a person cannot
    # reach it and a runaway script can: an author saving every few seconds, a
    # reader opening thirty guides and an importer pushing a corpus all have to
    # pass untouched, because a limit that blocks real work gets switched off.
    # Per process and per minute - see app/ratelimit.py.
    rate_limit_enabled: bool = True
    rate_limit_reads_per_minute: int = 600
    rate_limit_writes_per_minute: int = 240
    rate_limit_uploads_per_minute: int = 60

    login_max_attempts_per_email_and_ip: int = 5
    login_max_attempts_per_email: int = 50
    login_max_attempts_per_ip: int = 20
    login_attempt_window_minutes: int = 15

    trust_forwarded_for: bool = False

    max_request_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 20 * 1024 * 1024
    max_video_bytes: int = 200 * 1024 * 1024
    max_image_dimension: int = 10_000
    max_image_pixels: int = MAX_IMAGE_PIXELS_DEFAULT
    max_media_per_step: int = 4

    min_password_length: int = 12

    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 4

    organisation_name: str = "Center for Microscopy and Image Analysis"
    organisation_short_name: str = "ZMB"
    organisation_url: str | None = None
    """Whose instance this is.

    Configuration rather than source, because one Reticle per facility is the
    intended shape: each runs its own process, its own database and its own
    media store, and the only thing that differs is whose name is on it. A
    facility should not have to fork the software to put its own name in the
    header.
    """

    admin_email: str = "admin@zmb.uzh.ch"
    admin_password: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept both a JSON array and a plain comma-separated line.

        ``NoDecode`` on the field is what makes this reachable: without it
        pydantic-settings JSON-decodes list-typed values inside the source,
        before any validator runs, and a comma-separated line in a ``.env`` file
        aborts start-up instead of arriving here. Taking the decoding over means
        this validator owns both forms, so the JSON one has to be parsed rather
        than passed through.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @field_validator("cors_origins")
    @classmethod
    def _refuse_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Refuse to start rather than reflect every origin back with credentials.

        Starlette treats ``["*"]`` together with ``allow_credentials=True`` as an
        instruction to echo the request's own ``Origin`` header, which is not a
        wildcard at all — it is universal approval. An operator reaching for
        ``*`` is almost always trying to unblock one forgotten hostname, so
        failing loudly at start-up costs them a minute and refusing quietly
        would cost the institute every guide it holds.
        """
        if any(origin.strip() == "*" for origin in value):
            raise ValueError(WILDCARD_ORIGIN_REFUSAL)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load configuration, honouring an explicit env-file location.

    A deployment keeps its environment file wherever the service manager wants
    it, not in the process working directory, and the test suite sets the
    variable to empty so that a developer's ``.env`` sitting next to the code
    cannot quietly change what the tests are asserting.
    """
    env_file = os.environ.get(ENV_FILE_VARIABLE, DEFAULT_ENV_FILE)
    return Settings(_env_file=env_file or None)
