import pytest

from app.models.project import TranslationProject
from app.models.segment_comment import SegmentComment
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
    ("get", "/projects/{pid}/segments"),
    ("get", "/projects/{pid}/download"),
    ("get", "/projects/{pid}/rebuild-url"),
    ("get", "/projects/{pid}/preview/rebuild-docx"),
    ("get", "/projects/{pid}/export"),
    ("patch", "/projects/{pid}"),
    ("delete", "/projects/{pid}"),
    ("post", "/projects/{pid}/revise"),
    ("post", "/projects/{pid}/rerun"),
    ("post", "/projects/{pid}/rebuild-with-claude"),
])
def test_other_tenant_gets_404(client, two_tenants, method, path):
    _, bob, project = two_tenants
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    r = getattr(client, method)(path.format(pid=project.id), headers=bob["headers"], **kwargs)
    assert r.status_code == 404, (path, r.status_code, r.text)


def test_segment_edit_blocked_for_other_tenant(client, db, two_tenants):
    _, bob, project = two_tenants
    seg = _segment(db, project)
    r = client.patch(f"/segments/{seg.id}", headers=bob["headers"], json={"translated_text": "pwned"})
    assert r.status_code == 404
    db.refresh(seg)
    assert seg.translated_text != "pwned"


def test_comments_are_tenant_scoped(client, db, two_tenants):
    alice, bob, project = two_tenants
    seg = _segment(db, project)
    assert client.post(f"/segments/{seg.id}/comments", headers=alice["headers"], json={"text": "check"}).status_code == 200
    comment = db.query(SegmentComment).first()

    assert client.get(f"/segments/{seg.id}/comments", headers=bob["headers"]).status_code == 404
    assert client.post(f"/segments/{seg.id}/comments", headers=bob["headers"], json={"text": "x"}).status_code == 404
    assert client.patch(f"/segments/{comment.id}/resolve", headers=bob["headers"]).status_code == 404
    assert client.patch(f"/segments/comments/{comment.id}/reopen", headers=bob["headers"]).status_code == 404
    assert client.delete(f"/segments/comments/{comment.id}", headers=bob["headers"]).status_code == 404
    assert client.get(f"/segments/{seg.id}/comments", headers=alice["headers"]).json()[0]["text"] == "check"


def test_query_string_token_is_not_accepted(client, two_tenants):
    alice, _, project = two_tenants
    token = alice["headers"]["Authorization"].split()[1]
    r = client.get(f"/projects/{project.id}/preview/rebuild-docx?access_token={token}")
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
    assert client.post(f"/projects/{project.id}/build-rebuild-docx", headers=trial["headers"]).status_code == 403


def test_edited_html_is_sanitized(client, db, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    html = '<p onclick="x()">Hi<script>alert(1)</script><img src="http://169.254.169.254/latest"></p>'
    assert client.patch(f"/projects/{project.id}/edited-html", headers=owner["headers"], json={"html": html}).status_code == 200
    db.refresh(project)
    assert "script" not in project.edited_html
    assert "onclick" not in project.edited_html
    assert "169.254" not in project.edited_html
