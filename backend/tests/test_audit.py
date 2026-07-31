"""The audit trail: who changed what, when.

ZMB runs shared instruments and shared documentation; when a procedure changes,
somebody has to be able to answer "who did that and when" without restoring a
backup.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog

from .conftest import create_guide, document_from, image_bytes, step


def entries(db_session):
    return db_session.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)).all()


def test_a_successful_login_is_recorded_with_the_source_address(client_factory, make_user, db_session):
    make_user("audited@zmb.uzh.ch")
    client_factory("198.51.100.22").login("audited@zmb.uzh.ch")

    record = entries(db_session)[-1]

    assert record.action == "auth.login"
    assert record.ip_address == "198.51.100.22"
    assert record.actor_id is not None


def test_a_failed_login_records_neither_the_password_nor_the_typed_address(
    client_factory, make_user, db_session
):
    """The submitted string is never stored verbatim.

    A password typed into the email box only needs an ``@`` to satisfy
    validation and reach this record, and it would then sit in the audit table
    in plaintext. A digest still lets an admin correlate repeated attempts
    against one account without holding the text.
    """
    from app.security import email_fingerprint

    make_user("audited@zmb.uzh.ch")
    client_factory("198.51.100.23").login("audited@zmb.uzh.ch", "the-wrong-password")

    record = entries(db_session)[-1]

    assert record.action == "auth.login_failed"
    assert "the-wrong-password" not in repr(record.detail)
    assert "audited@zmb.uzh.ch" not in repr(record.detail)
    assert record.detail["emailDigest"] == email_fingerprint("audited@zmb.uzh.ch")


def test_a_failed_login_for_an_unknown_account_records_no_actor(anon, db_session):
    anon.login("ghost@zmb.uzh.ch", "whatever")

    record = entries(db_session)[-1]

    assert record.action == "auth.login_failed"
    assert record.actor_id is None


def test_the_guide_lifecycle_is_audited(author, admin, category, db_session):
    created = create_guide(author, category.id)
    author.put(f"/api/guides/{created['id']}", json=document_from(created, steps=[step("One")]))
    author.post(f"/api/guides/{created['id']}/publish")
    author.post(f"/api/guides/{created['id']}/unpublish")
    admin.delete(f"/api/guides/{created['id']}")

    actions = [r.action for r in entries(db_session) if r.entity_type == "guide"]

    assert actions == ["guide.create", "guide.update", "guide.publish", "guide.unpublish", "guide.archive"]
    assert all(r.entity_id == created["id"] for r in entries(db_session) if r.entity_type == "guide")


def test_the_publish_record_carries_the_version(author, category, db_session):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")

    record = next(r for r in entries(db_session) if r.action == "guide.publish")

    assert record.detail["version"] == 1


def test_user_and_category_administration_is_audited(admin, db_session):
    created = admin.post("/api/categories", json={"name": "Spatial Biology"}).json()
    admin.patch(f"/api/categories/{created['id']}", json={"name": "Spatial Omics"})
    user = admin.post("/api/users", json={"email": "audited.new@zmb.uzh.ch", "role": "author", "password": "Long-Enough-Password-1"}).json()
    admin.post(f"/api/users/{user['id']}/password", json={"newPassword": "Another-Long-Password-2"})

    actions = [r.action for r in entries(db_session) if r.entity_type in {"category", "user"}]

    assert actions == ["category.create", "category.update", "user.create", "user.password_change"]


def test_a_password_change_never_lands_in_the_audit_detail(admin, db_session):
    user = admin.post("/api/users", json={"email": "secret@zmb.uzh.ch", "role": "viewer", "password": "Long-Enough-Password-1"}).json()
    admin.post(f"/api/users/{user['id']}/password", json={"newPassword": "Another-Long-Password-2"})

    assert not any("Long-Enough" in repr(r.detail) or "Another-Long" in repr(r.detail) for r in entries(db_session))


def test_an_upload_is_audited_with_its_size_and_type(author, db_session):
    payload = image_bytes(40, 30)
    created = author.post("/api/media", files={"file": ("x.png", payload, "image/png")}).json()

    record = next(r for r in entries(db_session) if r.action == "media.upload")

    assert record.entity_id == created["id"]
    assert record.detail["contentType"] == "image/png"
    assert record.detail["byteSize"] > 0


def test_rejected_writes_leave_no_audit_entry(viewer, category, db_session):
    viewer.post("/api/guides", json={"title": "Denied", "categoryId": category.id})

    assert [r.action for r in entries(db_session) if r.entity_type == "guide"] == []
