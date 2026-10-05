import pytest

from app.models.project import ProjectStatus


@pytest.fixture()
def mail(monkeypatch):
    """Resend configured, sends captured instead of made."""
    import app.services.email_service as email_service

    sent: list[dict] = []
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(email_service, "send_email", lambda **kw: sent.append(kw) or True)
    return sent


@pytest.fixture()
def team(db, make_user):
    owner = make_user(email="owner@traqtest.io")
    owner["user"].full_name = "Maria Rossi"
    db.commit()
    member = make_user(email="member@traqtest.io", team=owner["team"])
    other = make_user(email="other@traqtest.io", team=owner["team"])
    return {"owner": owner, "member": member, "other": other}


def _assign(client, project, who, assignee):
    return client.patch(
        f"/projects/{project.id}/assign",
        json={"assignee_id": str(assignee["user"].id) if assignee else None},
        headers=who["headers"],
    )


def test_assigning_another_member_sends_one_email(client, team, make_project, mail):
    project = make_project(team["owner"], status=ProjectStatus.COMPLETED, pages=3)
    res = _assign(client, project, team["owner"], team["member"])
    assert res.status_code == 200
    assert res.json()["assignee_id"] == str(team["member"]["user"].id)

    assert len(mail) == 1
    email = mail[0]
    assert email["to"] == "member@traqtest.io"
    assert email["subject"] == "Maria Rossi assigned you a translation"
    link = f"http://localhost:3000/editor/{project.id}"
    assert link in email["html"]
    assert link in email["text_fallback"]
    assert "Open project" in email["html"]
    for fact in ("source.pdf", "Italian → English", "3 pages", "Delivered"):
        assert fact in email["html"]
        assert fact in email["text_fallback"]


def test_assigner_without_a_name_is_shown_by_email(client, db, team, make_project, mail):
    team["member"]["user"].full_name = None
    db.commit()
    project = make_project(team["owner"])
    assert _assign(client, project, team["member"], team["other"]).status_code == 200
    assert [m["subject"] for m in mail] == ["member@traqtest.io assigned you a translation"]
    assert mail[0]["to"] == "other@traqtest.io"


def test_assigning_yourself_sends_nothing(client, team, make_project, mail):
    project = make_project(team["owner"])
    assert _assign(client, project, team["member"], team["member"]).status_code == 200
    assert mail == []


def test_unassigning_sends_nothing(client, team, make_project, mail):
    project = make_project(team["owner"])
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200
    mail.clear()
    res = _assign(client, project, team["owner"], None)
    assert res.status_code == 200
    assert res.json()["assignee_id"] is None
    assert mail == []


def test_reassigning_the_same_person_sends_nothing(client, team, make_project, mail):
    project = make_project(team["owner"])
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200
    assert len(mail) == 1
    assert _assign(client, project, team["other"], team["member"]).status_code == 200
    assert len(mail) == 1


def test_email_not_configured_still_assigns(client, db, team, make_project, monkeypatch, caplog):
    import app.services.email_service as email_service

    posts = []
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(email_service.requests, "post", lambda *a, **kw: posts.append(kw))
    project = make_project(team["owner"])

    res = _assign(client, project, team["owner"], team["member"])
    assert res.status_code == 200
    db.refresh(project)
    assert project.assignee_id == team["member"]["user"].id
    assert posts == []
    assert "email is not configured" in caplog.text


def test_email_failure_never_fails_the_request(client, team, make_project, monkeypatch):
    import app.services.email_service as email_service

    def boom(**kw):
        raise RuntimeError("resend down")

    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(email_service, "send_email", boom)
    project = make_project(team["owner"])
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200


def test_list_assignee_me_returns_only_my_projects(client, team, make_project, mail):
    mine = make_project(team["owner"])
    theirs = make_project(team["owner"])
    unassigned = make_project(team["owner"])
    assert _assign(client, mine, team["owner"], team["member"]).status_code == 200
    assert _assign(client, theirs, team["owner"], team["other"]).status_code == 200

    res = client.get("/projects/", params={"assignee": "me"}, headers=team["member"]["headers"])
    assert res.status_code == 200
    assert [p["id"] for p in res.json()] == [str(mine.id)]

    res = client.get("/projects/", params={"assignee": "unassigned"}, headers=team["member"]["headers"])
    assert [p["id"] for p in res.json()] == [str(unassigned.id)]

    res = client.get("/projects/", headers=team["member"]["headers"])
    assert {p["id"] for p in res.json()} == {str(mine.id), str(theirs.id), str(unassigned.id)}
