"""Mini-agentes especializados de aprendizado autônomo do A.P.O.L.O."""

from .base import BaseAgent
from .doc_agent import DocCrawlerAgent
from .search_agent import WebSearchAgent
from .trend_agent import TrendAgent
from .synthesis_agent import SynthesisAgent
from .github_agent import GitHubAgent
from .encyclopedia_agent import EncyclopediaAgent
from .book_agent import BookAgent

__all__ = [
    "BaseAgent",
    "DocCrawlerAgent",
    "WebSearchAgent",
    "TrendAgent",
    "SynthesisAgent",
    "GitHubAgent",
    "EncyclopediaAgent",
    "BookAgent",
]
