"""User administration and password changes."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Session as SessionRow
from app.models import User

from .conftest import TEST_PASSWORD

NEW_PASSWORD = "A-Completely-Different-One-4"


def test_an_admin_lists_users(admin, make_user):
    make_user("colleague@zmb.uzh.ch", role="author", display_name="Colleague")

    response = admin.get("/api/users")

    assert response.status_code == 200
    listing = {entry["email"]: entry for entry in response.json()}
    assert set(listing) == {"admin@zmb.uzh.ch", "colleague@zmb.uzh.ch"}
    assert listing["colleague@zmb.uzh.ch"]["role"] == "author"
    assert set(listing["colleague@zmb.uzh.ch"]) == {
        "id",
        "email",
        "displayName",
        "role",
        "isActive",
        "createdAt",
    }
    assert listing["colleague@zmb.uzh.ch"]["isActive"] is True


def test_authors_and_viewers_cannot_manage_users(author, viewer, make_user):
    other = make_user("other@zmb.uzh.ch")

    assert author.get("/api/users").status_code == 403
    assert viewer.get("/api/users").status_code == 403
    assert (
        author.post(
            "/api/users", json={"email": "x@zmb.uzh.ch", "password": NEW_PASSWORD, "role": "admin"}
        ).status_code
        == 403
    )
    assert author.patch(f"/api/users/{other.id}", json={"role": "admin"}).status_code == 403


def test_an_admin_creates_a_user_who_can_then_log_in(admin, client_factory):
    response = admin.post(
        "/api/users",
        json={
            "email": "New.Hire@ZMB.uzh.ch",
            "displayName": "New Hire",
            "role": "author",
            "password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new.hire@zmb.uzh.ch"
    assert response.json()["role"] == "author"
    assert "password" not in response.json()

    fresh = client_factory("192.0.2.50")
    assert fresh.login("new.hire@zmb.uzh.ch", NEW_PASSWORD).status_code == 200


def test_a_created_user_password_is_hashed_not_stored(admin, db_session):
    admin.post(
        "/api/users",
        json={"email": "hashed@zmb.uzh.ch", "role": "viewer", "password": NEW_PASSWORD},
    )

    stored = db_session.scalars(select(User).where(User.email == "hashed@zmb.uzh.ch")).one()
    assert stored.password_hash.startswith("$argon2id$")
    assert NEW_PASSWORD not in stored.password_hash


def test_a_duplicate_email_conflicts(admin):
    response = admin.post(
        "/api/users", json={"email": "admin@zmb.uzh.ch", "role": "viewer", "password": NEW_PASSWORD}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_a_weak_password_is_refused(admin):
    response = admin.post(
        "/api/users", json={"email": "weak@zmb.uzh.ch", "role": "viewer", "password": "short"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_an_unknown_role_is_refused(admin):
    assert (
        admin.post(
            "/api/users",
            json={"email": "x@zmb.uzh.ch", "role": "superuser", "password": NEW_PASSWORD},
        ).status_code
        == 422
    )


def test_an_admin_changes_a_role_and_a_display_name(admin, make_user):
    target = make_user("promote@zmb.uzh.ch", role="viewer")

    body = admin.patch(
        f"/api/users/{target.id}", json={"role": "author", "displayName": "Promoted Person"}
    ).json()

    assert body["role"] == "author"
    assert body["displayName"] == "Promoted Person"


def test_deactivating_a_user_blocks_login_and_kills_live_sessions(admin, as_role, db_session):
    victim = as_role("author", "victim@zmb.uzh.ch")
    victim_id = victim.get("/api/auth/me").json()["id"]

    admin.patch(f"/api/users/{victim_id}", json={"isActive": False})

    assert victim.get("/api/auth/me").status_code == 401
    assert victim.login("victim@zmb.uzh.ch").status_code == 401
    assert all(
        row.revoked_at is not None
        for row in db_session.scalars(select(SessionRow).where(SessionRow.user_id == victim_id))
    )


def test_an_admin_cannot_lock_themselves_out(admin):
    me = admin.get("/api/auth/me").json()

    assert admin.patch(f"/api/users/{me['id']}", json={"isActive": False}).status_code == 422
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 422


def test_patching_an_unknown_user_is_not_found(admin):
    assert (
        admin.patch("/api/users/01JQNOTAREALULID00000000", json={"role": "viewer"}).status_code
        == 404
    )


def test_a_user_changes_their_own_password_with_the_current_one(author, client_factory):
    me = author.get("/api/auth/me").json()

    response = author.post(
        f"/api/users/{me['id']}/password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
    )

    assert response.status_code == 204
    fresh = client_factory("192.0.2.60")
    assert fresh.login("author@zmb.uzh.ch", TEST_PASSWORD).status_code == 401
    assert fresh.login("author@zmb.uzh.ch", NEW_PASSWORD).status_code == 200


def test_the_wrong_current_password_is_refused(author):
    me = author.get("/api/auth/me").json()

    response = author.post(
        f"/api/users/{me['id']}/password",
        json={"currentPassword": "not-it", "newPassword": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_a_self_change_must_supply_the_current_password(author):
    me = author.get("/api/auth/me").json()

    assert (
        author.post(
            f"/api/users/{me['id']}/password", json={"newPassword": NEW_PASSWORD}
        ).status_code
        == 422
    )


def test_a_user_cannot_change_someone_else_s_password(author, make_user):
    other = make_user("other@zmb.uzh.ch")

    response = author.post(
        f"/api/users/{other.id}/password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
    )

    assert response.status_code == 403


def test_an_admin_resets_another_password_without_knowing_it(admin, make_user, client_factory):
    target = make_user("forgot@zmb.uzh.ch", role="viewer")

    assert (
        admin.post(
            f"/api/users/{target.id}/password", json={"newPassword": NEW_PASSWORD}
        ).status_code
        == 204
    )
    assert client_factory("192.0.2.70").login("forgot@zmb.uzh.ch", NEW_PASSWORD).status_code == 200


def test_changing_a_password_revokes_every_session_of_that_user(admin, as_role, db_session):
    victim = as_role("author", "compromised@zmb.uzh.ch")
    victim_id = victim.get("/api/auth/me").json()["id"]

    admin.post(f"/api/users/{victim_id}/password", json={"newPassword": NEW_PASSWORD})

    assert victim.get("/api/auth/me").status_code == 401


def test_a_password_change_keeps_the_actor_s_own_session_alive(author, client_factory):
    me = author.get("/api/auth/me").json()

    author.post(
        f"/api/users/{me['id']}/password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
    )

    assert author.get("/api/auth/me").status_code == 200


def test_user_endpoints_require_a_session(anon):
    assert anon.get("/api/users").status_code == 401
