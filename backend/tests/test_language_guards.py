"""Auto-detected source already in the target language, and source-language text left in a translation."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.credit import CreditTransaction, CreditWallet
from app.models.glossary import Glossary
from app.models.project import ProjectStatus
from app.services import claude_authored_rebuild as car
from app.services import learning, review_checks, template_fill
from app.services import translation_processor as tp
from app.services.credit_service import CreditService
from tests.test_learning import PROFILE
from tests.test_review import GOOD_TRANSLATION, _checks, _doc, _ids_by_text, fake, page_cache, review_project  # noqa: F401

SOURCE = ["COMUNE DI VALLEVERDE", "Il sindaco certifica che il Sig. ROSSI MARIO è residente in questo comune."]


@pytest.fixture()
def pipeline(db, monkeypatch, make_project):
    calls = {"translate": 0, "rebuild": 0, "author": 0, "fill": 0}

    def translate_batch(texts, *a, **kw):
        calls["translate"] += 1
        return [f"EN {t}" for t in texts]

    def translate_text(text, *a, **kw):
        calls["translate"] += 1
        return f"EN {text}"

    def rebuild(**kw):
        calls["rebuild"] += 1
        Path(kw["output_path"]).write_bytes(b"docx")
        return kw["output_path"]

    def bump(name, value):
        def _f(*a, **kw):
            calls[name] += 1
            return value
        return _f

    monkeypatch.setattr(tp, "download_file_from_s3", lambda key, dest: Path(dest).write_bytes(b"%PDF"))
    monkeypatch.setattr(tp, "extract_segments", lambda path: ("PDF", [SimpleNamespace(text=s, layout={}) for s in SOURCE]))
    monkeypatch.setattr(tp, "translate_batch", translate_batch)
    monkeypatch.setattr(tp, "translate_text", translate_text)
    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: "uploads/out.docx")
    monkeypatch.setattr(car, "author_rebuild_docx", bump("author", b"docx"))
    monkeypatch.setattr(template_fill, "fill_from_template", bump("fill", (b"docx", {})))

    def run(owner, target, detected="Italian", mode="translate", charge=True):
        monkeypatch.setattr(learning, "classify_document", lambda *a, **kw: {**PROFILE, "source_language": detected})
        project = make_project(owner, status=ProjectStatus.PENDING, segments=SOURCE)
        project.source_language = "auto"
        project.target_language = target
        project.mode = mode
        project.model = "claude-authored"
        if charge:
            CreditService.deduct_credits(db, owner["team"].id, 2, reference_id=str(project.id))
        db.commit()
        tp.process_translation_job(str(project.id))
        db.expire_all()
        return project

    return calls, run


def _credits(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one().subscription_credits


def test_auto_source_already_in_target_stops_before_translation_and_refunds_once(db, make_user, pipeline):
    calls, run = pipeline
    owner = make_user(credits=10)
    project = run(owner, "it-IT")

    assert calls == {"translate": 0, "rebuild": 0, "author": 0, "fill": 0}
    assert project.status == ProjectStatus.FAILED
    assert project.failure_reason == (
        "This document is already in Italian. Choose another target language, or create an Editable copy instead."
    )
    assert _credits(db, owner) == 10
    refunds = db.query(CreditTransaction).filter(CreditTransaction.reference_id == f"refund:{project.id}").all()
    assert [r.amount for r in refunds] == [2]

    # A retry of the same job can't refund twice.
    tp.process_translation_job(str(project.id))
    assert _credits(db, owner) == 10
    assert db.query(CreditTransaction).filter(CreditTransaction.reference_id == f"refund:{project.id}").count() == 1
    assert calls["translate"] == calls["rebuild"] == 0


def test_project_api_reports_the_same_language_code(client, db, make_user, pipeline):
    _, run = pipeline
    owner = make_user(credits=10)
    project = run(owner, "it-IT")
    body = client.get(f"/projects/{project.id}", headers=owner["headers"]).json()
    assert body["failure_code"] == "same_language"
    listed = client.get("/projects/", headers=owner["headers"]).json()
    assert listed[0]["failure_code"] == "same_language"


def test_other_target_and_other_files_proceed(db, make_user, pipeline):
    calls, run = pipeline
    owner = make_user(credits=10)
    stopped = run(owner, "it-IT")
    project = run(owner, "en-GB")
    assert stopped.status == ProjectStatus.FAILED
    assert project.status == ProjectStatus.COMPLETED and project.failure_reason is None
    assert calls["translate"] >= 1 and calls["rebuild"] == 1
    assert _credits(db, owner) == 8


def test_unknown_detection_proceeds(db, make_user, pipeline):
    calls, run = pipeline
    owner = make_user(credits=10)
    for detected in ("Unknown", "", "Mixed"):
        project = run(owner, "it-IT", detected=detected, charge=False)
        assert project.status == ProjectStatus.COMPLETED, detected
    assert calls["rebuild"] == 3


def test_editable_copy_is_unaffected(db, make_user, pipeline):
    calls, run = pipeline
    owner = make_user(credits=10)
    project = run(owner, "Italian", mode="dtp")
    assert project.status == ProjectStatus.COMPLETED
    assert calls["rebuild"] == 1 and calls["translate"] == 0
    assert _credits(db, owner) == 8


# Possibly untranslated text

def _possibly(result):
    return [i for i in result["items"] if i["kind"] == "possibly_untranslated"]


def _with(lines):
    return list(GOOD_TRANSLATION) + lines


def test_heading_left_in_italian_is_flagged_with_its_block(client, review_project, fake):
    fake(names={"names": [{"source": "Comune di Valleverde", "kind": "institution",
                           "renderings": ["Comune di Valleverde", "Municipality of Valleverde"]}]})
    owner, project = review_project(translation=_with(["COMUNE DI VALLEVERDE"]), plan="BASIC")
    data, _ = _doc(client, owner, project)
    result = _checks(client, owner, project)
    [item] = _possibly(result)
    assert item["severity"] == "warning"
    assert item["message"] == "Possibly not translated: “COMUNE DI VALLEVERDE”"
    assert item["block_id"] == _ids_by_text(data)["COMUNE DI VALLEVERDE"]
    assert not result["ready"]


def test_names_codes_addresses_and_notations_are_not_flagged(client, review_project, fake):
    fake(names={"names": [{"source": "MARIO ROSSI", "kind": "person", "renderings": ["MARIO ROSSI"]}]})
    lines = ["MARIO ROSSI", "Via Roma 15", "ANA/2026/7781", "[Signature]", "Piazza della Repubblica 3, Valleverde",
             "Stato civile"]
    owner, project = review_project(translation=_with(lines), plan="BASIC")
    # The one Italian line proves the check ran.
    assert [i["message"] for i in _possibly(_checks(client, owner, project))] == ["Possibly not translated: “Stato civile”"]


def test_approved_glossary_target_is_not_flagged(client, db, make_user, review_project, fake):
    fake()
    owner, project = review_project(translation=_with(["COMUNE DI VALLEVERDE"]), plan="PRO")
    db.add(Glossary(team_id=owner["team"].id, source_language="Italian", target_language="English",
                    source_term="Comune di Valleverde", target_term="Comune di Valleverde", origin="manual"))
    db.commit()
    assert _possibly(_checks(client, owner, project)) == []
    owner, project = review_project(translation=_with(["COMUNE DI VALLEVERDE"]), plan="PRO", owner=make_user(plan="PRO"))
    assert len(_possibly(_checks(client, owner, project))) == 1


def test_full_italian_sentence_is_flagged(client, review_project, fake):
    fake()
    sentence = "Il presente certificato è rilasciato su richiesta dell'interessato per gli usi consentiti dalla legge."
    owner, project = review_project(translation=_with([sentence]), plan="BASIC")
    [item] = _possibly(_checks(client, owner, project))
    assert item["message"].startswith("Possibly not translated: “Il presente certificato")


def test_english_sentence_naming_an_italian_office_is_not_flagged(client, review_project, fake):
    fake()
    line = "This certificate is issued by the Comune di Valleverde at the request of the person concerned."
    owner, project = review_project(translation=_with([line, "Registry Office", "Stato civile"]), plan="BASIC")
    assert len(_possibly(_checks(client, owner, project))) == 1


def test_skipped_for_editable_copies(client, db, review_project, fake):
    fake()
    owner, project = review_project(translation=_with(["COMUNE DI VALLEVERDE"]), plan="BASIC")
    project.mode = "dtp"
    db.commit()
    assert _possibly(_checks(client, owner, project)) == []


def test_heuristic_directly():
    lines = {review_checks._norm("Ufficio Tributi")}
    look = lambda t: review_checks._looks_untranslated(t, "it", "en", lines, set())  # noqa: E731
    assert look("COMUNE DI VALLEVERDE")
    assert look("Ufficio anagrafe e stato civile")
    assert not look("MARIO ROSSI")
    assert not look("Municipality of Valleverde")
    assert not look("Leonardo da Vinci")
