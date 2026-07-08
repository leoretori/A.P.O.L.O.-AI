"""Fachada do banco (SQLite + SQLAlchemy). O DatabaseManager é composto de
mixins por área — modelos em storage_models, métodos em storage_*.
Mantém a API pública: `from src.storage import DatabaseManager` (e modelos)."""

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session  # noqa: F401 (re-export p/ `from src.storage import Session`)

# Re-exporta modelos/helpers p/ compatibilidade (from src.storage import ...).
from src.storage_models import (  # noqa: F401
    Base, RELEARN_DAYS, _now, _parse_dt,
    Execution, SessionMessage, SessionMeta, Notification, ScheduledStudy,
    LearnedTopic, Reaction, CoderTask, BenchmarkRun, Episode, Reminder,
    Permission, ToolAudit, EvalRun,
)
from src.storage_conversations import ConversationsMixin
from src.storage_learning import LearningMixin
from src.storage_analytics import AnalyticsMixin
from src.storage_episodes import EpisodesMixin
from src.storage_reminders import RemindersMixin
from src.storage_permissions import PermissionsMixin
from src.storage_evals import EvalsMixin

logger = logging.getLogger(__name__)


class DatabaseManager(ConversationsMixin, LearningMixin, AnalyticsMixin,
                      EpisodesMixin, RemindersMixin, PermissionsMixin, EvalsMixin):
    def __init__(self, database_url: str = "sqlite:///data/apolo.db"):
        self.engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(self.engine)   # cria TABELAS novas (não altera existentes)
        self._migrate()                          # adiciona COLUNAS novas em tabelas antigas
        logger.debug(f"Banco conectado: {database_url}")

    # Colunas adicionadas depois que a tabela já existia no banco do usuário.
    # `create_all` só cria tabelas — não faz ALTER. SQLite aceita ADD COLUMN.
    _COLUMN_MIGRATIONS = {
        "notifications": [
            ("priority", "INTEGER DEFAULT 1"),
            ("count", "INTEGER DEFAULT 1"),
        ],
        "reactions": [                          # M9 9.2: feedback acionável
            ("reason", "TEXT DEFAULT ''"),
            ("question", "TEXT DEFAULT ''"),
            ("answer", "TEXT DEFAULT ''"),
        ],
    }

    def _migrate(self) -> None:
        insp = inspect(self.engine)
        existing_tables = set(insp.get_table_names())
        with self.engine.begin() as conn:
            for table, cols in self._COLUMN_MIGRATIONS.items():
                if table not in existing_tables:
                    continue
                have = {c["name"] for c in insp.get_columns(table)}
                for name, decl in cols:
                    if name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
                        logger.info(f"[migração] {table}.{name} adicionada")
