"""Regressions from the pipeline and editor audit."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.project import ProjectStatus
from app.services import translation_processor as tp


@pytest.mark.parametrize(
    "name,expected",
    [
        ("contract.pdf", "contract.pdf"),
        ("Contract 1/2.pdf", "2.pdf"),
        ("/etc/evil.pdf", "evil.pdf"),
        ("../../evil.pdf", "evil.pdf"),
        ("..\\..\\evil.pdf", "evil.pdf"),
        ("..", "source"),
        ("", "source"),
        (None, "source"),
    ],
)
def test_local_file_name_stays_inside_the_folder(name, expected):
    assert tp.local_file_name(name) == expected


def test_job_writes_the_source_inside_its_temp_dir(db, make_user, make_project, monkeypatch):
    owner = make_user()
    project = make_project(owner, status=ProjectStatus.PENDING)
    project.file_name = "/../../../../tmp/escaped_by_name.pdf"
    db.commit()
    written = []

    def download(key, dest):
        written.append(Path(dest))
        Path(dest).write_bytes(b"%PDF")

    def rebuild(**kw):
        written.append(Path(kw["output_path"]))
        Path(kw["output_path"]).write_bytes(b"docx")
        return kw["output_path"]

    monkeypatch.setattr(tp, "download_file_from_s3", download)
    monkeypatch.setattr(tp, "extract_segments", lambda path: ("PDF", [SimpleNamespace(text="Ciao", layout={})]))
    monkeypatch.setattr(tp, "translate_batch", lambda texts, *a, **kw: [f"EN {t}" for t in texts])
    monkeypatch.setattr(tp, "translate_text", lambda text, *a, **kw: f"EN {text}")
    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: "uploads/out.docx")
    tp.process_translation_job(str(project.id))

    temp_root = Path(tempfile.gettempdir()).resolve()
    assert len(written) == 2
    for path in written:
        assert path.resolve().parent.parent == temp_root
    assert [p.name for p in written] == ["escaped_by_name.pdf", "translated_escaped_by_name.pdf"]
