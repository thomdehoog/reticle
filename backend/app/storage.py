"""Where uploaded photographs and videos are kept.

Every picture in a guide is a file that has to live somewhere. On the server
ZMB runs, "somewhere" is a folder on its hard disk. If Reticle is ever hosted
for several facilities at once, it becomes a bucket in cloud storage instead,
because a folder on one machine's disk cannot be shared between machines and
disappears if that machine is replaced.

This file exists so that the rest of the program never has to know which of
those two it is. Everywhere else just says "save this file" and "give me that
file back", and this module decides how. Swapping one for the other is a
setting, not a rewrite.

One rule governs everything here: **a file is only ever handed to someone
allowed to see it.** Guides contain photographs of access badges, licence keys
taped to instruments, and results that are not published yet. Cloud storage
makes it very easy to mark a file "anyone with the link can read this", and
that cannot be undone later — whatever was copied while it was open stays
copied. So files are always stored privately, and when one is needed the
application checks first, then hands out a link that stops working within
minutes.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from . import errors

if TYPE_CHECKING:
    from .settings import Settings

SIGNED_URL_SECONDS = 300
"""Long enough for a browser to fetch an image on a slow bench connection,
short enough that a URL copied out of devtools is worthless by the time anybody
uses it. A guide page is read for minutes, not hours."""


@runtime_checkable
class Storage(Protocol):
    """What the application needs of a file store, and nothing more.

    Deliberately small. Every method here is one the routers, the exporter, the
    importer or the static site generator actually call; anything larger would
    be inventing requirements for a backend nobody has written yet.
    """

    def write(self, storage_path: str, payload: bytes) -> None:
        """Store bytes, creating whatever structure the backend needs."""

    def read(self, storage_path: str) -> bytes:
        """Return the bytes, or raise ``errors.not_found``."""

    def exists(self, storage_path: str) -> bool: ...

    def delete(self, storage_path: str) -> None:
        """Remove it. Missing is not an error — deleting is idempotent."""

    def local_path(self, storage_path: str) -> Path | None:
        """A real filesystem path, when the backend has one.

        ``None`` for anything remote. Callers use it as a fast path — serving a
        file directly and copying during an export — and must have a fallback
        through ``read`` for when it is absent.
        """

    def signed_url(self, storage_path: str, seconds: int = SIGNED_URL_SECONDS) -> str | None:
        """A time-limited URL, when the backend can issue one; ``None`` if not."""


class LocalStorage:
    """Files under a directory. The default, and what ZMB runs.

    The containment check is applied on read as well as on write. The stored
    path is server-generated, so a traversal can only arise if the database has
    been edited directly — which is exactly the situation in which a path check
    earns its keep.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _target(self, storage_path: str) -> Path:
        root = self.root.resolve()
        target = (root / storage_path).resolve()
        if not target.is_relative_to(root):
            raise errors.not_found("That file is no longer available.")
        return target

    def write(self, storage_path: str, payload: bytes) -> None:
        target = self._target(storage_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def read(self, storage_path: str) -> bytes:
        return self.local_path_or_404(storage_path).read_bytes()

    def exists(self, storage_path: str) -> bool:
        try:
            return self._target(storage_path).is_file()
        except errors.ApiError:
            return False

    def delete(self, storage_path: str) -> None:
        self._target(storage_path).unlink(missing_ok=True)

    def local_path(self, storage_path: str) -> Path | None:
        target = self._target(storage_path)
        return target if target.is_file() else None

    def local_path_or_404(self, storage_path: str) -> Path:
        target = self.local_path(storage_path)
        if target is None:
            raise errors.not_found("That file is no longer available.")
        return target

    def signed_url(self, storage_path: str, seconds: int = SIGNED_URL_SECONDS) -> str | None:
        return None


class S3Storage:
    """S3-compatible object storage — AWS, a Swiss or EU provider, or MinIO.

    boto3 is imported lazily so the dependency is only needed by an
    installation that has chosen this backend. A single-facility server running
    on local disk should not have to install an AWS SDK.

    Objects are written with **no ACL**, so they inherit the bucket's default
    and are private. That is not an oversight to be corrected later: it is the
    mechanism by which the login still protects the media. Reads go out as
    signed URLs, issued only after the caller has passed the same visibility
    check the local backend's route performs.
    """

    def __init__(self, bucket: str, prefix: str = "", client=None, **client_kwargs) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = client
        self._client_kwargs = client_kwargs

    @property
    def client(self):
        if self._client is None:
            import boto3  # imported here so the dependency stays optional

            self._client = boto3.client("s3", **self._client_kwargs)
        return self._client

    def _key(self, storage_path: str) -> str:
        return f"{self.prefix}/{storage_path}" if self.prefix else storage_path

    def write(self, storage_path: str, payload: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._key(storage_path), Body=payload)

    def read(self, storage_path: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(storage_path))
        except Exception as failure:
            raise errors.not_found("That file is no longer available.") from failure
        return response["Body"].read()

    def exists(self, storage_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(storage_path))
        except Exception:
            return False
        return True

    def delete(self, storage_path: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(storage_path))

    def local_path(self, storage_path: str) -> Path | None:
        return None

    def signed_url(self, storage_path: str, seconds: int = SIGNED_URL_SECONDS) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(storage_path)},
            ExpiresIn=seconds,
        )


def build_storage(settings: Settings) -> Storage:
    """Pick a backend from configuration. The only way to get one.

    Takes the settings rather than reading them, so the caller that already has
    a ``Settings`` — the importer, the exporter, the static site generator — is
    guaranteed to get the store those settings describe. A router with none in
    hand passes ``get_settings()``.

    Nothing is cached. ``LocalStorage`` is two attributes and a few path
    operations, so building one per request costs nothing measurable, and a
    cached one would make the media root impossible to change in a test without
    reaching into a module global — which is how a suite ends up writing into
    the developer's real media directory.

    An unknown backend name raises rather than falling back to local. A typo in
    ``RETICLE_STORAGE_BACKEND`` that silently wrote a facility's uploads to the
    instance's own disk would look like it worked, right up until the instance
    was replaced.
    """
    backend = (settings.storage_backend or "local").lower()
    if backend == "local":
        return LocalStorage(settings.media_root)
    if backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("RETICLE_S3_BUCKET must be set when the storage backend is s3.")
        return S3Storage(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
        )
    raise ValueError(f"Unknown storage backend {backend!r}. Use 'local' or 's3'.")
