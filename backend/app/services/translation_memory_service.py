from sqlalchemy.orm import Session
from app.models.translation_memory import TranslationMemory


# =========================================
# GET TM ENTRIES (OPTIONAL FILTER 🔥 FIX)
# =========================================
def get_tm_entries(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str | None = None,   # ✅ FIX: optional filter
):
    query = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language
    )

    # ✅ OPTIONAL EXACT MATCH FILTER
    if source_text:
        query = query.filter(
            TranslationMemory.source_text == source_text
        )

    return query.all()


# =========================================
# FIND EXACT MATCH
# =========================================
def find_tm_match(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str
):
    entry = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language,
        TranslationMemory.source_text == source_text
    ).first()

    if entry:
        return entry.translated_text

    return None


# PostgreSQL btree index entries cap at ~2700 bytes. Long Italian
# tax-form paragraphs (6kB+) blow this cap and crash the insert. TM
# is designed for sentence-sized reuse anyway — anything longer than
# ~1500 chars adds no practical reuse value and risks indexing errors,
# so we skip storing entries above this threshold.
_TM_MAX_SOURCE_LEN = 1500


# =========================================
# STORE ENTRY
# =========================================
def store_tm_entry(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str
):
    """Persist a translation pair to the TM table.

    Returns None when the entry was skipped (too long for the btree
    index, or empty). Rolls back the session on any other failure so
    the caller's outer transaction can keep going — TM is best-effort
    metadata and must never crash the parent translation job.
    """
    if not source_text or not translated_text:
        return None
    if len(source_text) > _TM_MAX_SOURCE_LEN:
        # Caller logs the skip; we just return.
        return None

    entry = TranslationMemory(
        team_id=team_id,
        source_language=source_language,
        target_language=target_language,
        source_text=source_text,
        translated_text=translated_text,
    )

    try:
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    except Exception:
        # Critical: clear the failed transaction so the caller can keep
        # using the session. Without this, every subsequent query raises
        # PendingRollbackError until the session is rebuilt.
        try:
            db.rollback()
        except Exception:
            pass
        raise