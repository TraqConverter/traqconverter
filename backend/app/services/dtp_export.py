"""Export of an editable copy: the edited document alone, with no source pages and no certification."""
from io import BytesIO

from sqlalchemy.orm import Session

from app.models.project import TranslationProject
from app.models.user import User


def render(db: Session, project: TranslationProject, user: User, fmt: str) -> BytesIO:
    from app.routers.document import _initial_builder
    from app.services import document_editor
    from app.services.docx_blocks import strip_blocks
    from app.services.export_service import _convert_docx_to_pdf

    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    data = strip_blocks(data)
    if fmt == "pdf":
        pdf = _convert_docx_to_pdf(data)
        if not pdf:
            raise RuntimeError("PDF conversion is unavailable")
        return BytesIO(pdf)
    return BytesIO(data)
