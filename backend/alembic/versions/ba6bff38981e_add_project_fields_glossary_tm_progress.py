"""add project fields, glossary, tm, progress

Revision ID: ba6bff38981e
Revises: 96cabd049f95
Create Date: 2026-04-13 20:32:11.388361
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect  # ✅ FIX

revision: str = 'ba6bff38981e'
down_revision: Union[str, Sequence[str], None] = '96cabd049f95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # =====================================================
    # 🔥 GLOSSARY FIX
    # =====================================================
    glossary_columns = [c["name"] for c in inspector.get_columns("glossary")]

    if "team_id" not in glossary_columns:
        op.add_column('glossary', sa.Column('team_id', sa.UUID(), nullable=True))

    # Populate safely (only if column exists)
    if "team_id" in [c["name"] for c in inspector.get_columns("glossary")]:
        op.execute("""
            UPDATE glossary g
            SET team_id = u.team_id
            FROM users u
            WHERE g.user_id = u.id
        """)

        op.alter_column('glossary', 'team_id', nullable=False)

    op.alter_column(
        'glossary',
        'user_id',
        existing_type=sa.UUID(),
        nullable=False
    )

    # Add FK only if not exists
    fks = inspector.get_foreign_keys("glossary")
    fk_names = [fk["name"] for fk in fks]

    if "fk_glossary_team" not in fk_names:
        op.create_foreign_key(
            "fk_glossary_team",
            'glossary',
            'teams',
            ['team_id'],
            ['id']
        )

    # =====================================================
    # SEGMENT COMMENTS
    # =====================================================
    op.alter_column(
        'segment_comments',
        'created_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
        existing_server_default=sa.text('now()')
    )

    # =====================================================
    # TRANSLATION MEMORY
    # =====================================================
    tm_columns = [c["name"] for c in inspector.get_columns("translation_memory")]

    op.alter_column(
        'translation_memory',
        'team_id',
        existing_type=sa.UUID(),
        nullable=False
    )

    fks = inspector.get_foreign_keys("translation_memory")
    fk_names = [fk["name"] for fk in fks]

    if "fk_tm_team" not in fk_names:
        op.create_foreign_key(
            "fk_tm_team",
            'translation_memory',
            'teams',
            ['team_id'],
            ['id']
        )

    if "created_at" in tm_columns:
        op.drop_column('translation_memory', 'created_at')

    # =====================================================
    # TRANSLATION PROJECTS (🔥 FIXED)
    # =====================================================
    project_columns = [c["name"] for c in inspector.get_columns("translation_projects")]

    if "total_segments" not in project_columns:
        op.add_column(
            'translation_projects',
            sa.Column('total_segments', sa.Integer(), nullable=False, server_default="0")
        )

    if "translated_segments" not in project_columns:
        op.add_column(
            'translation_projects',
            sa.Column('translated_segments', sa.Integer(), nullable=False, server_default="0")
        )

    # remove defaults safely
    op.alter_column('translation_projects', 'total_segments', server_default=None)
    op.alter_column('translation_projects', 'translated_segments', server_default=None)

    op.alter_column(
        'translation_projects',
        'team_id',
        existing_type=sa.UUID(),
        nullable=False
    )

    op.alter_column(
        'translation_projects',
        'source_language',
        existing_type=sa.VARCHAR(),
        nullable=False
    )

    op.alter_column(
        'translation_projects',
        'target_language',
        existing_type=sa.VARCHAR(),
        nullable=False
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # =============================
    # PROJECTS (SAFE DROP)
    # =============================
    project_columns = [c["name"] for c in inspector.get_columns("translation_projects")]

    if "translated_segments" in project_columns:
        op.drop_column('translation_projects', 'translated_segments')

    if "total_segments" in project_columns:
        op.drop_column('translation_projects', 'total_segments')

    op.alter_column(
        'translation_projects',
        'team_id',
        existing_type=sa.UUID(),
        nullable=True
    )

    op.alter_column(
        'translation_projects',
        'source_language',
        existing_type=sa.VARCHAR(),
        nullable=True
    )

    op.alter_column(
        'translation_projects',
        'target_language',
        existing_type=sa.VARCHAR(),
        nullable=True
    )

    # =============================
    # TRANSLATION MEMORY
    # =============================
    tm_columns = [c["name"] for c in inspector.get_columns("translation_memory")]

    if "created_at" not in tm_columns:
        op.add_column(
            'translation_memory',
            sa.Column('created_at', postgresql.TIMESTAMP(), nullable=True)
        )

    fks = inspector.get_foreign_keys("translation_memory")
    fk_names = [fk["name"] for fk in fks]

    if "fk_tm_team" in fk_names:
        op.drop_constraint("fk_tm_team", 'translation_memory', type_='foreignkey')

    op.alter_column(
        'translation_memory',
        'team_id',
        existing_type=sa.UUID(),
        nullable=True
    )

    # =============================
    # GLOSSARY
    # =============================
    glossary_columns = [c["name"] for c in inspector.get_columns("glossary")]

    fks = inspector.get_foreign_keys("glossary")
    fk_names = [fk["name"] for fk in fks]

    if "fk_glossary_team" in fk_names:
        op.drop_constraint("fk_glossary_team", 'glossary', type_='foreignkey')

    if "team_id" in glossary_columns:
        op.drop_column('glossary', 'team_id')

    op.alter_column(
        'glossary',
        'user_id',
        existing_type=sa.UUID(),
        nullable=True
    )