"""The file store, and the rule that must survive changing it.

Media sit behind the login. Reticle refuses a viewer a file unless a published
guide or page actually shows it, and that has been fixed twice in this codebase
because each new way of displaying a file was a fresh copy of the same hole.

Introducing a second backend is the third chance to lose it, and the way it
would be lost is specific: object storage makes it *easy* to hand out a public
URL, and a public URL is not a hole that can be closed later — anything already
copied stays readable. So the S3 tests below assert on what is sent to the
client library, not just on what comes back.

boto3 is never imported. ``S3Storage`` takes an injected client, which is what
makes an object-storage backend testable on a machine with no network and no
credentials at all.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app import errors
from app.storage import LocalStorage, S3Storage, Storage, build_storage


class FakeS3:
    """Enough of the boto3 S3 client to exercise the backend, and no more."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict] = []
        self.presign_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presign_calls.append({"op": operation, "params": Params, "expires": ExpiresIn})
        return f"https://example.invalid/{Params['Key']}?expires={ExpiresIn}"


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class Settings:
    def __init__(self, **fields):
        self.media_root = fields.pop("media_root", Path(tempfile.gettempdir()) / "reticle-test")
        self.storage_backend = fields.pop("storage_backend", "local")
        self.s3_bucket = fields.pop("s3_bucket", "")
        self.s3_prefix = fields.pop("s3_prefix", "")
        self.s3_endpoint_url = fields.pop("s3_endpoint_url", "")
        self.s3_region = fields.pop("s3_region", "")


# --- both backends satisfy the same contract -------------------------------


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalStorage(tmp_path)
    return S3Storage(bucket="reticle-test", prefix="media", client=FakeS3())


def test_what_was_written_is_what_comes_back(store):
    store.write("ab/cd/abcdef.png", b"\x89PNG-pretend")

    assert store.read("ab/cd/abcdef.png") == b"\x89PNG-pretend"


def test_a_file_reports_that_it_exists(store):
    assert store.exists("ab/cd/abcdef.png") is False

    store.write("ab/cd/abcdef.png", b"x")

    assert store.exists("ab/cd/abcdef.png") is True


def test_deleting_is_idempotent(store):
    """A restore or a cleanup runs twice more often than it runs once."""
    store.write("ab/cd/gone.png", b"x")

    store.delete("ab/cd/gone.png")
    store.delete("ab/cd/gone.png")

    assert store.exists("ab/cd/gone.png") is False


def test_reading_something_that_is_not_there_is_a_not_found(store):
    with pytest.raises(errors.ApiError) as raised:
        store.read("ab/cd/never-written.png")

    assert raised.value.status_code == 404


def test_both_backends_satisfy_the_protocol(store):
    assert isinstance(store, Storage)


# --- local disk ------------------------------------------------------------


def test_a_path_that_climbs_out_of_the_media_root_is_refused(tmp_path):
    """The stored path is server-generated, so this can only fire if the
    database was edited directly — which is exactly when it earns its keep."""
    store = LocalStorage(tmp_path / "media")
    store.write("ok.png", b"x")

    with pytest.raises(errors.ApiError):
        store.write("../escaped.png", b"payload")

    assert not (tmp_path / "escaped.png").exists()


def test_traversal_is_refused_on_read_as_well_as_on_write(tmp_path):
    (tmp_path / "secret.txt").write_bytes(b"not for you")
    store = LocalStorage(tmp_path / "media")

    with pytest.raises(errors.ApiError):
        store.read("../secret.txt")

    assert store.exists("../secret.txt") is False


def test_nested_directories_are_created_on_demand(tmp_path):
    """ULIDs are time-ordered, so media are sharded into two levels rather than
    one directory that grows until ``ls`` cannot open it."""
    store = LocalStorage(tmp_path)

    store.write("01/HZ/01HZABC.png", b"x")

    assert (tmp_path / "01" / "HZ" / "01HZABC.png").read_bytes() == b"x"


def test_local_offers_a_real_path_and_no_signed_url(tmp_path):
    """The two are complementary: a caller uses whichever is not None."""
    store = LocalStorage(tmp_path)
    store.write("a.png", b"x")

    assert store.local_path("a.png") is not None
    assert store.signed_url("a.png") is None


def test_a_missing_local_file_has_no_path_rather_than_a_broken_one(tmp_path):
    assert LocalStorage(tmp_path).local_path("nope.png") is None


# --- object storage --------------------------------------------------------


def test_an_uploaded_object_is_never_made_public():
    """The load-bearing assertion in this file.

    A public-read ACL cannot be walked back: whatever was fetched while the
    bucket was open stays fetched. Reticle's media include photographs of access
    badges and unpublished results, so the object must inherit the bucket's
    private default and be reached only through a signed URL.
    """
    fake = FakeS3()
    store = S3Storage(bucket="reticle", prefix="media", client=fake)

    store.write("ab/cd/x.png", b"x")

    call = fake.put_calls[0]
    assert "ACL" not in call
    assert call["Bucket"] == "reticle"
    assert call["Key"] == "media/ab/cd/x.png"


def test_remote_objects_are_served_by_signed_url_not_by_a_path():
    store = S3Storage(bucket="reticle", client=FakeS3())
    store.write("a.png", b"x")

    assert store.local_path("a.png") is None
    assert store.signed_url("a.png").startswith("https://")


def test_a_signed_url_expires_soon_enough_to_be_worthless_if_copied():
    """Long enough to load an image on a slow bench connection; short enough
    that a URL pasted out of devtools has expired before anybody uses it."""
    fake = FakeS3()
    store = S3Storage(bucket="reticle", client=fake)

    store.signed_url("a.png")

    assert fake.presign_calls[0]["expires"] <= 900
    assert fake.presign_calls[0]["op"] == "get_object"


def test_the_prefix_keeps_one_facility_out_of_another_s_keys():
    """A shared bucket with a per-facility prefix is a supported arrangement,
    so the prefix has to be applied on every operation, not only on write."""
    fake = FakeS3()
    store = S3Storage(bucket="shared", prefix="zmb", client=fake)

    store.write("a.png", b"x")
    store.read("a.png")
    store.delete("a.png")

    assert set(fake.objects) == set()
    assert fake.put_calls[0]["Key"] == "zmb/a.png"


def test_no_prefix_leaves_keys_unchanged():
    fake = FakeS3()
    S3Storage(bucket="b", client=fake).write("a.png", b"x")

    assert fake.put_calls[0]["Key"] == "a.png"


# --- choosing a backend ----------------------------------------------------


def test_the_default_is_local_disk(tmp_path):
    assert isinstance(build_storage(Settings(media_root=tmp_path)), LocalStorage)


def test_a_typo_in_the_backend_name_is_refused_rather_than_falling_back():
    """Falling back to local would look like it worked, right up until the
    instance was replaced and a facility's uploads went with it."""
    with pytest.raises(ValueError, match="Unknown storage backend"):
        build_storage(Settings(storage_backend="s3-compatible"))


def test_choosing_s3_without_a_bucket_fails_at_startup_not_at_first_upload():
    with pytest.raises(ValueError, match="S3_BUCKET"):
        build_storage(Settings(storage_backend="s3"))


def test_the_backend_name_is_not_case_sensitive(tmp_path):
    assert isinstance(build_storage(Settings(storage_backend="LOCAL", media_root=tmp_path)), LocalStorage)
