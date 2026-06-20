"""Agente de documentação oficial — crawl direto em fontes primárias."""

import logging

from src.web_search import fetch_page_text
from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

# ── Documentação oficial expandida (60+ fontes) ───────────────
DOC_SOURCES: list[tuple[str, str]] = [
    # Python Core
    ("Python asyncio — Coroutines e Tasks",     "https://docs.python.org/3/library/asyncio-task.html"),
    ("Python typing — Type Hints Avançados",    "https://docs.python.org/3/library/typing.html"),
    ("Python dataclasses — Referência",         "https://docs.python.org/3/library/dataclasses.html"),
    ("Python contextlib — Context Managers",    "https://docs.python.org/3/library/contextlib.html"),
    ("Python pathlib — Manipulação de Paths",   "https://docs.python.org/3/library/pathlib.html"),
    ("Python logging — Configuração Avançada",  "https://docs.python.org/3/howto/logging.html"),
    ("Python multiprocessing — Paralelismo",    "https://docs.python.org/3/library/multiprocessing.html"),
    ("Python itertools — Iteradores",           "https://docs.python.org/3/library/itertools.html"),
    ("Python functools — Ferramentas Funcionais","https://docs.python.org/3/library/functools.html"),
    ("Python abc — Classes Abstratas",          "https://docs.python.org/3/library/abc.html"),

    # FastAPI & Web
    ("FastAPI — Primeiros Passos",              "https://fastapi.tiangolo.com/tutorial/first-steps/"),
    ("FastAPI — Dependências",                  "https://fastapi.tiangolo.com/tutorial/dependencies/"),
    ("FastAPI — Segurança OAuth2 JWT",          "https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/"),
    ("FastAPI — Middleware",                    "https://fastapi.tiangolo.com/tutorial/middleware/"),
    ("FastAPI — Background Tasks",              "https://fastapi.tiangolo.com/tutorial/background-tasks/"),
    ("FastAPI — WebSockets",                    "https://fastapi.tiangolo.com/advanced/websockets/"),
    ("FastAPI — Server-Sent Events",            "https://fastapi.tiangolo.com/advanced/custom-response/"),
    ("Starlette — Routing Avançado",            "https://www.starlette.io/routing/"),
    ("httpx — Cliente Async",                   "https://www.python-httpx.org/async/"),

    # Banco de Dados & ORM
    ("SQLAlchemy 2.0 — ORM Quickstart",         "https://docs.sqlalchemy.org/en/20/orm/quickstart.html"),
    ("SQLAlchemy 2.0 — Async ORM",              "https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html"),
    ("SQLAlchemy 2.0 — Core Expressions",       "https://docs.sqlalchemy.org/en/20/core/expression_api.html"),
    ("Alembic — Tutorial de Migrações",         "https://alembic.sqlalchemy.org/en/latest/tutorial.html"),
    ("PostgreSQL — Índices Avançados",          "https://www.postgresql.org/docs/current/indexes.html"),
    ("PostgreSQL — Window Functions",           "https://www.postgresql.org/docs/current/tutorial-window.html"),
    ("PostgreSQL — EXPLAIN ANALYZE",            "https://www.postgresql.org/docs/current/using-explain.html"),
    ("PostgreSQL — Particionamento",            "https://www.postgresql.org/docs/current/ddl-partitioning.html"),
    ("Redis — Tipos de Dados",                  "https://redis.io/docs/latest/develop/data-types/"),
    ("Redis — Pub/Sub Patterns",                "https://redis.io/docs/latest/develop/pubsub/"),

    # Pydantic & Validação
    ("Pydantic v2 — Models",                    "https://docs.pydantic.dev/latest/concepts/models/"),
    ("Pydantic v2 — Validators",                "https://docs.pydantic.dev/latest/concepts/validators/"),
    ("Pydantic v2 — Settings",                  "https://docs.pydantic.dev/latest/concepts/pydantic_settings/"),
    ("Pydantic v2 — Serialização",              "https://docs.pydantic.dev/latest/concepts/serialization/"),

    # Cloud — AWS
    ("AWS Lambda — Python Handler",             "https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html"),
    ("AWS S3 — boto3 Guide",                    "https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-example-creating-buckets.html"),
    ("AWS DynamoDB — Python SDK",               "https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html"),
    ("AWS SQS — Mensageria",                    "https://boto3.amazonaws.com/v1/documentation/api/latest/guide/sqs.html"),
    ("AWS IAM — Roles e Políticas",             "https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html"),
    ("AWS CDK — Python Guide",                  "https://docs.aws.amazon.com/cdk/v2/guide/work-with-cdk-python.html"),

    # Containers & Orquestração
    ("Docker — Multi-stage Builds",             "https://docs.docker.com/build/building/multi-stage/"),
    ("Docker — Compose File Reference",         "https://docs.docker.com/compose/compose-file/"),
    ("Docker — BuildKit Cache",                 "https://docs.docker.com/build/cache/"),
    ("Kubernetes — Deployments",                "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/"),
    ("Kubernetes — Services e Networking",      "https://kubernetes.io/docs/concepts/services-networking/service/"),
    ("Kubernetes — ConfigMaps e Secrets",       "https://kubernetes.io/docs/concepts/configuration/configmap/"),
    ("Kubernetes — HPA — Auto Scaling",         "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/"),
    ("Kubernetes — Ingress Controllers",        "https://kubernetes.io/docs/concepts/services-networking/ingress/"),

    # IaC & CI/CD
    ("Terraform — AWS Provider",                "https://registry.terraform.io/providers/hashicorp/aws/latest/docs"),
    ("Terraform — Módulos",                     "https://developer.hashicorp.com/terraform/language/modules"),
    ("GitHub Actions — Python CI",              "https://docs.github.com/en/actions/use-cases-and-examples/building-and-testing/building-and-testing-python"),
    ("GitHub Actions — Docker Build",           "https://docs.github.com/en/actions/use-cases-and-examples/publishing-packages/publishing-docker-images"),

    # Data Engineering
    ("dbt — Models",                            "https://docs.getdbt.com/docs/build/models"),
    ("dbt — Tests e Validação",                 "https://docs.getdbt.com/docs/build/data-tests"),
    ("dbt — Incremental Models",                "https://docs.getdbt.com/docs/build/incremental-models"),
    ("Apache Kafka — Conceitos",                "https://kafka.apache.org/documentation/#gettingStarted"),
    ("Apache Airflow — DAG Concepts",           "https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html"),

    # Testes & Qualidade
    ("pytest — Fixtures",                       "https://docs.pytest.org/en/stable/how-to/fixtures.html"),
    ("pytest — Parametrize",                    "https://docs.pytest.org/en/stable/how-to/parametrize.html"),
    ("pytest — Mocking",                        "https://docs.pytest.org/en/stable/how-to/monkeypatch.html"),

    # Observabilidade
    ("OpenTelemetry — Python",                  "https://opentelemetry-python.readthedocs.io/en/latest/"),
    ("Prometheus — Métricas Python",            "https://prometheus.github.io/client_python/"),

    # ── Frontend & Web (outros setores) ──
    ("MDN — JavaScript Guide",                  "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide"),
    ("MDN — CSS Flexbox",                       "https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox"),
    ("MDN — Web Accessibility (ARIA)",          "https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA"),
    ("React — Thinking in React",               "https://react.dev/learn/thinking-in-react"),
    ("React — useEffect Reference",             "https://react.dev/reference/react/useEffect"),
    ("TypeScript — Everyday Types",             "https://www.typescriptlang.org/docs/handbook/2/everyday-types.html"),
    ("Tailwind CSS — Utility-First",            "https://tailwindcss.com/docs/utility-first"),

    # ── Linguagens & Sistemas ──
    ("The Rust Book — Ownership",               "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html"),
    ("Go — Effective Go",                       "https://go.dev/doc/effective_go"),
    ("Go — Concurrency Patterns",               "https://go.dev/blog/pipelines"),
    ("MDN — WebAssembly Concepts",              "https://developer.mozilla.org/en-US/docs/WebAssembly/Concepts"),

    # ── Mobile ──
    ("Flutter — State Management",              "https://docs.flutter.dev/data-and-backend/state-mgmt/intro"),
    ("React Native — Architecture",             "https://reactnative.dev/architecture/overview"),

    # ── Machine Learning & Dados ──
    ("PyTorch — Learn the Basics",              "https://pytorch.org/tutorials/beginner/basics/intro.html"),
    ("scikit-learn — Pipelines",                "https://scikit-learn.org/stable/modules/compose.html"),
    ("Hugging Face — Transformers Quicktour",   "https://huggingface.co/docs/transformers/quicktour"),
    ("Polars — User Guide",                     "https://docs.pola.rs/user-guide/"),
]


class DocCrawlerAgent(BaseAgent):
    """Agente que faz crawl direto em documentação oficial."""

    name = "doc_crawler"
    category = "official_doc"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = 0

    async def next_topic(self) -> tuple[str, str]:
        # Avança pelo índice, pulando URLs já estudadas
        attempts = 0
        while attempts < len(DOC_SOURCES):
            topic, url = DOC_SOURCES[self._index % len(DOC_SOURCES)]
            self._index += 1
            if not (self.db and self.db.is_url_studied(url)):
                return topic, url
            attempts += 1
        # Todas já estudadas — reinicia do início (refresh de conhecimento)
        self._index = 0
        topic, url = DOC_SOURCES[0]
        return topic, url

    async def _study(self, topic: str, url: str) -> StudyResult:
        logger.info(f"[doc_crawler] Crawling: {url}")
        try:
            import asyncio
            content = await asyncio.wait_for(fetch_page_text(url), timeout=15.0)
        except Exception as e:
            logger.warning(f"[doc_crawler] Fetch falhou {url}: {e}")
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)

        if not content or len(content) < 100:
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)

        summary = await self.summarize(topic, content)
        return StudyResult(
            ok=True, topic=topic, url=url,
            summary=summary, category=self.category, agent_name=self.name,
        )
