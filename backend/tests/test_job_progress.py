"""Staged job progress and batched vision table extraction."""
import json
from types import SimpleNamespace

import pytest

from app.models.project import ProjectStatus
from app.services import claude_authored_rebuild as car
from app.services import claude_params, job_progress
from app.services import translation_processor as tp
from tests.conftest import make_pdf


def test_stage_weights_cover_the_bar_and_cap_below_100():
    assert sum(job_progress.STAGE_WEIGHTS.values()) == 100
    assert job_progress.overall_percent("reading", 0) == 0
    assert job_progress.overall_percent("reading", 0.5) == 22
    assert job_progress.overall_percent("translating", 0) == 45
    assert job_progress.overall_percent("rebuilding", 0) == 55
    assert job_progress.overall_percent("finishing", 0) == 95
    assert job_progress.overall_percent("finishing", 1) == 99
    assert job_progress.overall_percent("nonsense", 1) == 0


def test_report_outside_a_job_is_a_no_op():
    job_progress.report("reading", 0.5, "Reading page 1 of 2")


def test_scope_maps_nested_reports_into_its_slice():
    seen = []
    with job_progress.bind(lambda stage, f, detail: seen.append((stage, round(f, 3), detail))):
        with job_progress.scope(0.5, 1.0, "Rebuilding page 2 of 2"):
            job_progress.report("rebuilding", 0.0, "Rebuilding the layout")
            job_progress.report("rebuilding", 0.5)
    assert seen == [
        ("rebuilding", 0.5, "Rebuilding page 2 of 2"),
        ("rebuilding", 0.75, "Rebuilding page 2 of 2"),
    ]


def test_a_job_moves_through_the_stages_and_only_hits_100_when_done(
    db, client, make_user, make_project, monkeypatch, tmp_path
):
    from app.services import claude_vision_ocr

    owner = make_user()
    project = make_project(owner, status=ProjectStatus.PENDING, pages=3, segments=())
    project.model = "claude-authored"
    db.commit()
    pid = str(project.id)
    pdf = make_pdf(tmp_path / "scan.pdf", pages=3).read_bytes()

    snapshots = []

    def snapshot(label):
        body = client.get(f"/projects/{pid}", headers=owner["headers"]).json()
        snapshots.append((label, body["status"], body["progress_stage"], body["progress_detail"], body["progress_percent"]))

    page_no = iter(range(1, 4))

    def ocr(path):
        snapshot("ocr")
        n = next(page_no)
        # 15 segments per page, so translation runs in three batches.
        return [{"text": f"Riga {n}-{i}", "bbox": [10, 10 + 30 * i, 300, 35 + 30 * i]} for i in range(15)]

    def translate(texts, *a, **kw):
        snapshot("translate")
        return [f"Line {t}" for t in texts]

    def author(**kw):
        for turn in (1, 2):
            job_progress.report("rebuilding", 0.15 + 0.85 * (turn - 1) / 2, "Rebuilding the layout")
            snapshot("rebuild")
        return b"docx"

    def rebuild(**kw):
        open(kw["output_path"], "wb").write(b"docx")
        return kw["output_path"]

    broadcasts = []
    real_broadcast = tp.safe_broadcast
    monkeypatch.setattr(tp, "safe_broadcast", lambda pid_, pct, status, extra=None: broadcasts.append((pct, status, extra)) or real_broadcast(pid_, pct, status, extra))
    monkeypatch.setattr(tp, "download_file_from_s3", lambda key, dest: open(dest, "wb").write(pdf))
    monkeypatch.setattr(claude_vision_ocr, "is_available", lambda: True)
    monkeypatch.setattr(claude_vision_ocr, "ocr_image", ocr)
    monkeypatch.setattr(tp, "translate_batch", translate)
    monkeypatch.setattr(tp, "translate_text", lambda text, *a, **kw: f"Line {text}")
    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: "uploads/out.docx")
    monkeypatch.setattr(car, "author_rebuild_docx", author)

    tp.process_translation_job(pid)

    stages = [s[2] for s in snapshots]
    assert stages[:3] == ["reading"] * 3
    assert [s[3] for s in snapshots[:3]] == ["Reading page 1 of 3", "Reading page 2 of 3", "Reading page 3 of 3"]
    assert stages[3:6] == ["translating"] * 3
    assert stages[6:] == ["rebuilding"] * 2
    percents = [s[4] for s in snapshots]
    assert percents == sorted(percents)
    assert percents[0] == 0 and percents[2] > percents[0]
    assert all(0 < p < 100 for p in percents[1:])
    assert all(s[1] == "PROCESSING" for s in snapshots)

    processing = [b for b in broadcasts if b[1] == "PROCESSING"]
    assert [b[0] for b in processing] == sorted(b[0] for b in processing)
    assert all(b[0] < 100 for b in processing)
    assert [b[2]["stage"] for b in processing][-1] == "finishing"
    assert broadcasts[-1][0] == 100

    done = client.get(f"/projects/{pid}", headers=owner["headers"]).json()
    assert done["status"] == "COMPLETED"
    assert done["progress_percent"] == 100
    assert done["progress_stage"] is None and done["progress_detail"] is None


def test_project_endpoints_expose_the_stage_while_processing(db, client, make_user, make_project):
    owner = make_user()
    project = make_project(owner, status=ProjectStatus.PROCESSING, pages=10)
    project.progress_percent = 30
    project.progress_stage = "reading"
    project.progress_detail = "Reading page 7 of 10"
    db.commit()

    body = client.get(f"/projects/{project.id}", headers=owner["headers"]).json()
    assert body["progress_percent"] == 30
    assert body["progress_stage"] == "reading"
    assert body["progress_detail"] == "Reading page 7 of 10"
    assert body["page_count"] == 10

    row = next(p for p in client.get("/projects/", headers=owner["headers"]).json() if p["id"] == str(project.id))
    assert row["progress"] == 30
    assert row["progress_stage"] == "reading"
    assert row["progress_detail"] == "Reading page 7 of 10"


def test_a_processing_project_never_shows_100(db, client, make_user, make_project):
    owner = make_user()
    project = make_project(owner, status=ProjectStatus.PROCESSING)
    project.progress_percent = 100
    db.commit()
    assert client.get(f"/projects/{project.id}", headers=owner["headers"]).json()["progress_percent"] == 99


# --- vision table extraction in page batches ---------------------------------

PAGE_B64 = 3_500_000


def _reply(tables):
    text = "```json\n" + json.dumps({"tables": tables}) + "\n```"
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=None)


@pytest.fixture()
def big_pages(monkeypatch):
    # Ten scanned pages at ~3.5 MB of base64 each: 35 MB in one request was the production 413.
    images = [chr(ord("a") + i) * PAGE_B64 for i in range(10)]
    monkeypatch.setattr(claude_params, "api_key", lambda: "k")
    monkeypatch.setattr(car, "_render_table_pages", lambda pdf: images)
    return images


def _page_of(image_block, images):
    return images.index(image_block["source"]["data"])


def test_ten_large_pages_are_split_under_the_request_limit(big_pages, monkeypatch):
    calls = []

    def fake(client, **kw):
        content = kw["messages"][0]["content"]
        images = [b for b in content if b["type"] == "image"]
        calls.append([_page_of(b, big_pages) for b in images])
        assert sum(len(b["source"]["data"]) for b in images) <= car.TABLE_BATCH_BYTES
        assert content[-1] == {"type": "text", "text": car._TABLE_EXTRACT_PROMPT}
        return _reply([])

    monkeypatch.setattr(claude_params, "create_message", fake)
    assert car._extract_tables_via_vision(b"%PDF") == []
    assert len(calls) >= 3
    assert sorted(p for c in calls for p in c) == list(range(10))
    for c in calls:
        assert c == list(range(c[0], c[0] + len(c)))


def test_batch_results_merge_in_page_order(big_pages, monkeypatch):
    def fake(client, **kw):
        images = [b for b in kw["messages"][0]["content"] if b["type"] == "image"]
        first = _page_of(images[0], big_pages)
        # Each batch reports its last image first, numbered within the batch.
        return _reply([
            {"page": len(images), "title": f"T{first + len(images)}", "headers": ["A"], "rows": [["x"]]},
            {"page": 1, "title": f"T{first + 1}", "headers": ["A"], "rows": [["y"]]},
        ])

    monkeypatch.setattr(claude_params, "create_message", fake)
    tables = car._extract_tables_via_vision(b"%PDF")
    pages = [t["page"] for t in tables]
    assert pages == sorted(pages)
    assert all(t["title"] == f"T{t['page']}" for t in tables)
    assert pages[0] == 1 and pages[-1] == 10


def test_one_failed_batch_keeps_the_others(big_pages, monkeypatch):
    import anthropic
    import httpx

    def fake(client, **kw):
        images = [b for b in kw["messages"][0]["content"] if b["type"] == "image"]
        first = _page_of(images[0], big_pages)
        if first == 0:
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIStatusError(
                "request_too_large", response=httpx.Response(413, request=request), body=None
            )
        return _reply([{"page": 1, "title": "", "headers": ["A"], "rows": [["v"]]}])

    monkeypatch.setattr(claude_params, "create_message", fake)
    tables = car._extract_tables_via_vision(b"%PDF")
    batches = car._batch_page_images(big_pages)
    assert len(tables) == len(batches) - 1
    assert [t["page"] for t in tables] == [start + 1 for start, _ in batches[1:]]


def test_batches_respect_the_page_cap_and_keep_an_oversized_page_alone():
    small = ["x" * 10] * 20
    assert [len(b) for _, b in car._batch_page_images(small, budget_bytes=10**9, max_pages=8)] == [8, 8, 4]
    huge = ["x" * 50, "y" * 5, "z" * 5]
    assert [(s, len(b)) for s, b in car._batch_page_images(huge, budget_bytes=20)] == [(0, 1), (1, 2)]


def test_real_pdf_pages_render_under_the_image_cap(tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", pages=2).read_bytes()
    images = car._render_table_pages(pdf)
    assert len(images) == 2
    assert all(len(b) < 5_000_000 for b in images)
