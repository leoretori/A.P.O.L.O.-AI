"""Fachada do banco (SQLite + SQLAlchemy). O DatabaseManager é composto de
mixins por área — modelos em storage_models, métodos em storage_*.
Mantém a API pública: `from src.storage import DatabaseManager` (e modelos)."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session  # noqa: F401 (re-export p/ `from src.storage import Session`)

# Re-exporta modelos/helpers p/ compatibilidade (from src.storage import ...).
from src.storage_models import (  # noqa: F401
    Base, RELEARN_DAYS, _now, _parse_dt,
    Execution, SessionMessage, SessionMeta, Notification, ScheduledStudy,
    LearnedTopic, Reaction, CoderTask, BenchmarkRun, Episode,
)
from src.storage_conversations import ConversationsMixin
from src.storage_learning import LearningMixin
from src.storage_analytics import AnalyticsMixin
from src.storage_episodes import EpisodesMixin

logger = logging.getLogger(__name__)


class DatabaseManager(ConversationsMixin, LearningMixin, AnalyticsMixin, EpisodesMixin):
    def __init__(self, database_url: str = "sqlite:///data/apolo.db"):
        self.engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(self.engine)
        logger.debug(f"Banco conectado: {database_url}")
