import pytest

from app.models.project import TranslationProject
from app.models.translation_segment import TranslationSegment


@pytest.fixture()
def two_tenants(make_user, make_project):
    alice = make_user()
    bob = make_user()
    project = make_project(alice)
    return alice, bob, project


def _segment(db, project):
    return db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id).first()


@pytest.mark.parametrize("method,path", [
    ("get", "/projects/{pid}"),
    ("get", "/projects/{pid}/download"),
    ("get", "/projects/{pid}/rebuild-url"),
    ("get", "/projects/{pid}/preview/source"),
    ("get", "/projects/{pid}/export"),
    ("patch", "/projects/{pid}"),
    ("delete", "/projects/{pid}"),
    ("post", "/projects/{pid}/rerun"),
    ("post", "/projects/{pid}/rebuild-with-claude"),
])
def test_other_tenant_gets_404(client, two_tenants, method, path):
    _, bob, project = two_tenants
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    r = getattr(client, method)(path.format(pid=project.id), headers=bob["headers"], **kwargs)
    assert r.status_code == 404, (path, r.status_code, r.text)


@pytest.mark.parametrize("method,path", [
    ("post", "/segments/{sid}/retranslate"),
    ("patch", "/segments/{sid}"),
    ("get", "/segments/project/{pid}"),
    ("get", "/segments/{sid}/comments"),
    ("get", "/projects/{pid}/segments"),
    ("patch", "/projects/{pid}/segments/{sid}/approve"),
    ("post", "/projects/{pid}/revise"),
    ("post", "/projects/{pid}/suggest-glossary"),
    ("get", "/projects/{pid}/preview/rebuild"),
    ("get", "/projects/{pid}/preview/rebuild-html"),
    ("get", "/projects/{pid}/preview/rebuild-docx"),
    ("post", "/projects/{pid}/build-rebuild-docx"),
])
def test_unused_ai_and_segment_routes_are_gone(client, db, two_tenants, monkeypatch, method, path):
    from app.services import ai_translation_service, claude_params

    def no_model(*a, **k):
        pytest.fail("a removed route reached the model")

    monkeypatch.setattr(ai_translation_service, "_call_model", no_model)
    monkeypatch.setattr(claude_params, "create_message", no_model)
    alice, _, project = two_tenants
    seg = _segment(db, project)
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    r = getattr(client, method)(path.format(pid=project.id, sid=seg.id), headers=alice["headers"], **kwargs)
    assert r.status_code in (404, 405), (path, r.status_code)


def test_query_string_token_is_not_accepted(client, two_tenants):
    alice, _, project = two_tenants
    token = alice["headers"]["Authorization"].split()[1]
    r = client.get(f"/projects/{project.id}/preview/source?access_token={token}")
    assert r.status_code == 401


def test_team_member_can_view_but_not_delete(client, db, make_user, make_project):
    owner = make_user()
    member = make_user(team=owner["team"], role="MEMBER")
    project = make_project(owner)
    assert client.get(f"/projects/{project.id}", headers=member["headers"]).status_code == 200
    assert client.delete(f"/projects/{project.id}", headers=member["headers"]).status_code == 403


def test_uploader_delete_removes_stored_files(client, db, storage, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    keys = {project.file_path, project.output_file}
    assert client.delete(f"/projects/{project.id}", headers=owner["headers"]).status_code == 200
    assert db.query(TranslationProject).count() == 0
    assert keys <= set(storage["deleted"])


def test_trial_cannot_fetch_full_output(client, make_user, make_project):
    trial = make_user(plan="TRIAL", credits=1)
    project = make_project(trial)
    for path in ("/projects/{pid}/rebuild-url", "/projects/{pid}/download", "/projects/{pid}/export"):
        assert client.get(path.format(pid=project.id), headers=trial["headers"]).status_code == 403, path


def test_edited_html_is_sanitized(client, db, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    html = '<p onclick="x()">Hi<script>alert(1)</script><img src="http://169.254.169.254/latest"></p>'
    assert client.patch(f"/projects/{project.id}/edited-html", headers=owner["headers"], json={"html": html}).status_code == 200
    db.refresh(project)
    assert "script" not in project.edited_html
    assert "onclick" not in project.edited_html
    assert "169.254" not in project.edited_html
