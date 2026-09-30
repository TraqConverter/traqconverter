"""translation memory: BCP-47 pairs, origin, project link, timestamps, one row per source

Revision ID: d7f3a9c1e5b2
Revises: c3e8a1f5d7b9
Create Date: 2026-09-30 18:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7f3a9c1e5b2'
down_revision: Union[str, Sequence[str], None] = 'c3e8a1f5d7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'translation_memory'


def _columns(bind) -> set[str]:
    return {c['name'] for c in sa.inspect(bind).get_columns(TABLE)}


def _indexes(bind) -> set[str]:
    return {i['name'] for i in sa.inspect(bind).get_indexes(TABLE)}


def cleanup_rows(bind) -> dict:
    """Normalise languages, resolve 'auto', link projects and drop duplicates; safe to run again."""
    from app.services.tm_keys import plan_cleanup

    rows = [
        {**r._mapping, "id": str(r.id), "team_id": str(r.team_id)}
        for r in bind.execute(sa.text(
            "SELECT id, team_id, source_language, target_language, source_text, translated_text, origin, "
            "row_number() OVER (ORDER BY created_at, ctid) AS seq FROM translation_memory"
        ))
    ]
    matches: dict = {}
    for r in bind.execute(sa.text(
        "SELECT DISTINCT tm.id AS tm_id, p.id, p.source_language, p.target_language, "
        "CAST(p.doc_profile AS TEXT) AS doc_profile, p.created_at "
        "FROM translation_memory tm "
        "JOIN translation_projects p ON p.team_id = tm.team_id "
        "JOIN translation_segments s ON s.project_id = p.id AND s.source_text = tm.source_text"
    )):
        m = dict(r._mapping)
        m["id"] = str(m["id"])
        m["doc_profile"] = json.loads(m["doc_profile"]) if m["doc_profile"] else None
        matches.setdefault(str(m.pop("tm_id")), []).append(m)
    plan = plan_cleanup(rows, matches)
    if plan["delete"]:
        bind.execute(sa.text("DELETE FROM translation_memory WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": list(plan["delete"])})
    if plan["update"]:
        bind.execute(
            sa.text(
                "UPDATE translation_memory SET source_language = :source_language, target_language = :target_language, "
                "source_hash = :source_hash, project_id = CAST(:project_id AS uuid) WHERE id = CAST(:id AS uuid)"
            ),
            plan["update"],
        )
    return plan


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind)
    if 'project_id' not in cols:
        op.add_column(TABLE, sa.Column('project_id', sa.UUID(), nullable=True))
        op.create_foreign_key(
            'fk_tm_project', TABLE, 'translation_projects', ['project_id'], ['id'], ondelete='SET NULL'
        )
    if 'origin' not in cols:
        op.add_column(TABLE, sa.Column('origin', sa.String(), nullable=False, server_default='machine'))
    if 'created_at' not in cols:
        op.add_column(TABLE, sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    if 'updated_at' not in cols:
        op.add_column(TABLE, sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    if 'source_hash' not in cols:
        op.add_column(TABLE, sa.Column('source_hash', sa.String(64), nullable=True))

    cleanup_rows(bind)

    op.alter_column(TABLE, 'source_hash', nullable=False)
    indexes = _indexes(bind)
    if 'idx_tm_lookup' in indexes:
        # Replaced by the hash key: a btree over raw text breaks on long sources.
        op.drop_index('idx_tm_lookup', table_name=TABLE)
    if 'uq_tm_key' not in indexes:
        op.create_index('uq_tm_key', TABLE, ['team_id', 'source_language', 'target_language', 'source_hash'], unique=True)
    if 'ix_translation_memory_project_id' not in indexes:
        op.create_index('ix_translation_memory_project_id', TABLE, ['project_id'])


def downgrade() -> None:
    # Duplicates removed on upgrade are not restored.
    op.drop_index('ix_translation_memory_project_id', table_name=TABLE)
    op.drop_index('uq_tm_key', table_name=TABLE)
    op.create_index('idx_tm_lookup', TABLE, ['team_id', 'source_language', 'target_language', 'source_text'], unique=False)
    op.drop_constraint('fk_tm_project', TABLE, type_='foreignkey')
    for col in ('source_hash', 'updated_at', 'created_at', 'origin', 'project_id'):
        op.drop_column(TABLE, col)
