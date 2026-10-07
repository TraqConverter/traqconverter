from app.models.certification import Certification
from app.models.document_version import DocumentVersion
from app.models.media_asset import MediaAsset


def test_deleting_an_account_deletes_its_stored_files(client, db, storage, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    db.add(DocumentVersion(project_id=project.id, version=1, s3_key="uploads/version-1.docx", note="v1"))
    db.add(Certification(team_id=owner["team"].id, file_name="cert.docx", file_path="uploads/cert.docx",
                         file_hash="a" * 64, size_bytes=10, kind="SWORN_DECLARATION", uploaded_by=owner["user"].id))
    owner["team"].stamp_s3_key = "uploads/stamp.png"
    db.add(MediaAsset(team_id=owner["team"].id, name="ISO EN", kind="stamp", language="en", s3_key="media/iso_en.png"))
    db.commit()
    source = project.file_path

    res = client.post("/auth/delete-account", headers=owner["headers"],
                      json={"password": "correct horse battery", "confirm": "DELETE"})
    assert res.status_code == 200
    for key in (source, "uploads/version-1.docx", "uploads/cert.docx", "uploads/stamp.png", "media/iso_en.png"):
        assert key in storage["deleted"]


def test_deleting_a_certification_deletes_its_stored_file(client, db, storage, make_user):
    owner = make_user()
    cert = Certification(team_id=owner["team"].id, file_name="cert.pdf", file_path="uploads/cert.pdf",
                         file_hash="b" * 64, size_bytes=10, kind="SWORN_DECLARATION", uploaded_by=owner["user"].id)
    db.add(cert)
    db.commit()
    assert client.delete(f"/certifications/{cert.id}", headers=owner["headers"]).status_code == 200
    assert "uploads/cert.pdf" in storage["deleted"]
