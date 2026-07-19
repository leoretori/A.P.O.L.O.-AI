"""Universo de estudo do A.P.O.L.O. — organizado por SETOR.

Antes ele afundava num só assunto (backend Python + IA). Aqui os tópicos são
agrupados por setor e o rodízio percorre um setor diferente a cada item
(round-robin via `interleave`), então ele estuda em LEQUE: frontend, mobile, ML,
sistemas, segurança, jogos, blockchain... e também conhecimento geral (ciência,
finanças, produtividade, comunicação). Para ampliar o alcance, basta acrescentar
setores ou itens — o rodízio se ajusta sozinho.

Idioma: as queries ficam em inglês (mais conteúdo na web); o resumo sai em PT-BR.
"""

import os
import re
from functools import lru_cache
from itertools import zip_longest

# Saudação / agradecimento / despedida curtos — o A.P.O.L.O. responde direto,
# SEM disparar busca na web nem marcar lacuna de conhecimento. Antes um "oi"
# fazia uma pesquisa web inteira (~10s até a 1ª palavra) e ainda salvava um
# "Auto-pesquisa: oi" na base. Âncora ^…$ = a mensagem TODA é a saudação; uma
# pergunta de verdade ("oi, o que é X?") não casa e segue o fluxo normal.
_SMALLTALK_RE = re.compile(
    r"^(oi+|ol[áa]+|al[óo]|opa|e+\s*a[íi]|ea[êe]|hey+|hi+|hello|hol[áa]|"
    r"bom dia|boa tarde|boa noite|tudo (bem|bom|certo|jóia|joia)|de boa|"
    r"como (vai|voc[êe]|est[áa]|voc[êe]s)|beleza|blz|valeu|vlw|"
    r"obrigad[oa]|obg|brigad[oa]|agradeço|thanks|thank you|thx|"
    r"ok+|okay|tá|ta|tchau|falou|flw|at[ée] (mais|logo)|bye)"
    r"[\s,!.?]*$",
    re.IGNORECASE,
)


def is_smalltalk(text: str) -> bool:
    """True p/ saudação/agradecimento/despedida curtos — dispensa RAG-gap + web
    (responder direto é mais rápido e não polui a base de conhecimento)."""
    t = (text or "").strip()
    return len(t) <= 40 and bool(_SMALLTALK_RE.match(t))

# ════════════════ ENGENHARIA DE SOFTWARE ════════════════
TECH_SECTORS: dict[str, list[str]] = {
    "backend_apis": [
        "Python async await best practices production",
        "FastAPI dependency injection advanced patterns",
        "REST API versioning and pagination strategies",
        "gRPC vs REST vs GraphQL tradeoffs",
        "idempotency keys and retries in APIs",
        "rate limiting token bucket algorithm implementation",
        "background jobs queues Celery RQ patterns",
        "webhook design delivery reliability best practices",
    ],
    "frontend_web": [
        "React server components vs client components 2024",
        "JavaScript event loop microtasks macrotasks explained",
        "CSS flexbox vs grid when to use each",
        "TypeScript generics and utility types deep dive",
        "web performance Core Web Vitals optimization",
        "web accessibility WCAG ARIA practical guide",
        "state management Redux vs Zustand vs signals",
        "Vite bundling and code splitting explained",
    ],
    "mobile": [
        "React Native new architecture Fabric Turbo Modules",
        "Flutter state management Riverpod Bloc comparison",
        "Swift concurrency async await actors iOS",
        "Kotlin coroutines Android best practices",
        "mobile app offline first sync strategies",
        "push notifications architecture iOS Android",
        "mobile app performance profiling battery usage",
    ],
    "data_ml": [
        "pandas vs Polars performance large datasets",
        "scikit-learn pipeline feature engineering best practices",
        "PyTorch training loop mixed precision explained",
        "transformer architecture attention mechanism explained",
        "RAG retrieval augmented generation evaluation metrics",
        "MLOps model deployment monitoring drift detection",
        "feature store concept and tools 2024",
        "time series forecasting models comparison",
    ],
    "systems_languages": [
        "Rust ownership borrowing lifetimes explained",
        "Go goroutines channels concurrency patterns",
        "C++ move semantics and RAII explained",
        "memory management stack vs heap garbage collection",
        "lock-free data structures atomics explained",
        "compiler design lexer parser AST basics",
        "WebAssembly use cases and performance 2024",
    ],
    "devops_cloud": [
        "Kubernetes autoscaling HPA VPA explained",
        "Docker multi-stage build image size optimization",
        "Terraform modules and remote state best practices",
        "GitHub Actions reusable workflows matrix builds",
        "observability metrics logs traces OpenTelemetry",
        "blue green vs canary deployment strategies",
        "infrastructure cost optimization FinOps practices",
    ],
    "databases": [
        "PostgreSQL EXPLAIN ANALYZE query optimization",
        "database indexing B-tree vs hash vs GIN",
        "SQL window functions practical examples",
        "Redis caching invalidation strategies",
        "ACID vs BASE consistency models explained",
        "database sharding and partitioning strategies",
        "vector database comparison pgvector Qdrant Weaviate",
    ],
    "security": [
        "OWASP Top 10 web vulnerabilities explained 2024",
        "JWT vs session authentication tradeoffs",
        "OAuth2 and OpenID Connect flows explained",
        "SQL injection and XSS prevention techniques",
        "TLS handshake and certificate chain explained",
        "secrets management Vault and rotation",
        "supply chain security SBOM dependency scanning",
        "threat modeling STRIDE methodology",
    ],
    "ai_agents": [  # missão A.P.O.L.O. — autonomia e automelhoria
        "autonomous AI agent architecture self-improving",
        "ReAct reasoning acting loop agent implementation",
        "LLM agent long-term memory architectures",
        "multi-agent orchestration LangGraph CrewAI 2024",
        "LLM self-reflection and self-correction techniques",
        "tool use function calling agent patterns",
        "agent planning and goal decomposition",
        "local LLM inference optimization quantization",
    ],
    "game_dev": [
        "game loop fixed timestep explained",
        "entity component system ECS architecture",
        "Unity vs Godot vs Unreal comparison 2024",
        "game physics collision detection basics",
        "procedural generation algorithms games",
        "shader programming basics GLSL explained",
    ],
    "blockchain_web3": [
        "blockchain consensus proof of stake explained",
        "smart contract Solidity security pitfalls",
        "EVM how Ethereum executes transactions",
        "zero knowledge proofs zk-SNARKs explained",
        "decentralized storage IPFS explained",
    ],
    "cs_fundamentals": [
        "big O notation algorithm complexity explained",
        "data structures hash map vs tree tradeoffs",
        "distributed systems CAP theorem explained",
        "consensus algorithms Raft Paxos explained",
        "TCP IP networking model explained",
        "operating system processes threads scheduling",
        "dynamic programming patterns explained",
    ],
    "data_engineering": [
        "ETL vs ELT data pipeline design",
        "data warehouse star schema dimensional modeling",
        "data lakehouse architecture Delta Iceberg",
        "streaming vs batch processing tradeoffs",
        "data orchestration Airflow Dagster Prefect",
        "data quality and observability pipelines",
        "change data capture CDC explained",
    ],
    "sre_reliability": [
        "SRE SLO SLI error budget explained",
        "incident response and blameless postmortems",
        "chaos engineering principles explained",
        "on-call best practices and alert fatigue",
        "capacity planning and load testing",
        "circuit breaker retry backoff patterns",
    ],
    "embedded_iot": [
        "embedded systems C firmware fundamentals",
        "ESP32 Arduino IoT project tutorial",
        "RTOS task scheduling FreeRTOS explained",
        "MQTT protocol IoT messaging explained",
        "low power embedded design techniques",
        "I2C SPI UART serial protocols explained",
    ],
    "graphics_xr": [
        "computer graphics rendering pipeline explained",
        "ray tracing vs rasterization explained",
        "WebGL and Three.js fundamentals",
        "AR and VR development fundamentals",
        "GPU compute shaders explained",
        "3D math vectors matrices quaternions",
    ],
    "networking_protocols": [
        "TCP vs UDP differences explained",
        "HTTP/2 and HTTP/3 QUIC explained",
        "how DNS works",
        "TLS handshake explained",
        "load balancing strategies explained",
        "VPNs and proxies explained",
    ],
    "testing_qa": [
        "unit vs integration vs e2e testing",
        "test driven development TDD explained",
        "property based testing explained",
        "mocking and test doubles explained",
        "CI test automation strategies",
        "what code coverage really means",
    ],
    "quantum_computing": [
        "qubits and superposition explained",
        "quantum entanglement explained",
        "Shor's algorithm explained",
        "quantum gates and circuits explained",
        "quantum error correction basics",
        "quantum supremacy explained",
    ],
    "robotics_automation": [
        "how robots sense and actuate",
        "ROS robot operating system basics",
        "inverse kinematics explained",
        "PID control explained",
        "computer vision for robotics",
        "industrial automation PLC basics",
    ],
}

# ════════════════ CONHECIMENTO GERAL (JARVIS amplo) ════════════════
GENERAL_SECTORS: dict[str, list[str]] = {
    "science": [
        "how quantum computing works explained simply",
        "CRISPR gene editing how it works",
        "how the immune system fights infection",
        "black holes and general relativity explained",
        "climate change mechanisms and feedback loops",
        "how mRNA vaccines work",
    ],
    "finance_economics": [
        "compound interest and investing fundamentals",
        "how inflation and interest rates work",
        "index funds vs active investing explained",
        "personal finance budgeting frameworks",
        "how startups raise venture capital rounds",
        "behavioral economics cognitive biases money",
    ],
    "productivity_learning": [
        "spaced repetition and active recall learning",
        "deep work and focus techniques",
        "Zettelkasten note taking method explained",
        "habit formation science cues rewards",
        "time management frameworks GTD timeboxing",
        "Feynman technique learning hard concepts",
    ],
    "communication_languages": [
        "principles of clear technical writing",
        "storytelling structure for presentations",
        "negotiation tactics principled negotiation",
        "how to learn a language fast methods",
        "giving and receiving feedback effectively",
    ],
    "design_ux": [
        "design principles contrast hierarchy alignment",
        "color theory for interfaces explained",
        "usability heuristics Nielsen explained",
        "typography fundamentals for screens",
        "design systems and component libraries",
    ],
    "business_product": [
        "product management prioritization frameworks RICE",
        "lean startup MVP build measure learn",
        "go to market strategy fundamentals",
        "metrics that matter SaaS retention churn",
        "OKRs goal setting framework explained",
    ],
    "health_mind": [
        "sleep science circadian rhythm explained",
        "how exercise affects the brain",
        "nutrition fundamentals macros and micros",
        "stress cortisol and the nervous system",
        "neuroplasticity how the brain rewires",
    ],
    "history_philosophy": [
        "history of the internet and the web",
        "stoicism core ideas practical philosophy",
        "scientific method and Karl Popper falsifiability",
        "industrial revolution causes and effects",
        "game theory prisoner dilemma explained",
    ],
    "mathematics": [
        "linear algebra vectors and matrices intuition",
        "calculus derivatives and integrals intuition",
        "probability and statistics fundamentals",
        "discrete math logic and proofs basics",
        "Bayesian thinking and inference explained",
        "graph theory fundamentals explained",
    ],
    "career_growth": [
        "system design interview framework",
        "coding interview preparation strategy",
        "software engineer career growth senior to staff",
        "engineering leadership fundamentals",
        "salary negotiation for tech roles",
        "building a personal brand as a developer",
    ],
    "law_compliance": [
        "LGPD lei geral de proteção de dados resumo",
        "GDPR compliance basics explained",
        "open source software licensing explained",
        "intellectual property patents and copyright basics",
        "privacy by design principles",
        "data retention and consent management",
    ],
    "arts_creativity": [
        "music theory fundamentals scales and chords",
        "creative writing storytelling techniques",
        "photography composition fundamentals",
        "design thinking process explained",
        "creativity and brainstorming techniques",
        "color and visual composition principles",
    ],
    "medicine_health": [
        "how the human immune system works",
        "cardiovascular system explained",
        "how common medications work",
        "antibiotics and antibiotic resistance",
        "human anatomy systems overview",
        "how vaccines train the immune system",
    ],
    "psychology": [
        "cognitive biases explained",
        "attachment theory in relationships",
        "how human memory works",
        "motivation and behavior psychology",
        "emotional intelligence explained",
        "cognitive behavioral therapy basics",
    ],
    "education_pedagogy": [
        "how people learn cognitive science",
        "effective teaching methods explained",
        "Bloom's taxonomy explained",
        "retrieval practice and spaced learning",
        "Montessori vs traditional education",
        "designing a curriculum fundamentals",
    ],
    "environment_sustainability": [
        "how solar panels work",
        "renewable energy sources compared",
        "carbon footprint explained",
        "circular economy explained",
        "biodiversity and ecosystems explained",
        "climate change causes and solutions",
    ],
    "cooking_nutrition": [
        "macronutrients and micronutrients explained",
        "Maillard reaction cooking science",
        "fermentation basics food science",
        "balanced diet fundamentals",
        "cooking techniques braising and roasting",
        "food safety and storage basics",
    ],
    "space_astronomy": [
        "how stars form and die",
        "the solar system overview",
        "how rockets reach orbit",
        "the Big Bang theory explained",
        "exoplanets and the search for life",
        "galaxies and the structure of the universe",
    ],
    "geography_geopolitics": [
        "plate tectonics explained",
        "how ocean currents shape climate",
        "world geopolitics power dynamics",
        "major biomes of the world",
        "how map projections work",
        "rivers and the water cycle",
    ],
    "marketing_sales": [
        "marketing funnel AIDA explained",
        "positioning and branding fundamentals",
        "consumer psychology in marketing",
        "SEO and content marketing basics",
        "consultative selling techniques",
        "pricing strategies explained",
    ],
    "sports_fitness": [
        "strength training fundamentals",
        "how muscles grow hypertrophy",
        "cardio vs resistance training",
        "sports nutrition basics",
        "injury prevention and recovery",
        "periodization in training",
    ],
    "engineering_physical": [
        "how bridges bear structural load",
        "internal combustion engine explained",
        "electrical circuits fundamentals",
        "how electric motors work",
        "laws of thermodynamics explained",
        "materials science strength and fatigue",
    ],
    "investing_markets": [
        "how the stock market works",
        "value vs growth investing explained",
        "ETFs vs mutual funds explained",
        "price to earnings ratio explained",
        "diversification and asset allocation",
        "dividends and compounding explained",
    ],
    "crypto_finance": [
        "how Bitcoin works as money",
        "DeFi decentralized finance explained",
        "stablecoins explained",
        "crypto wallets and custody explained",
        "staking and yield farming explained",
        "tokenomics fundamentals explained",
    ],
    "accounting_tax": [
        "balance sheet vs income statement",
        "cash flow statement explained",
        "double entry bookkeeping basics",
        "depreciation and amortization explained",
        "tax brackets and deductions explained",
        "accrual vs cash accounting",
    ],
    "macroeconomics": [
        "how central banks set interest rates",
        "GDP inflation and unemployment explained",
        "monetary vs fiscal policy",
        "supply and demand explained",
        "exchange rates explained",
        "business cycles and recessions explained",
    ],
    "pharmacology": [
        "how drugs are absorbed and metabolized",
        "pharmacokinetics vs pharmacodynamics",
        "drug interactions explained",
        "how painkillers work",
        "how antidepressants work",
        "clinical trials and drug development",
    ],
    "public_health": [
        "epidemiology basics explained",
        "how diseases spread R0 explained",
        "vaccination and herd immunity",
        "public health interventions explained",
        "health surveillance and data",
        "social determinants of health",
    ],
    "biotech_genomics": [
        "how CRISPR gene editing works",
        "DNA sequencing explained",
        "mRNA technology explained",
        "stem cells explained",
        "synthetic biology basics",
        "genetic inheritance explained",
    ],
    "politics_government": [
        "how democracies and elections work",
        "separation of powers explained",
        "political ideologies compared",
        "how laws are made",
        "international relations basics",
        "public policy fundamentals",
    ],
    "languages_learning": [
        "how to learn a language effectively",
        "comprehensible input method explained",
        "spaced repetition for vocabulary",
        "phonetics and pronunciation basics",
        "language families explained",
        "bilingualism and the brain",
    ],
    "agriculture_food": [
        "how modern agriculture works",
        "crop rotation and soil health",
        "irrigation methods explained",
        "sustainable farming practices",
        "the food supply chain explained",
        "hydroponics and vertical farming",
    ],
}

# Conjunto completo de setores (tech + geral).
ALL_SECTORS: dict[str, list[str]] = {**TECH_SECTORS, **GENERAL_SECTORS}


def interleave(sectors: dict[str, list[str]] | None = None) -> list[str]:
    """Achata os setores em RODÍZIO: 1º item de cada setor, depois 2º de cada...

    Assim itens consecutivos vêm de setores diferentes — o A.P.O.L.O. estuda em
    leque em vez de afundar num assunto só."""
    data = sectors if sectors is not None else ALL_SECTORS
    out: list[str] = []
    for row in zip_longest(*data.values()):
        out.extend(item for item in row if item)
    return out


# Lista plana, intercalada por setor — usada pelo WebSearchAgent.
ALL_TOPICS: list[str] = interleave()

# Mapa exato tópico → setor (os 129 tópicos do WebSearch caem certinho aqui).
TOPIC_SECTOR: dict[str, str] = {
    topic: sector for sector, topics in ALL_SECTORS.items() for topic in topics
}

# Rótulo legível + emoji por setor (usado no painel "Mente do A.P.O.L.O.").
SECTOR_LABELS: dict[str, str] = {
    "backend_apis": "⚙️ Backend & APIs",
    "frontend_web": "🎨 Frontend & Web",
    "mobile": "📱 Mobile",
    "data_ml": "🤖 Data & ML",
    "systems_languages": "🦀 Sistemas & Linguagens",
    "devops_cloud": "☁️ DevOps & Cloud",
    "databases": "🗄️ Bancos de Dados",
    "security": "🔐 Segurança",
    "ai_agents": "🧠 Agentes de IA",
    "game_dev": "🎮 Game Dev",
    "blockchain_web3": "⛓️ Blockchain & Web3",
    "cs_fundamentals": "📐 Fundamentos de CS",
    "science": "🔬 Ciência",
    "finance_economics": "💰 Finanças & Economia",
    "productivity_learning": "⏱️ Produtividade",
    "communication_languages": "🗣️ Comunicação & Idiomas",
    "design_ux": "✏️ Design & UX",
    "business_product": "📈 Negócios & Produto",
    "health_mind": "🧬 Saúde & Mente",
    "history_philosophy": "📜 História & Filosofia",
    "data_engineering": "🛠️ Data Engineering",
    "sre_reliability": "🚨 SRE & Confiabilidade",
    "embedded_iot": "🔌 Embarcados & IoT",
    "graphics_xr": "🕶️ Gráficos & XR",
    "mathematics": "➗ Matemática",
    "career_growth": "🚀 Carreira",
    "law_compliance": "⚖️ Direito & Compliance",
    "arts_creativity": "🎭 Artes & Criatividade",
    "medicine_health": "🩺 Medicina & Saúde",
    "psychology": "💭 Psicologia",
    "education_pedagogy": "🎓 Educação",
    "environment_sustainability": "🌱 Meio Ambiente",
    "cooking_nutrition": "🍳 Culinária & Nutrição",
    "space_astronomy": "🪐 Astronomia",
    "geography_geopolitics": "🗺️ Geografia & Geopolítica",
    "marketing_sales": "📣 Marketing & Vendas",
    "sports_fitness": "🏋️ Esportes & Fitness",
    "engineering_physical": "🏗️ Engenharia (Física)",
    "networking_protocols": "🛰️ Redes & Protocolos",
    "testing_qa": "🧪 Testes & QA",
    "quantum_computing": "⚛️ Computação Quântica",
    "robotics_automation": "🦾 Robótica & Automação",
    "investing_markets": "💹 Investimentos & Mercado",
    "crypto_finance": "🪙 Cripto & DeFi",
    "accounting_tax": "🧾 Contabilidade & Impostos",
    "macroeconomics": "🏦 Macroeconomia",
    "pharmacology": "💊 Farmacologia",
    "public_health": "🏥 Saúde Pública",
    "biotech_genomics": "🧫 Biotecnologia & Genômica",
    "politics_government": "🏛️ Política & Governo",
    "languages_learning": "🗨️ Idiomas",
    "agriculture_food": "🌾 Agricultura & Alimentos",
    "outros": "📦 Outros",
}

# Palavras-chave por setor — classificam tópicos que NÃO estão no mapa exato
# (docs, trends, GitHub, perguntas do usuário). Ordem importa pouco; pega o maior score.
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "frontend_web": ["react", "css", "javascript", "typescript", "frontend", "vue", "angular", "tailwind", "vite", "html", "starlette", "htmx", "svelte"],
    "backend_apis": ["fastapi", "api", "rest", "grpc", "graphql", "endpoint", "webhook", "django", "flask", "pydantic", "backend", "openapi", "asyncio", "typing", "dataclass", "contextlib", "pathlib", "itertools", "functools", "multiprocessing", "pytest", "uvicorn", "celery"],
    "mobile": ["android", "ios", "flutter", "react native", "swift", "kotlin", "mobile", "compose"],
    "data_ml": ["pandas", "polars", "pytorch", "tensorflow", "scikit", "machine learning", "embedding", "transformer", "dataframe", "numpy", "dbt", "airflow", "spark", "kafka", "analytics", "hugging face"],
    "systems_languages": ["rust", "golang", "c++", "wasm", "webassembly", "compiler", "concurrency", "zig", "goroutine", "ownership", "effective go"],
    "devops_cloud": ["kubernetes", "docker", "terraform", "aws", "gcp", "azure", "cloud", "ci/cd", "github actions", "deployment", "helm", "serverless", "lambda", "ansible", "argocd", "opentelemetry", "prometheus", "observability", "tracing", "grafana", "continuous integration", "continuous delivery", "continuous deployment", "infrastructure as code"],
    "databases": ["postgres", "sql", "redis", "mongodb", "database", "index", "sqlalchemy", "clickhouse", "timescale", "elasticsearch", "pgvector", "query optimization", "acid transaction", "acid properties", "transaction isolation", "sharding", "replication", "normalization", "b-tree"],
    "security": ["security", "owasp", "jwt", "oauth", "encryption", "vulnerab", "injection", "tls", "passkey", "cryptograph", "secrets", "zero trust", "supply chain"],
    "ai_agents": ["agent", "llm", "autonomous", "langchain", "langgraph", "ollama", "prompt", "self-improv", "crewai", "autogen", "rag", "self-reflection", "function calling", "jarvis", "meta-learning", "rlhf"],
    "game_dev": ["game", "unity", "godot", "unreal", "shader", "ecs", "collision", "procedural generation"],
    "blockchain_web3": ["blockchain", "ethereum", "solidity", "smart contract", "web3", "zk-", "rollup", "consensus proof"],
    "cs_fundamentals": ["algorithm", "data structure", "big o", "distributed system", "cap theorem", "raft", "paxos", "tcp", "networking", "operating system", "dynamic programming"],
    "science": ["quantum", "crispr", "immune", "black hole", "climate", "vaccine", "physics", "biology", "relativity", "mrna"],
    "finance_economics": ["finance", "investing", "inflation", "economic", "venture capital", "budget", "interest rate", "index fund", "compound interest"],
    "productivity_learning": ["productivity", "spaced repetition", "habit", "note taking", "zettelkasten", "deep work", "time management", "feynman", "learning method"],
    "communication_languages": ["writing", "storytelling", "negotiation", "language fast", "feedback", "communication", "presentation"],
    "design_ux": ["design", "ux", "color theory", "usability", "typography", "interface", "heuristic"],
    "business_product": ["product management", "startup", "go to market", "okr", "saas", "retention", "churn", "mvp", "prioritization"],
    "health_mind": ["sleep", "brain", "nutrition", "stress", "exercise", "neuroplastic", "cortisol", "circadian"],
    "history_philosophy": ["history", "stoicism", "philosophy", "scientific method", "game theory", "industrial revolution", "falsifiability"],
    "data_engineering": ["etl", "elt", "data warehouse", "data lake", "lakehouse", "data pipeline", "star schema", "dimensional modeling", "change data capture", "data orchestration"],
    "sre_reliability": ["sre", "slo", "sli", "error budget", "incident", "postmortem", "chaos engineering", "on-call", "reliability", "capacity planning", "load testing"],
    "embedded_iot": ["embedded", "firmware", "microcontroller", "arduino", "esp32", "rtos", "freertos", "mqtt", "iot", "i2c", "uart"],
    "graphics_xr": ["computer graphics", "rendering pipeline", "ray tracing", "rasterization", "webgl", "three.js", "augmented reality", "virtual reality", "quaternion"],
    "mathematics": ["linear algebra", "calculus", "probability", "statistics", "discrete math", "bayesian", "graph theory", "derivative", "integral", "matrices intuition"],
    "career_growth": ["system design interview", "coding interview", "career growth", "engineering leadership", "salary negotiation", "personal brand", "staff engineer", "tech lead"],
    "law_compliance": ["lgpd", "gdpr", "compliance", "licensing", "intellectual property", "patent", "copyright", "privacy by design", "data retention", "consent management"],
    "arts_creativity": ["music theory", "creative writing", "photography", "design thinking", "creativity", "brainstorming"],
    "medicine_health": ["immune system", "cardiovascular", "medication", "antibiotic", "vaccine", "anatomy", "disease", "medicina", "saúde", "doença", "vacina"],
    "psychology": ["cognitive bias", "psychology", "attachment theory", "memory works", "motivation", "emotional intelligence", "cognitive behavioral", "psicologia", "comportamento"],
    "education_pedagogy": ["how people learn", "teaching method", "bloom's taxonomy", "retrieval practice", "montessori", "curriculum", "pedagog", "educação", "ensino", "didática"],
    "environment_sustainability": ["solar panel", "renewable energy", "carbon footprint", "circular economy", "biodiversity", "ecosystem", "sustainability", "meio ambiente", "sustentab"],
    "cooking_nutrition": ["macronutrient", "maillard", "fermentation", "balanced diet", "cooking technique", "food safety", "nutrition", "culinária", "nutrição", "gastronomia", "receita"],
    "space_astronomy": ["stars form", "solar system", "rocket", "big bang", "exoplanet", "galaxies", "astronomy", "astronomia", "espaço", "galáxia", "planeta"],
    "geography_geopolitics": ["plate tectonics", "ocean current", "geopolitics", "biomes", "map projection", "water cycle", "geography", "geografia", "geopolítica"],
    "marketing_sales": ["marketing funnel", "branding", "consumer psychology", "content marketing", "selling", "pricing strategy", "marketing", "vendas"],
    "sports_fitness": ["strength training", "hypertrophy", "cardio", "sports nutrition", "injury prevention", "periodization", "fitness", "esporte", "treino", "musculação"],
    "engineering_physical": ["structural load", "internal combustion", "electrical circuit", "electric motor", "thermodynamics", "materials science", "engenharia civil", "engenharia mecânica"],
    "networking_protocols": ["tcp", "udp", "http/2", "http/3", "quic", "dns", "tls handshake", "load balancing", "vpn", "proxy", "redes", "protocolo"],
    "testing_qa": ["unit test", "integration test", "e2e test", "test driven", "tdd", "property based test", "mocking", "test double", "code coverage", "teste de software", "qa"],
    "quantum_computing": ["qubit", "superposition", "entanglement", "shor's algorithm", "quantum gate", "quantum error", "quantum supremacy", "computação quântica", "quântica"],
    "robotics_automation": ["robot", "ros robot", "inverse kinematics", "pid control", "industrial automation", "plc", "robótica", "automação", "atuador"],
    "investing_markets": ["stock market", "value investing", "growth investing", "etf", "mutual fund", "price to earnings", "asset allocation", "dividend", "investimento", "ações", "bolsa"],
    "crypto_finance": ["bitcoin", "defi", "stablecoin", "crypto wallet", "staking", "yield farming", "tokenomics", "cripto", "blockchain finance"],
    "accounting_tax": ["balance sheet", "income statement", "cash flow statement", "bookkeeping", "depreciation", "amortization", "tax bracket", "accrual", "contabilidade", "imposto", "tributo"],
    "macroeconomics": ["central bank", "interest rate", "gdp", "inflation", "monetary policy", "fiscal policy", "exchange rate", "recession", "macroeconomia", "economia"],
    "pharmacology": ["pharmacokinetics", "pharmacodynamics", "drug interaction", "painkiller", "antidepressant", "clinical trial", "metabolized", "farmacologia", "medicamento", "remédio"],
    "public_health": ["epidemiology", "diseases spread", "herd immunity", "public health", "health surveillance", "social determinants", "saúde pública", "epidemiologia", "pandemia"],
    "biotech_genomics": ["crispr", "dna sequencing", "mrna", "stem cells", "synthetic biology", "genetic inheritance", "genome", "biotecnologia", "genômica", "genética"],
    "politics_government": ["democracy", "elections", "separation of powers", "political ideolog", "how laws are made", "international relations", "public policy", "política", "governo", "eleições"],
    "languages_learning": ["learn a language", "comprehensible input", "vocabulary", "phonetics", "pronunciation", "language families", "bilingualism", "idioma", "aprender inglês"],
    "agriculture_food": ["agriculture", "crop rotation", "soil health", "irrigation", "sustainable farming", "food supply chain", "hydroponics", "agricultura", "plantio", "lavoura"],
}

# Reforço de palavras-chave para reduzir o balde "outros": termos PT da enciclopédia,
# nomes de ferramentas (GitHub trending) e títulos de livros que antes não casavam.
_EXTRA_KEYWORDS: dict[str, list[str]] = {
    "science": ["relatividade", "fotossíntese", "tabela periódica", "evolução", "gene egoísta", "física quântica"],
    "medicine_health": ["imunológico", "imunitário", "anatomia humana", "coração humano"],
    "biotech_genomics": ["genética", "sequenciamento", "dna humano"],
    "psychology": ["psicanálise", "mindset", "homem em busca de sentido", "inteligência emocional", "flow csikszentmihalyi"],
    "history_philosophy": ["estoicismo", "renascimento", "iluminismo", "revolução industrial", "segunda guerra", "sapiens", "arte da guerra", "meditações", "filosofia", "marco aurélio"],
    "arts_creativity": ["pintura", "cinema", "música"],
    "environment_sustainability": ["mudança climática", "vulcão", "oceano", "sustentabilidade"],
    "space_astronomy": ["sistema solar"],
    "politics_government": ["democracia", "capitalismo"],
    "productivity_learning": ["hábitos atômicos", "poder do hábito", "deep work", "essencialismo", "7 hábitos", "os 7 hábitos"],
    "finance_economics": ["pai rico", "psicologia financeira", "antifrágil", "cisne negro", "economia comportamental"],
    "business_product": ["comece pelo porquê", "como fazer amigos", "influenciar pessoas"],
    "databases": ["vector db", "vector database", "migrations", "alembic", "qdrant", "orm"],
    "backend_apis": ["logging", "loguru", "http client", "httpx", "package manager", "linter", "ruff", "cli com tipos", "typer", "event-driven", "faststream", "starlette"],
    "data_ml": ["feature store", "small language model", "slm"],
    "data_engineering": ["data contract", "workflow", "temporal", "prefect", "orchestrat", "dagster"],
    "devops_cloud": ["devcontainer", "trending", "nix flakes"],
}
for _sector, _kws in _EXTRA_KEYWORDS.items():
    SECTOR_KEYWORDS.setdefault(_sector, []).extend(_kws)

# Segunda passada: termos de linguagem/runtime e mais PT da enciclopédia.
_EXTRA_KEYWORDS_2: dict[str, list[str]] = {
    "backend_apis": ["python", "pep ", "type checking", "packaging", "pyright", "mypy", "rye"],
    "systems_languages": ["nogil", "free-threaded", "metaclass", "generator protocol", "gil removal", "ebpf"],
    "devops_cloud": ["edge computing", "service mesh"],
    "arts_creativity": ["arquitetura"],
    "medicine_health": ["coração", "cérebro"],
    "biotech_genomics": ["dna"],
    "space_astronomy": ["buraco negro"],
    "engineering_physical": ["termodinâmica"],
    "psychology": ["rápido e devagar", "flow (mihaly"],
    "frontend_web": ["accessibility", "aria", "acessibilidade"],
    "ai_agents": ["autoaprendizado", "auto-aprendizado", "self-learning"],
}

# Terceira passada (2026-07-19): amostra real do painel "Conhecimento por setor"
# mostrou centenas de verbetes de enciclopédia legítimos ("Metabolismo
# (enciclopédia)", "Grécia Antiga (enciclopédia)") sem cobertura — caíam em
# "Outros" não por serem ruído, mas por falta de palavra-chave. Só termos
# distintivos (sem risco de substring em palavra comum, ex.: "lógica" NÃO
# entra — é substring de "biológica"/"ecológica"/"tecnológica").
_EXTRA_KEYWORDS_3: dict[str, list[str]] = {
    "medicine_health": ["psiquiatria", "neurologia", "neurociência", "microbiologia", "metabolismo", "longevidade"],
    "science": ["antimatéria", "entropia"],
    "space_astronomy": ["via láctea"],
    "environment_sustainability": ["amazônia"],
    "history_philosophy": ["grécia antiga", "império romano", "idade média", "antropologia",
                             "retórica", "rota da seda", "teoria dos jogos"],
    "robotics_automation": ["robô"],
    "arts_creativity": ["fotografia"],
}
for _sector, _kws in _EXTRA_KEYWORDS_3.items():
    SECTOR_KEYWORDS.setdefault(_sector, []).extend(_kws)
for _sector, _kws in _EXTRA_KEYWORDS_2.items():
    SECTOR_KEYWORDS.setdefault(_sector, []).extend(_kws)


@lru_cache(maxsize=8192)
def classify_sector(text: str) -> str:
    """Descobre o setor de um tópico. 1º tenta o mapa exato; senão usa palavras-chave;
    senão 'outros'. Funciona para qualquer agente (docs/trends/GitHub/usuário).

    Cacheado (lru_cache): função pura e determinística, chamada milhares de vezes
    nos painéis Mente/Mapa e a cada save — tópicos repetidos saem de graça."""
    if not text:
        return "outros"
    # Remove prefixos comuns ("[A.P.O.L.O.] ", "[Tendência] ", "Pesquisa: ")
    clean = text
    for pref in ("[A.P.O.L.O.] ", "[Tendência] ", "Tendência: ", "Pesquisa profunda: ", "Pesquisa: "):
        if clean.startswith(pref):
            clean = clean[len(pref):]
    if clean in TOPIC_SECTOR:
        return TOPIC_SECTOR[clean]
    low = clean.lower()
    best, best_score = "outros", 0
    for sector, kws in SECTOR_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in low)
        if score > best_score:
            best, best_score = sector, score
    return best


# ── Re-verificação priorizada (P2.7) ────────────────────────────────
# Setores que mudam RÁPIDO (framework nova, API depreciada, versão nova) —
# re-verificar em janela mais curta que o padrão de RELEARN_DAYS (21). O
# resto (ciência, matemática, história...) é estável de propósito: não teria
# sentido "atualizar" a Segunda Lei de Newton toda semana.
VOLATILE_SECTORS: frozenset[str] = frozenset({
    "backend_apis", "frontend_web", "mobile", "data_ml", "systems_languages",
    "devops_cloud", "databases", "security", "ai_agents", "game_dev",
    "blockchain_web3", "data_engineering", "sre_reliability", "embedded_iot",
    "graphics_xr", "networking_protocols",
})
VOLATILE_RELEARN_DAYS = int(os.getenv("VOLATILE_RELEARN_DAYS", 10))


def relearn_window_days(topic: str, base: int | None = None) -> int:
    """Quantos dias até um TÓPICO poder ser re-estudado — mais curto pra
    setores voláteis (tech que muda rápido), o padrão (`RELEARN_DAYS`) pro
    resto. `base` sobrescreve o padrão (injetável nos testes, sem depender
    de env). `base<=0` é "nunca re-estuda" (RELEARN_DAYS desligado) — nunca
    encurtado, desligado é desligado."""
    from src.storage_models import RELEARN_DAYS

    base = RELEARN_DAYS if base is None else base
    if base <= 0:
        return base
    sector = classify_sector(topic)
    return min(base, VOLATILE_RELEARN_DAYS) if sector in VOLATILE_SECTORS else base
