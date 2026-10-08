from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.team_member import TeamInvite, TeamMember
from app.models.user import User
from tests.conftest import make_pdf

PASSWORD = "correct horse battery"


# Team invites


def _invite(client, owner, email, role="MEMBER"):
    return client.post("/members/invite", headers=owner["headers"], json={"email": email, "role": role})


def test_existing_and_new_emails_get_the_same_invite_answer(client, db, make_user, emails):
    owner = make_user(plan="PRO")
    existing = make_user(email="colleague@traqtest.io")

    known = _invite(client, owner, "colleague@traqtest.io")
    unknown = _invite(client, owner, "nobody@traqtest.io")
    assert known.status_code == unknown.status_code == 200

    def shape(body):
        return sorted(body), sorted(body["invite"]), body["invited"], body["email_delivered"]

    assert shape(known.json()) == shape(unknown.json())
    assert "added" not in known.json() and "member" not in known.json()
    assert db.query(TeamMember).filter(TeamMember.user_id == existing["user"].id).count() == 0
    assert db.query(TeamInvite).filter(TeamInvite.status == "PENDING").count() == 2


def test_existing_user_joins_only_after_accepting(client, db, make_user):
    owner = make_user(plan="PRO")
    owner["team"].name = "Rossi Translations"
    db.commit()
    colleague = make_user(email="colleague@traqtest.io")
    _invite(client, owner, "colleague@traqtest.io", role="REVIEWER")
    token = db.query(TeamInvite).one().token

    members = client.get("/members", headers=owner["headers"]).json()
    assert [m["email"] for m in members["members"]] == [owner["user"].email]
    assert [i["email"] for i in members["pending_invites"]] == ["colleague@traqtest.io"]

    looked = client.get("/members/invites/lookup", params={"token": token}, headers=colleague["headers"])
    assert looked.status_code == 200
    assert looked.json()["team_name"] == "Rossi Translations"
    assert looked.json()["role"] == "REVIEWER"
    assert db.query(TeamMember).filter(TeamMember.user_id == colleague["user"].id).count() == 0

    assert client.post("/members/invites/accept", headers=colleague["headers"], json={"token": token}).status_code == 200
    row = db.query(TeamMember).filter(TeamMember.user_id == colleague["user"].id).one()
    assert row.team_id == owner["team"].id and row.role == "REVIEWER"


def test_invite_lookup_and_decline_need_the_addressee(client, db, make_user):
    owner = make_user(plan="PRO")
    colleague = make_user(email="colleague@traqtest.io")
    stranger = make_user()
    _invite(client, owner, "colleague@traqtest.io")
    token = db.query(TeamInvite).one().token

    assert client.get("/members/invites/lookup", params={"token": token}, headers=stranger["headers"]).status_code == 404
    assert client.post("/members/invites/decline", headers=stranger["headers"], json={"token": token}).status_code == 404

    assert client.post("/members/invites/decline", headers=colleague["headers"], json={"token": token}).status_code == 200
    assert db.query(TeamInvite).one().status == "DECLINED"
    assert client.post("/members/invites/accept", headers=colleague["headers"], json={"token": token}).status_code == 404
    assert client.get("/members", headers=owner["headers"]).json()["pending_invites"] == []


def test_inviting_a_current_member_is_refused(client, make_user):
    owner = make_user(plan="PRO")
    mate = make_user(team=owner["team"])
    assert _invite(client, owner, mate["user"].email.upper()).status_code == 400


# Which team an upload goes to


def _upload(client, user, tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", pages=1)
    with open(pdf, "rb") as f:
        return client.post(
            "/projects/upload",
            headers=user["headers"],
            files={"file": ("doc.pdf", f, "application/pdf")},
            data={"source_language": "Italian", "target_language": "English"},
        )


def test_upload_goes_to_the_users_own_team_even_when_they_joined_another(client, db, make_user, tmp_path):
    from app.models.project import TranslationProject

    other = make_user()
    me = make_user(credits=10)
    db.add(TeamMember(team_id=other["team"].id, user_id=me["user"].id, role="ADMIN"))
    db.commit()
    r = _upload(client, me, tmp_path)
    assert r.status_code == 200, r.text
    assert db.query(TranslationProject).one().team_id == me["team"].id


def test_member_of_two_teams_uploads_to_the_one_joined_first(db, make_user):
    from app.dependencies.tenant import active_team

    first = make_user()
    second = make_user()
    member = make_user(team=second["team"])
    db.add(TeamMember(
        team_id=first["team"].id,
        user_id=member["user"].id,
        role="MEMBER",
        created_at=datetime.utcnow() - timedelta(days=30),
    ))
    db.commit()
    for _ in range(5):
        assert active_team(db, member["user"]).id == first["team"].id


# Owner, admin and PM only


@pytest.fixture()
def team_of_roles(make_user, make_project):
    owner = make_user(plan="PRO", credits=100)
    people = {role: make_user(team=owner["team"], role=role) for role in ("ADMIN", "PM", "REVIEWER", "MEMBER")}
    people["OWNER"] = owner
    return owner, people, make_project


@pytest.mark.parametrize("role", ["REVIEWER", "MEMBER"])
def test_lower_roles_cannot_certify_rerun_or_regenerate(client, db, team_of_roles, role):
    owner, people, make_project = team_of_roles
    project = make_project(owner)
    who = people[role]["headers"]

    assert client.post(f"/projects/{project.id}/certify", headers=who).status_code == 403
    assert client.patch(f"/projects/{project.id}/review-status", headers=who, json={"status": "CERTIFIED"}).status_code == 403
    assert client.post(f"/projects/{project.id}/rerun", headers=who, json={}).status_code == 403
    assert client.post(f"/projects/{project.id}/rebuild-with-claude", headers=who).status_code == 403
    db.refresh(project)
    assert (project.review_status or "DRAFT") != "CERTIFIED"
    assert client.get(f"/projects/{project.id}", headers=who).json()["can_lead"] is False

    # Reviewing without certifying stays open to them.
    assert client.patch(f"/projects/{project.id}/review-status", headers=who, json={"status": "IN_REVIEW"}).status_code == 200


@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "PM"])
def test_lead_roles_can_certify(client, db, team_of_roles, role):
    owner, people, make_project = team_of_roles
    project = make_project(owner)
    who = people[role]["headers"]
    assert client.get(f"/projects/{project.id}", headers=who).json()["can_lead"] is True
    r = client.patch(f"/projects/{project.id}/review-status", headers=who, json={"status": "CERTIFIED"})
    assert r.status_code == 200, r.text


def test_pm_can_rerun(client, db, team_of_roles):
    owner, people, make_project = team_of_roles
    project = make_project(owner)
    r = client.post(f"/projects/{project.id}/rerun", headers=people["PM"]["headers"], json={})
    assert r.status_code == 200, r.text


def test_batch_certify_needs_a_lead_role(client, db, team_of_roles):
    owner, people, make_project = team_of_roles
    batch = client.post("/batches", headers=owner["headers"], json={"name": "March"}).json()
    project = make_project(owner)
    project.batch_id = batch["id"]
    db.commit()

    reviewer = people["REVIEWER"]["headers"]
    assert client.get(f"/batches/{batch['id']}", headers=reviewer).json()["can_certify"] is False
    assert client.post(f"/batches/{batch['id']}/review-status", headers=reviewer, json={"status": "CERTIFIED"}).status_code == 403
    assert client.post(f"/batches/{batch['id']}/review-status", headers=reviewer, json={"status": "IN_REVIEW"}).status_code == 200
    r = client.post(f"/batches/{batch['id']}/review-status", headers=people["ADMIN"]["headers"], json={"status": "CERTIFIED"})
    assert r.status_code == 200 and r.json()["updated"] == 1


def test_tm_bulk_delete_needs_a_lead_role(client, db, team_of_roles):
    from app.models.translation_memory import TranslationMemory

    owner, people, _ = team_of_roles
    entry = TranslationMemory(
        team_id=owner["team"].id,
        source_language="it",
        target_language="en",
        source_text="Ciao",
        translated_text="Hello",
        source_hash="0" * 64,
    )
    db.add(entry)
    db.commit()
    body = {"ids": [str(entry.id)]}
    assert client.post("/tm/bulk-delete", headers=people["REVIEWER"]["headers"], json=body).status_code == 403
    assert db.query(TranslationMemory).count() == 1
    r = client.post("/tm/bulk-delete", headers=people["PM"]["headers"], json=body)
    assert r.status_code == 200 and r.json()["deleted"] == 1


# Logins


def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_ten_failures_lock_the_account_with_the_wrong_password_answer(client, db, make_user):
    from app.dependencies import rate_limit

    user = make_user(email="locked@traqtest.io")
    wrong = None
    for _ in range(10):
        rate_limit._buckets.clear()
        wrong = _login(client, "locked@traqtest.io", "nope nope nope")
        assert wrong.status_code == 400
    rate_limit._buckets.clear()
    locked = _login(client, "locked@traqtest.io", PASSWORD)
    assert locked.status_code == wrong.status_code
    assert locked.json() == wrong.json()

    row = db.query(User).filter(User.id == user["user"].id).one()
    db.refresh(row)
    assert row.login_locked_until is not None
    row.login_locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert _login(client, "locked@traqtest.io", PASSWORD).status_code == 200


def test_failures_older_than_the_window_start_over_and_success_resets(client, db, make_user):
    from app.dependencies import rate_limit

    user = make_user(email="slow@traqtest.io")
    row = db.query(User).filter(User.id == user["user"].id).one()
    row.failed_login_count = 9
    row.failed_login_window_start = datetime.utcnow() - timedelta(minutes=16)
    db.commit()
    assert _login(client, "slow@traqtest.io", "nope nope nope").status_code == 400
    db.refresh(row)
    assert row.failed_login_count == 1 and row.login_locked_until is None

    rate_limit._buckets.clear()
    assert _login(client, "slow@traqtest.io", PASSWORD).status_code == 200
    db.refresh(row)
    assert row.failed_login_count == 0 and row.failed_login_window_start is None


def test_access_tokens_last_a_day_by_default():
    from app.config import Settings

    assert Settings.model_fields["access_token_expire_minutes"].default == 1440


# Storage and logs


def test_new_storage_keys_carry_no_file_name(monkeypatch, tmp_path):
    from app.services import s3_service

    calls = []
    monkeypatch.setattr(s3_service.s3_client, "upload_file", lambda *a, **kw: calls.append(a))
    path = tmp_path / "Mario Rossi passport.PDF"
    path.write_bytes(b"%PDF")
    key = s3_service.upload_file_to_s3(path)
    assert key.startswith("uploads/") and key.endswith(".pdf")
    assert "Mario" not in key and "passport" not in key
    assert len(Path(key).stem) == 36


def test_old_keys_are_logged_without_their_file_name():
    from app.services.s3_service import key_ref

    key = "uploads/3f0b6d1e-8a4c-4c8e-9a51-0d2f6f1b7c90_Mario Rossi passport.pdf"
    assert key_ref(key) == "uploads/3f0b6d1e-8a4c-4c8e-9a51-0d2f6f1b7c90"
    assert key_ref(None) == "-"


def test_template_fill_stats_are_logged_as_counts():
    from app.services.template_fill import loggable_stats

    stats = {"calls": 1, "leftovers": ["BIANCHI", "1987"], "notes": "Name changed to ROSSI"}
    assert loggable_stats(stats) == {"calls": 1, "leftovers": 2, "notes": 21}
    assert stats["leftovers"] == ["BIANCHI", "1987"]


def test_sentry_events_lose_bodies_cookies_and_auth():
    from app.main import sentry_scrub

    event = {
        "request": {
            "data": {"text": "certificate of Mario Rossi"},
            "cookies": {"s": "1"},
            "headers": {"Authorization": "Bearer abc", "Accept": "application/json"},
        },
        "user": {"email": "dan@example.com"},
    }
    out = sentry_scrub(event, {})
    assert "data" not in out["request"] and "cookies" not in out["request"]
    assert out["request"]["headers"] == {"Authorization": "[Filtered]", "Accept": "application/json"}
    assert "user" not in out


def test_unused_certification_upload_endpoint_is_gone(client, make_user):
    owner = make_user()
    r = client.post("/settings/upload-certification", headers=owner["headers"], files={"file": ("a.pdf", b"%PDF")})
    assert r.status_code in (404, 405)
