from logging.config import fileConfig
from sqlalchemy import pool
from alembic import context

config = context.config

import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.database import Base

# Import ALL model modules so autogenerate sees every table.
# Audit medium fix: this list previously had only 5 of the 13+ models,
# which meant `alembic revision --autogenerate` silently missed schema
# changes for the rest.
import app.models.user  # noqa: F401
import app.models.team  # noqa: F401
import app.models.team_member  # noqa: F401
import app.models.job  # noqa: F401
import app.models.credit  # noqa: F401
import app.models.glossary  # noqa: F401
import app.models.project  # noqa: F401
import app.models.translation_segment  # noqa: F401
import app.models.translation_memory  # noqa: F401
import app.models.segment_comment  # noqa: F401
import app.models.stripe_event  # noqa: F401
import app.models.certification  # noqa: F401

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from sqlalchemy import create_engine
    from sqlalchemy import pool
    import os
    from dotenv import load_dotenv
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    database_url = os.getenv("DATABASE_URL")

    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()