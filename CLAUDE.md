# CLAUDE.md — AI Assistant Guide for EvaRAG Playwright Crawler

## Project Overview

Multi-service Python/FastAPI application (v3.16.1) combining:
- **Playwright Crawler**: BFS-based web scraping with adaptive timeouts and deduplication
- **RPA Module**: Robotic Process Automation for scraping insurance quotes from Moroccan insurers
- **Admin Dashboard**: Real-time monitoring with WebSocket support and Docker orchestration
- **Document Processor**: OCR and document parsing via Celery task queue
- **OCR Services**: Google Vision + EasyOCR wrappers

## Repository Structure

```
/
├── main.py                    # Primary FastAPI app — crawler + RPA endpoints (port 11235)
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Playwright service container
├── docker-compose.yml         # 8-service orchestration
├── .env                       # Environment config (DO NOT commit secrets)
├── SYNTHESIS.md               # Architecture documentation (French)
├── rpa_implementation_plan.md # RPA phased implementation guide
│
├── rpa/                       # RPA module
│   ├── __init__.py            # Public API exports
│   ├── models.py              # Pydantic v2 data models
│   ├── exceptions.py          # Custom exception hierarchy
│   ├── config_manager.py      # YAML config loading with 1-hour TTL cache
│   ├── quote_scraper.py       # Main scraping orchestrator
│   ├── configs/               # YAML workflow configs per insurer
│   │   └── validated/         # Validated production configs
│   └── insurers/              # Scraper implementations
│       ├── base.py            # BaseInsurer abstract class
│       ├── generic.py         # GenericYAMLScraper
│       └── allianz_maroc.py   # Reference insurer implementation
│
├── admin_dashboard/           # Admin UI (port 8080)
│   ├── main.py                # WebSocket + Docker management
│   └── templates/index.html   # Single-page admin UI
│
├── document_processor/        # OCR & document processing (port 11236)
│   ├── main.py
│   └── tasks.py               # Celery tasks
│
├── ocr_service/               # Google Vision OCR wrapper
├── easyocr_service/           # EasyOCR wrapper
├── logs/                      # Application logs (gitignored)
└── data/                      # Runtime data (gitignored)
```

## Tech Stack

- **Language**: Python 3, async/await throughout
- **Framework**: FastAPI + Uvicorn
- **Browser Automation**: Playwright 1.54.0
- **Data Validation**: Pydantic v2
- **Task Queue**: Celery + Redis broker
- **Caching**: Redis
- **OCR**: Google Cloud Vision, EasyOCR, Tesseract
- **Monitoring**: Prometheus metrics
- **Deployment**: Docker Compose (8 containers)
- **External**: Supabase (database + edge functions), Resend (email)

## Build & Run Commands

```bash
# Start all services
docker-compose up -d

# Build and start specific service
docker-compose build playwright-crawler
docker-compose up -d playwright-crawler

# View logs
docker-compose logs -f playwright-crawler

# Stop all services
docker-compose down
```

There is no Makefile, no npm scripts. Services are Python-only, managed via Docker.

## Testing

No formal test suite is configured yet. No `pytest.ini`, `setup.cfg`, or test directories exist.

Testing is currently manual via curl/HTTP requests. The planned structure (from docs) is:
```bash
pytest tests/unit/test_config_manager.py
pytest tests/integration/test_rpa_flow.py
```

## Linting & Formatting

No linting or formatting tools are configured (no flake8, black, ruff, mypy, or pre-commit hooks).

## CI/CD

No CI/CD pipeline exists. Deployment is manual via `docker-compose` on remote servers.

## Code Conventions

### Style
- **Language in code**: French comments and docstrings throughout
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes
- **Type hints**: Extensive — Pydantic models for all API I/O, type annotations on functions
- **Docstrings**: Google-style with triple quotes
- **Line length**: ~100-120 characters
- **Logging**: `logger = logging.getLogger(__name__)` pattern in every module

### Architecture Patterns
- **Async-first**: All I/O uses `async`/`await`
- **Factory pattern**: `create_scraper()` for dynamic scraper instantiation
- **Abstract base classes**: `BaseInsurer` defines the scraper interface
- **YAML-driven workflows**: Insurer configs are external YAML files, not hardcoded
- **Dependency injection**: Services receive dependencies as constructor parameters

### API Design
- Crawler endpoints: `/crawl4ai/{resource}`
- RPA endpoints: `/rpa/{resource}`
- Async processing: POST returns job acceptance immediately, results sent via `callback_url` webhook
- Authentication: HTTP Basic Auth on protected endpoints (`HTTPBasic` dependency)
- No REST API versioning (v1/v2)

### Error Handling
- Custom exception hierarchy in `rpa/exceptions.py` with job context (job_id, insurer name)
- Screenshot capture on scraper failures for debugging
- Timeout-aware error responses
- Path traversal protection in config file handling

### Configuration
- YAML files as primary config source for insurer workflows
- Supabase as optional secondary source
- Hot-reload capability without service restart
- In-memory caching with 1-hour TTL
- Environment variables via `.env` and `docker-compose.yml`

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `CRAWLER_WORKER_SECRET` | Basic Auth secret for crawler |
| `BASIC_AUTH_USER` / `BASIC_AUTH_PASS` | Admin dashboard credentials |
| `SUPABASE_JOB_STATUS_URL` | Callback endpoint for job status |
| `SUPABASE_ANON_KEY` | Supabase public API key |
| `DEFAULT_NAV_TIMEOUT` | Navigation timeout (default 30000ms) |
| `MAX_CONCURRENT_PAGES` | Concurrent Playwright pages (default 3) |
| `ENABLE_ADAPTIVE_TIMEOUTS` | Toggle adaptive timeout feature |
| `UVICORN_WORKERS` | Number of Uvicorn workers (default 2) |

## Service Ports

| Service | Internal Port | External Port |
|---------|--------------|---------------|
| Playwright Crawler | 11235 | 30001 |
| Document Processor | 11236 | 30002 |
| Admin Dashboard | 8080 | 30003 |

## Adding a New Insurer Scraper

1. Create YAML config in `rpa/configs/{insurer_name}.yaml`
2. If custom logic is needed, create `rpa/insurers/{insurer_name}.py` extending `BaseInsurer`
3. Register in `rpa/insurers/__init__.py` factory
4. For simple cases, `GenericYAMLScraper` handles YAML-only configs automatically
5. Reference implementation: `rpa/insurers/allianz_maroc.py`

## Important Notes

- **Do not commit `.env` or `gcp-credentials.json`** — they contain secrets
- **Documentation is in French** — maintain this convention for comments and docstrings
- **`backup_v31/`** contains a previous version backup; do not modify
- **Large files**: `admin_dashboard/main.py` (~11K lines) and `admin_dashboard/templates/index.html` (~26K lines) — edit carefully
- **Monorepo**: All 8 services share one repo; services communicate via Docker internal network
