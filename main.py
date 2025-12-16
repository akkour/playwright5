"""
EvaRAG Enhanced Crawler Service v3.16.1 - RPA Quote Integration + Job Status Notifications + Docker Execute Command
Service de crawling avec Playwright — version complète, ZÉRO régression.

✅ CORRECTIONS v3.16.1:
- Fixed duration_ms type: convertir float en int pour Pydantic (RPAQuoteResponse exige un entier)
- Fixed result extraction: extraire QuoteResult de RPAQuoteResponse si nécessaire
- Ajouté duration_ms aux blocs d'erreur InsurerNotFoundError, ScrapingTimeoutError, Exception

✅ NOUVEAUTÉS v3.16.0:
- POST /rpa/execute-command : Exécute des commandes docker-compose sécurisées
- Whitelisting strict des actions, services et arguments autorisés
- Audit logging de toutes les commandes exécutées
- Timeout configurable et sanitization des outputs

✅ NOUVEAUTÉS v3.15.0:
- Fonction notify_job_status() pour envoyer les notifications de statut à Supabase Edge Function
- Notifications automatiques à la création, démarrage, complétion et échec des jobs RPA
- Intégration avec l'edge function rpa-job-status pour persistance en BDD

✅ NOUVEAUTÉS v3.14.0:
- GET /rpa/configs : Liste tous les fichiers YAML disponibles
- GET /rpa/configs/{name} : Lit le contenu d'un fichier YAML
- PUT /rpa/configs/{name} : Met à jour un fichier YAML avec validation et backup automatique
- Fonction sanitize_insurer_name() pour prévenir les attaques path traversal
- Modèle YAMLConfigUpdateRequest pour la validation des requêtes PUT

✅ CORRECTIONS MAJEURES v3.13.2:
- (C1-9) Fixed /rpa/reload-config endpoint to accept 'force: true' payload.
- (C1-9) Added ConfigReloadRequest import from rpa.models.

✅ CORRECTIONS MAJEURES v3.13.1:
- Fixed RPAJobResponse import and usage for immediate job acceptance
- RPAQuoteResponse now only used for callback (not immediate response)
- Fixed Pydantic validation error: "queued" status replaced with proper RPAJobResponse
- Fixed logging duplication and indentation issues

✅ v3.13: Module RPA intégré pour scraping d'assurances marocaines
✅ v3.12: Détection des redirections initiales (ex: /fr) et contrainte dynamique du crawl.
- Worker asynchrone intelligent avec déduplication et normalisation d'URL à la volée.
- Authentification Basique unifiée pour les endpoints sécurisés.
"""

from __future__ import annotations

import os
import re
import json
import time
import secrets
import psutil
import hashlib
import asyncio
import aiofiles
import random
import yaml
import subprocess
import shlex
from datetime import datetime
from collections import deque, defaultdict
from typing import List, Optional, Dict, Any, Tuple, Union

from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup
import redis.asyncio as redis

from fastapi import (
    FastAPI, Request, HTTPException, BackgroundTasks, Header, Depends, status
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, AnyHttpUrl

from prometheus_client import Counter, Histogram, Gauge, generate_latest

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# =========================
# Logging (must be defined early)
# =========================
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =========================
# RPA Module Imports
# =========================
try:
    from rpa import (
        quote_scraper,
        config_manager,
        exceptions as rpa_exceptions
    )
    from rpa.models import (
        RPAQuoteRequest,
        RPAJobResponse,
        RPAQuoteResponse,
        RPAStatsResponse,
        RPAReloadResponse,
        ConfigReloadRequest
    )
    RPA_MODULE_LOADED = True
    RPA_VERSION = "1.2.0"
    logger.info(f"✅ RPA module loaded: v{RPA_VERSION}")
except ImportError as e:
    RPA_MODULE_LOADED = False
    RPA_VERSION = "not_loaded"
    logger.warning(f"⚠️ RPA module not available: {e}")

# =========================
# Configuration & Globals
# =========================

APP_NAME = "EvaRAG Crawler Service"
APP_VERSION = "3.16.1"

CRAWLER_WORKER_SECRET = os.getenv("CRAWLER_WORKER_SECRET", "")
DEFAULT_CALLBACK_URL = os.getenv("CRAWLER_CALLBACK_URL", "")

# Supabase Edge Function URL for job status notifications
SUPABASE_JOB_STATUS_URL = os.getenv(
    "SUPABASE_JOB_STATUS_URL", 
    "https://xmxwknqmuicygjnyipws.supabase.co/functions/v1/rpa-job-status"
)
SUPABASE_CALLBACK_SECRET = os.getenv("SUPABASE_CALLBACK_SECRET", "")

# Docker Command Execution Configuration (v3.16.0)
ENABLE_DOCKER_COMMANDS = os.getenv("ENABLE_DOCKER_COMMANDS", "false").lower() == "true"
DOCKER_COMMAND_TIMEOUT = int(os.getenv("DOCKER_COMMAND_TIMEOUT", "120"))

class Config:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    DEFAULT_NAV_TIMEOUT = int(os.getenv("DEFAULT_NAV_TIMEOUT", 60000))
    NETWORK_IDLE_TIMEOUT = int(os.getenv("NETWORK_IDLE_TIMEOUT", 25000))
    SCREENSHOT_TIMEOUT = int(os.getenv("SCREENSHOT_TIMEOUT", 5000))
    STATIC_TIMEOUT = 30.0
    MAX_LINKS_RETURNED = 50
    MAX_CONCURRENT_PAGES = 3
    MAX_RETRIES = 3
    CACHE_TTL = 3600
    MONITORING_INTERVAL = 5
    METRICS_RETENTION = 86400
    LOG_DIR = Path("logs")
    BFS_QUEUE_MULTIPLIER = 3.0
    BFS_SEEN_MULTIPLIER = 5.0
    CALLBACK_TIMEOUT = 30
    CALLBACK_RETRY_COUNT = 3

# =========================
# Authentification
# =========================
security = HTTPBasic()
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS", "Hg.54.uyt.$$!!.xcv")

def verify_basic_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, BASIC_AUTH_USER)
    correct_password = secrets.compare_digest(credentials.password, BASIC_AUTH_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# =========================
# Pydantic Models (Crawler)
# =========================

class CrawlRequest(BaseModel):
    urls: List[AnyHttpUrl]
    max_depth: int = Field(default=2, ge=1, le=5)
    max_pages: int = Field(..., ge=1, le=500)
    extract_text: bool = True
    render_js: bool = True
    chunk_size: int = Field(default=1000, ge=100, le=10000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    include_patterns: List[str] = []
    exclude_patterns: List[str] = []
    wait_selector: Optional[str] = None
    timeout: int = Field(default=30, ge=5, le=180)

class CrawlJobRequest(BaseModel):
    site_id: str
    organization_id: str
    url: AnyHttpUrl
    callback_url: AnyHttpUrl
    depth: int = Field(default=2, ge=1, le=5)
    max_pages: int = Field(default=10, ge=1, le=500)
    render_js: bool = True
    extract_text: bool = True
    chunk_size: int = Field(default=1000, ge=100, le=10000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    correlation_id: Optional[str] = None
    include_patterns: List[str] = []
    exclude_patterns: List[str] = []

class CrawlResult(BaseModel):
    url: str
    title: str
    textContent: str
    description: str = ""
    language: str = "unknown"
    wordCount: int = 0
    images: List[str] = []
    links: List[str] = []
    depth: int = 0
    crawled_at: str
    response_time: float = 0.0
    status_code: int = 200

class CrawlResponse(BaseModel):
    success: bool
    results: List[CrawlResult] = []
    summary: Dict[str, Any] = {}
    errors: List[str] = []
    timestamp: str

# =========================
# Pydantic Models (YAML Config API)
# =========================

class YAMLConfigUpdateRequest(BaseModel):
    """Request body for YAML config update"""
    content: str = Field(..., description="YAML content to write", min_length=10)

# =========================
# Pydantic Models (Docker Execute Command - v3.16.0)
# =========================

class ExecuteCommandRequest(BaseModel):
    """Request body for Docker command execution"""
    action: str = Field(..., description="Action to execute: build, up, down, restart, logs, ps, docker-ps, docker-logs")
    service: Optional[str] = Field(None, description="Service name (optional)")
    args: Optional[List[str]] = Field(None, description="Additional arguments (optional)")
    raw_command: Optional[str] = Field(None, description="Original raw command for logging")

class ExecuteCommandResponse(BaseModel):
    """Response for Docker command execution"""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    command: str
    executed_at: str

# =========================
# Métriques Prometheus
# =========================

crawl_requests_total = Counter('crawl_requests_total', 'Total crawl requests')
crawl_success_total = Counter('crawl_success_total', 'Successful crawls')
crawl_failures_total = Counter('crawl_failures_total', 'Failed crawls')
crawl_duration_seconds = Histogram('crawl_duration_seconds', 'Crawl duration')
active_crawls = Gauge('active_crawls_total', 'Currently active crawls')

# RPA Metrics
rpa_requests_total = Counter('rpa_requests_total', 'Total RPA requests')
rpa_success_total = Counter('rpa_success_total', 'Successful RPA jobs')
rpa_failures_total = Counter('rpa_failures_total', 'Failed RPA jobs')
rpa_duration_seconds = Histogram('rpa_duration_seconds', 'RPA job duration')

# Docker Command Metrics (v3.16.0)
docker_commands_total = Counter('docker_commands_total', 'Total Docker commands executed')
docker_commands_success = Counter('docker_commands_success', 'Successful Docker commands')
docker_commands_failed = Counter('docker_commands_failed', 'Failed Docker commands')

# =========================
# Classes de Support
# =========================

class CrawlStats:
    def __init__(self):
        self.daily_stats = defaultdict(int)
        self.reset_daily_stats()

    def reset_daily_stats(self):
        self.daily_stats.update({
            "total_requests": 0, "successful_crawls": 0, "failed_crawls": 0,
            "domains_crawled": set(), "total_processing_time": 0.0,
            "errors_by_type": defaultdict(int), "last_request_time": None
        })

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if key == "domains_crawled" and isinstance(value, str):
                self.daily_stats[key].add(value)
            elif key == "errors_by_type" and isinstance(value, dict):
                for error_type, count in value.items():
                    self.daily_stats[key][error_type] += count
            else:
                self.daily_stats[key] += value

class JobManager:
    def __init__(self):
        self.jobs = {}
        self.results = {}

    def create_job(self, job_id: str, data: dict) -> str:
        self.jobs[job_id] = { 'id': job_id, 'status': 'queued', 'created_at': datetime.now().isoformat(), 'data': data }
        return job_id

    def update_job(self, job_id: str, updates: dict):
        if job_id in self.jobs:
            self.jobs[job_id].update(updates)

    def get_job(self, job_id: str) -> Optional[dict]:
        return self.jobs.get(job_id)

    def set_job_result(self, job_id: str, result: dict):
        self.results[job_id] = result
        self.update_job(job_id, {'status': 'completed'})

class CallbackManager:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=Config.CALLBACK_TIMEOUT)

    async def send_callback(self, url: str, event_type: str, data: dict, job_id: str):
        if not url: return
        payload = { 'type': event_type, 'job_id': job_id, 'timestamp': datetime.now().isoformat(), **data }
        headers = { 'Content-Type': 'application/json', 'X-Crawler-Secret': CRAWLER_WORKER_SECRET }
        try:
            await self.client.post(url, json=payload, headers=headers)
        except Exception as e:
            logger.error(f"❌ Callback error: {str(e)}")

    async def close(self):
        await self.client.aclose()

# =========================
# Job Status Notification (NEW v3.15.0)
# =========================

async def notify_job_status(
    job_id: str,
    event: str,
    insurer_name: str = None,
    product: str = None,
    input_payload: dict = None,
    result: dict = None,
    error_message: str = None,
    duration_ms: int = None,
    status: str = None
):
    """
    Notify Supabase Edge Function of job status changes.
    
    Args:
        job_id: Unique job identifier
        event: Event type - "created", "started", "completed", "failed", "timeout"
        insurer_name: Name of the insurer
        product: Product code (e.g., "auto")
        input_payload: Original request data
        result: Quote result (for completed jobs)
        error_message: Error description (for failed jobs)
        duration_ms: Job duration in milliseconds
        status: Explicit status override
    """
    if not SUPABASE_JOB_STATUS_URL:
        logger.warning(f"⚠️ [RPA] SUPABASE_JOB_STATUS_URL not configured, skipping notification for {job_id}")
        return
    
    payload = {
        "job_id": job_id,
        "event": event,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if insurer_name:
        payload["insurer_name"] = insurer_name
    if product:
        payload["product"] = product
    if input_payload:
        payload["input_payload"] = input_payload
    if result:
        payload["result"] = result
    if error_message:
        payload["error_message"] = error_message
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    if status:
        payload["status"] = status
    
    headers = {
        "Content-Type": "application/json"
    }
    
    if SUPABASE_CALLBACK_SECRET:
        headers["X-Playwright-Secret"] = SUPABASE_CALLBACK_SECRET
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                SUPABASE_JOB_STATUS_URL,
                json=payload,
                headers=headers
            )
            if response.status_code == 200:
                logger.info(f"✅ [RPA] Job status notified: {job_id} -> {event}")
            else:
                logger.warning(f"⚠️ [RPA] Job status notification returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        logger.warning(f"⚠️ [RPA] Failed to notify job status for {job_id}: {str(e)}")

# =========================
# Docker Command Execution (NEW v3.16.0)
# =========================

# Strict whitelist for allowed actions
ALLOWED_ACTIONS = {'build', 'up', 'down', 'restart', 'logs', 'ps', 'docker-ps', 'docker-logs'}

# Strict whitelist for allowed services
ALLOWED_SERVICES = {
    'playwright-crawler', 
    'admin_dashboard', 
    'document_processor', 
    'easyocr_service', 
    'ocr_service',
    'redis',
    None  # Allow None for commands that don't need a service
}

# Strict whitelist for allowed arguments
ALLOWED_ARGS = {
    '--no-cache', '-d', '--detach', '-f', '--follow', 
    '--tail=50', '--tail=100', '--tail=200', '--tail=500',
    '-a', '--all'
}

def sanitize_output(output: str, max_length: int = 10000) -> str:
    """Sanitize command output to prevent information leakage"""
    if not output:
        return ""
    # Remove ANSI color codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned = ansi_escape.sub('', output)
    # Truncate if too long
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + f"\n... (truncated, {len(output) - max_length} chars remaining)"
    return cleaned

def execute_docker_command_sync(action: str, service: Optional[str], args: Optional[List[str]]) -> Tuple[bool, str, str]:
    """
    Execute a Docker command synchronously with strict validation.
    Returns (success, output, error)
    """
    # Validate action
    if action not in ALLOWED_ACTIONS:
        return False, "", f"Action non autorisée: {action}"
    
    # Validate service
    if service and service not in ALLOWED_SERVICES:
        return False, "", f"Service non autorisé: {service}"
    
    # Validate args
    if args:
        for arg in args:
            if arg and arg not in ALLOWED_ARGS:
                # Check for --tail=N pattern
                if not re.match(r'^--tail=\d+$', arg):
                    return False, "", f"Argument non autorisé: {arg}"
    
    # Build the command
    cmd = []
    
    if action == 'docker-ps':
        cmd = ['docker', 'ps']
        if args and '-a' in args:
            cmd.append('-a')
    elif action == 'docker-logs':
        if not service:
            return False, "", "Service requis pour docker logs"
        cmd = ['docker', 'logs']
        if args:
            for arg in args:
                if arg.startswith('--tail='):
                    cmd.append(arg)
                elif arg in ('-f', '--follow'):
                    # Don't allow -f for security (would block)
                    pass
        cmd.append(service)
    else:
        # docker compose commands (v2 syntax with space, not hyphen)
        cmd = ['docker', 'compose']
        
        if action == 'build':
            cmd.append('build')
            if args and '--no-cache' in args:
                cmd.append('--no-cache')
            if service:
                cmd.append(service)
        elif action == 'up':
            cmd.append('up')
            cmd.append('-d')  # Always detached for safety
            if service:
                cmd.append(service)
        elif action == 'down':
            cmd.append('down')
        elif action == 'restart':
            cmd.append('restart')
            if service:
                cmd.append(service)
        elif action == 'logs':
            cmd.append('logs')
            tail_arg = '--tail=100'  # Default
            if args:
                for arg in args:
                    if arg.startswith('--tail='):
                        tail_arg = arg
            cmd.append(tail_arg)
            if service:
                cmd.append(service)
        elif action == 'ps':
            cmd.append('ps')
    
    # Log the command
    cmd_str = ' '.join(cmd)
    logger.info(f"🐳 [DOCKER] Executing: {cmd_str}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DOCKER_COMMAND_TIMEOUT,
            cwd="/app"  # Execute from app directory
        )
        
        output = sanitize_output(result.stdout)
        error = sanitize_output(result.stderr)
        
        if result.returncode == 0:
            logger.info(f"✅ [DOCKER] Command succeeded: {cmd_str}")
            docker_commands_success.inc()
            return True, output, ""
        else:
            logger.warning(f"⚠️ [DOCKER] Command failed (code {result.returncode}): {cmd_str}")
            docker_commands_failed.inc()
            return False, output, error or f"Exit code: {result.returncode}"
            
    except subprocess.TimeoutExpired:
        logger.error(f"⏰ [DOCKER] Command timeout: {cmd_str}")
        docker_commands_failed.inc()
        return False, "", f"Timeout après {DOCKER_COMMAND_TIMEOUT} secondes"
    except FileNotFoundError:
        logger.error(f"❌ [DOCKER] Command not found: {cmd[0]}")
        docker_commands_failed.inc()
        return False, "", "Commande docker/docker-compose non trouvée"
    except PermissionError:
        logger.error(f"❌ [DOCKER] Permission denied for command: {cmd_str}")
        docker_commands_failed.inc()
        return False, "", "Permission refusée"
    except Exception as e:
        logger.error(f"💥 [DOCKER] Unexpected error: {str(e)}")
        docker_commands_failed.inc()
        return False, "", f"Erreur inattendue: {str(e)}"

# =========================
# Initialisation Globale
# =========================

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

job_manager = JobManager()
callback_manager = CallbackManager()

# RPA Config Manager
if RPA_MODULE_LOADED:
    rpa_config = config_manager
    try:
        rpa_config.load_all_configs()
        logger.info(f"✅ Loaded {len(rpa_config.list_insurers())} RPA configurations")
    except Exception as e:
        logger.warning(f"⚠️ Failed to load RPA configs: {e}")

# Log Docker command capability
if ENABLE_DOCKER_COMMANDS:
    logger.info(f"🐳 Docker command execution ENABLED (timeout: {DOCKER_COMMAND_TIMEOUT}s)")
else:
    logger.info(f"🐳 Docker command execution DISABLED")

# =========================
# Utilitaires
# =========================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/126.0",
]

def clean_text(text: str) -> str:
    if not text: return ""
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    return re.sub(r'\s+', ' ', cleaned).strip()

def extract_domain(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except: return ""

def normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        netloc = parts.netloc.lower()
        path = parts.path.rstrip('/') if len(parts.path) > 1 else parts.path
        params_to_remove = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid', 'mc_cid', 'mc_eid']
        query_params = [p for p in parse_qsl(parts.query) if p[0] not in params_to_remove]
        query_params.sort(key=lambda x: x[0])
        query_string = urlencode(query_params)
        return urlunparse((parts.scheme, netloc, path, parts.params, query_string, ''))
    except Exception:
        return url

def should_crawl_url(url: str, base_domain: str, include: List[str], exclude: List[str]) -> bool:
    normalized_url = normalize_url(url)
    if urlparse(normalized_url).netloc.lower() != base_domain: return False
    if any(re.search(p, normalized_url, re.IGNORECASE) for p in exclude): return False
    if include:
        return any(re.search(p, normalized_url, re.IGNORECASE) for p in include)
    return True

def sanitize_insurer_name(name: str) -> str:
    """
    Sanitize insurer name to prevent path traversal attacks.
    Only allows alphanumeric characters, underscores, and hyphens.
    """
    return "".join(c for c in name if c.isalnum() or c in ('_', '-')).lower()

# =========================
# Fonctions de Crawling
# =========================

async def crawl_page(page, url: str, depth: int, links_limit: Optional[int] = None) -> Optional[CrawlResult]:
    start_time = time.time()
    try:
        logger.info(f"🔍 Crawling: {url} (depth: {depth})")
        response = await page.goto(url, wait_until="domcontentloaded", timeout=Config.DEFAULT_NAV_TIMEOUT)
        if not response: return None
        await page.wait_for_load_state("networkidle", timeout=Config.NETWORK_IDLE_TIMEOUT)
        title = await page.title()
        title = clean_text(title) or "Sans titre"
        text_content = await page.evaluate("() => document.body.innerText")
        text_content = clean_text(text_content)
        if len(text_content) < 50:
            logger.warning(f"⚠️ Page has insufficient content: {url}")
            return None
        description = await page.evaluate("() => document.querySelector('meta[name=\"description\"]')?.content || ''")
        description = clean_text(description)
        language = await page.evaluate("() => document.documentElement.lang || 'unknown'")
        images = await page.evaluate("() => Array.from(document.querySelectorAll('img[src]')).map(img => img.src).slice(0, 10)")
        limit = links_limit if isinstance(links_limit, int) else Config.MAX_LINKS_RETURNED
        links = await page.evaluate(f"""() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(h => h.startsWith('http') && !h.includes('#')).slice(0, {int(limit)})""")
        return CrawlResult(
            url=url, title=title, textContent=text_content, description=description, language=language,
            wordCount=len(text_content.split()), images=images, links=links, depth=depth,
            crawled_at=datetime.now().isoformat(), response_time=time.time() - start_time, status_code=response.status
        )
    except PlaywrightTimeoutError:
        logger.warning(f"⏰ Timeout crawling: {url}")
        try:
            screenshot_path = "debug_timeout_screenshot.png"
            await page.screenshot(path=screenshot_path, timeout=Config.SCREENSHOT_TIMEOUT)
            logger.info(f"📸 Screenshot saved to {screenshot_path} for debugging.")
        except Exception as screenshot_error:
            logger.error(f"💥 Failed to take screenshot for {url}: {screenshot_error}")
        return None
    except Exception as e:
        logger.error(f"💥 Error crawling {url}: {str(e)}")
        return None

async def crawl_sync(request: CrawlRequest) -> CrawlResponse:
    start_time = time.time()
    results, errors = [], []
    try:
        start_url = str(request.urls[0])
        async with httpx.AsyncClient() as client:
            try:
                response = await client.head(start_url, follow_redirects=True, timeout=15.0)
                final_url_obj = response.url
                if str(final_url_obj) != start_url and urlparse(str(final_url_obj)).path not in ('', '/'):
                    base_path = f"{final_url_obj.scheme}://{final_url_obj.host}{urlparse(str(final_url_obj)).path}"
                    if '.' not in Path(urlparse(str(final_url_obj)).path).name:
                        base_path = base_path.rstrip('/')
                        include_pattern = f"^{re.escape(base_path)}"
                        if include_pattern not in request.include_patterns:
                            request.include_patterns.append(include_pattern)
                            logger.info(f"Redirect detected. Constraining crawl to pattern: {include_pattern}")
            except httpx.RequestError as e:
                logger.warning(f"Could not check for initial redirect: {e}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9,fr;q=0.8"}
            )
            page = await context.new_page()
            to_visit = deque([(start_url, 0)])
            visited = {start_url}
            base_domain = extract_domain(start_url)
            while to_visit and len(results) < request.max_pages:
                url, depth = to_visit.popleft()
                if depth > request.max_depth: continue
                result = await crawl_page(page, url, depth)
                if result:
                    results.append(result)
                    if depth < request.max_depth:
                        for link in result.links:
                            if link not in visited and should_crawl_url(link, base_domain, request.include_patterns, request.exclude_patterns):
                                visited.add(link)
                                to_visit.append((link, depth + 1))
                else:
                    errors.append(f"Failed to crawl: {url}")
                await asyncio.sleep(random.uniform(0.5, 1.5))
            await browser.close()
    except Exception as e:
        logger.error(f"💥 Crawling error: {str(e)}")
        errors.append(str(e))
    duration = time.time() - start_time
    return CrawlResponse(
        success=len(results) > 0, results=results, errors=errors, timestamp=datetime.now().isoformat(),
        summary={ "total_pages": len(results), "total_errors": len(errors), "duration_seconds": round(duration, 2) }
    )

async def crawl_async_worker(job_id: str, job_data: CrawlJobRequest):
    start_time = time.time()
    logger.info(f"🚀 Starting async stream job: {job_id} for {job_data.url}")
    await callback_manager.send_callback(str(job_data.callback_url), 'heartbeat', {'status': 'started'}, job_id)
    
    results, pages_attempted, documents_created_count = [], 0, 0
    content_hashes_seen, errors = set(), []
    base_domain = extract_domain(str(job_data.url))
    include_patterns = job_data.include_patterns or []
    exclude_patterns = job_data.exclude_patterns or []

    try:
        start_url = str(job_data.url)
        async with httpx.AsyncClient() as client:
            try:
                response = await client.head(start_url, follow_redirects=True, timeout=15.0)
                final_url_obj = response.url
                if str(final_url_obj) != start_url and urlparse(str(final_url_obj)).path not in ('', '/'):
                    base_path = f"{final_url_obj.scheme}://{final_url_obj.host}{urlparse(str(final_url_obj)).path}"
                    if '.' not in Path(urlparse(str(final_url_obj)).path).name:
                        base_path = base_path.rstrip('/')
                        include_pattern = f"^{re.escape(base_path)}"
                        if include_pattern not in include_patterns:
                            include_patterns.append(include_pattern)
                            logger.info(f"Redirect detected. Constraining crawl to pattern: {include_pattern}")
            except httpx.RequestError as e:
                logger.warning(f"Could not check for initial redirect: {e}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
            page = await context.new_page()
            to_visit = deque([(start_url, 0)])
            visited = {start_url}
            await callback_manager.send_callback(str(job_data.callback_url), 'pages_found', {'total': job_data.max_pages}, job_id)
            while to_visit and len(results) < job_data.max_pages:
                url, depth = to_visit.popleft()
                if depth > job_data.depth: continue
                pages_attempted += 1
                result = await crawl_page(page, url, depth)
                if result:
                    results.append(result)
                    content_hash = hashlib.sha256(result.textContent.encode()).hexdigest()
                    if content_hash not in content_hashes_seen:
                        content_hashes_seen.add(content_hash)
                        documents_created_count += 1
                        normalized_url = normalize_url(result.url)
                        source_id_hash = hashlib.sha256(normalized_url.encode()).hexdigest()
                        logger.info(f"📄 [{job_id}] New unique content found, sending document: {url}")
                        doc_data = {
                            'title': result.title, 'content': result.textContent, 'source_id': f"{job_data.site_id}_{source_id_hash}",
                            'metadata': { 'url': normalized_url, 'description': result.description, 'word_count': result.wordCount,
                                        'crawled_at': result.crawled_at, 'depth': result.depth, 'language': result.language },
                            'site_id': job_data.site_id, 'organization_id': job_data.organization_id
                        }
                        await callback_manager.send_callback(str(job_data.callback_url), 'document_created', {'doc': doc_data}, job_id)
                    if depth < job_data.depth:
                        for link in result.links:
                            if link not in visited and should_crawl_url(link, base_domain, include_patterns, exclude_patterns):
                                visited.add(link)
                                to_visit.append((link, depth + 1))
                else:
                    errors.append(f"Failed to crawl: {url}")
                await callback_manager.send_callback(str(job_data.callback_url), 'progress', 
                    {'pages_crawled': pages_attempted, 'documents_created': documents_created_count}, job_id)
                await asyncio.sleep(random.uniform(0.5, 1.5))
            await browser.close()
        duration = time.time() - start_time
        summary = { "total_pages": len(results), "documents_created": documents_created_count,
                    "total_errors": len(errors), "duration_seconds": round(duration, 2) }
        await callback_manager.send_callback(str(job_data.callback_url), 'completed', {'metrics': summary}, job_id)
        job_manager.set_job_result(job_id, {"summary": summary, "errors": errors})
        logger.info(f"✅ Async stream job finished: {job_id}")
    except Exception as e:
        logger.error(f"💥 Async worker failed: {job_id} - {str(e)}")
        await callback_manager.send_callback(str(job_data.callback_url), 'failed', {'error': str(e)}, job_id)
        job_manager.update_job(job_id, {'status': 'failed', 'error': str(e)})

# =========================
# RPA Background Worker (UPDATED v3.15.0)
# =========================

async def rpa_quote_worker(job_id: str, request_data: RPAQuoteRequest):
    """
    Background worker for RPA quote scraping.
    Sends result via callback when complete.
    NOW WITH: Job status notifications to Supabase
    """
    if not RPA_MODULE_LOADED:
        logger.error(f"❌ [RPA] Module not loaded, cannot process job {job_id}")
        return
    
    start_time = time.time()
    logger.info(f"🤖 [RPA] Starting job {job_id} for {request_data.insurer_name} - {request_data.product_code}")
    
    # ===== NOTIFICATION: Job started =====
    await notify_job_status(
        job_id=job_id,
        event="started",
        insurer_name=request_data.insurer_name,
        product=request_data.product_code,
        status="running"
    )
    
    try:
        # Create scraper
        result = await quote_scraper.scrape_quote(request_data)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Build callback response
        # Note: result peut être un RPAQuoteResponse ou un QuoteResult selon le scraper
        actual_result = result.result if hasattr(result, 'result') else result
        callback_payload = RPAQuoteResponse(
            job_id=job_id,
            status="success",
            result=actual_result,
            duration_ms=int(duration_ms)  # Convertir en int (Pydantic exige un entier)
        )
        
        # Send callback to original callback_url if provided
        if request_data.callback_url:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    request_data.callback_url,
                    json=callback_payload.dict(),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY', '')}","X-Playwright-Secret": os.getenv('PLAYWRIGHT_CALLBACK_SECRET', '')}
                )
        
        logger.info(f"✅ [RPA] Job {job_id} completed successfully in {duration_ms:.0f}ms")
        rpa_success_total.inc()
        
        # ===== NOTIFICATION: Job completed =====
        result_dict = result.dict() if hasattr(result, 'dict') else result
        await notify_job_status(
            job_id=job_id,
            event="completed",
            insurer_name=request_data.insurer_name,
            product=request_data.product_code,
            result=result_dict,
            duration_ms=int(duration_ms),
            status="completed"
        )
        
    except rpa_exceptions.InsurerNotFoundError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ [RPA] Insurer not found for job {job_id}: {str(e)}")
        callback_payload = RPAQuoteResponse(
            job_id=job_id,
            status="failed",
            error_message=str(e),
            duration_ms=int(duration_ms)  # AJOUTÉ: Pydantic exige un entier
        )
        rpa_failures_total.inc()
        
        # ===== NOTIFICATION: Job failed =====
        await notify_job_status(
            job_id=job_id,
            event="failed",
            insurer_name=request_data.insurer_name,
            product=request_data.product_code,
            error_message=str(e),
            duration_ms=int(duration_ms),
            status="failed"
        )
        
    except rpa_exceptions.ScrapingTimeoutError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"⏰ [RPA] Timeout for job {job_id}: {str(e)}")
        callback_payload = RPAQuoteResponse(
            job_id=job_id,
            status="timeout",
            error_message=str(e),
            duration_ms=int(duration_ms)  # AJOUTÉ: Pydantic exige un entier
        )
        rpa_failures_total.inc()
        
        # ===== NOTIFICATION: Job timeout =====
        await notify_job_status(
            job_id=job_id,
            event="timeout",
            insurer_name=request_data.insurer_name,
            product=request_data.product_code,
            error_message=str(e),
            duration_ms=int(duration_ms),
            status="timeout"
        )
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"💥 [RPA] Unexpected error for job {job_id}: {str(e)}")
        callback_payload = RPAQuoteResponse(
            job_id=job_id,
            status="failed",
            error_message=f"Unexpected error: {str(e)}",
            duration_ms=int(duration_ms)  # AJOUTÉ: Pydantic exige un entier
        )
        rpa_failures_total.inc()
        
        # ===== NOTIFICATION: Job failed =====
        await notify_job_status(
            job_id=job_id,
            event="failed",
            insurer_name=request_data.insurer_name,
            product=request_data.product_code,
            error_message=f"Unexpected error: {str(e)}",
            duration_ms=int(duration_ms),
            status="failed"
        )
        
        # Send error callback
        try:
            if request_data.callback_url:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await client.post(
                        request_data.callback_url,
                        json=callback_payload.dict(),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY', '')}","X-Playwright-Secret": os.getenv('PLAYWRIGHT_CALLBACK_SECRET', '')}
                    )
        except Exception as callback_error:
            logger.error(f"💥 [RPA] Failed to send error callback for job {job_id}: {callback_error}")

# =========================
# Endpoints
# =========================

@app.get("/health")
@app.get("/crawl4ai/health")
async def health():
    return {
        "status": "healthy",
        "service": APP_NAME,
        "version": APP_VERSION,
        "rpa_version": RPA_VERSION,
        "rpa_enabled": RPA_MODULE_LOADED,
        "docker_commands_enabled": ENABLE_DOCKER_COMMANDS
    }

@app.post("/crawl")
@app.post("/crawl4ai/crawl")
async def crawl_endpoint(req: CrawlRequest, username: str = Depends(verify_basic_auth)):
    with crawl_duration_seconds.time(), active_crawls.track_inprogress():
        try:
            result = await crawl_sync(req)
            crawl_success_total.inc()
            return result
        except Exception as e:
            crawl_failures_total.inc()
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs")
@app.post("/crawl4ai/jobs")
async def submit_job_async(job: CrawlJobRequest, background: BackgroundTasks, x_job_id: Optional[str] = Header(default=None), username: str = Depends(verify_basic_auth)):
    logger.info(f"Authenticated user '{username}' submitted a job for site {job.site_id}.")
    job_id = x_job_id or f"crawl_{int(time.time())}_{hash(str(job.url)) % 10000}"
    job_manager.create_job(job_id, job.dict())
    background.add_task(crawl_async_worker, job_id, job)
    logger.info(f"🆔 Async job created: {job_id}")
    return { 'success': True, 'job_id': job_id, 'status': 'queued', 'message': 'Job queued for processing', 'callback_url': str(job.callback_url) }

@app.get("/jobs/{job_id}")
async def get_job(job_id: str, username: str = Depends(verify_basic_auth)):
    job = job_manager.get_job(job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "completed":
        return {"job": job, "result": job_manager.results.get(job_id)}
    return {"job": job}

# =========================
# RPA Endpoints (UPDATED v3.15.0)
# =========================

@app.post("/rpa/quote", response_model=RPAJobResponse)
async def rpa_quote_endpoint(
    request: RPAQuoteRequest,
    background: BackgroundTasks,
    username: str = Depends(verify_basic_auth)
):
    """
    Submit an RPA quote scraping job.
    Returns immediately with job acceptance status.
    Actual result will be sent to callback_url when scraping completes.
    NOW WITH: Job status notifications to Supabase
    """
    if not RPA_MODULE_LOADED:
        raise HTTPException(
            status_code=503,
            detail="RPA module not available"
        )
    
    logger.info(f"🤖 [RPA] Quote request received: {request.job_id} for {request.insurer_name} - {request.product_code}")
    
    # Validate insurer exists (if not using config_yaml override)
    if not request.config_yaml:
        if request.insurer_name not in rpa_config.list_insurers():
            raise HTTPException(
                status_code=404,
                detail=f"Insurer '{request.insurer_name}' not found in loaded configurations"
            )
    
    # ===== NOTIFICATION: Job created =====
    await notify_job_status(
        job_id=request.job_id,
        event="created",
        insurer_name=request.insurer_name,
        product=request.product_code,
        input_payload={
            "license_plate": request.form_data.license_plate if request.form_data else None,
            "product_code": request.product_code,
            "insurer_name": request.insurer_name
        },
        status="queued"
    )
    
    # Queue background task
    background.add_task(rpa_quote_worker, request.job_id, request)
    rpa_requests_total.inc()
    
    # Return immediate acceptance response (NOT the final result)
    return RPAJobResponse(
        success=True,
        job_id=request.job_id,
        message="RPA job queued successfully",
        insurer=request.insurer_name,
        product=request.product_code
    )

@app.get("/rpa/stats", response_model=RPAStatsResponse)
async def rpa_stats_endpoint(username: str = Depends(verify_basic_auth)):
    """Get RPA module statistics and configuration"""
    if not RPA_MODULE_LOADED:
        raise HTTPException(
            status_code=503,
            detail="RPA module not available"
        )
    
    logger.info(f"🤖 [RPA] Stats requested")
    
    insurers = rpa_config.list_insurers()
    
    # Build products by insurer
    products_by_insurer = {}
    for insurer_name in insurers:
        try:
            config = rpa_config.get_config(insurer_name)
            products_by_insurer[insurer_name] = list(config.get("workflows", {}).keys())
        except Exception:
            products_by_insurer[insurer_name] = []
    
    return RPAStatsResponse(
        rpa_version=RPA_VERSION,
        config={
            "total_insurers": len(insurers),
            "insurers": insurers,
            "last_reload": rpa_config.last_reload.isoformat() if rpa_config.last_reload else None,
            "cache_ttl_seconds": rpa_config.cache_ttl.total_seconds(),
            "products_by_insurer": products_by_insurer
        },
        metrics={
            "total_requests": int(rpa_requests_total._value.get()),
            "successful_requests": int(rpa_success_total._value.get()),
            "failed_requests": int(rpa_failures_total._value.get())
        },
        available_scrapers={
            "Allianz Maroc": True,
            "Atlanta Sanad": False,
            "AXA Assurance Maroc": False,
            "RMA Watanya": False,
            "Sanlam": False,
            "Wafa Assurance": False
        }
    )

@app.post("/rpa/reload-config", response_model=RPAReloadResponse)
async def rpa_reload_config_endpoint(
    request: ConfigReloadRequest,
    username: str = Depends(verify_basic_auth)
):
    """Reload RPA configurations from YAML files"""
    if not RPA_MODULE_LOADED:
        raise HTTPException(
            status_code=503,
            detail="RPA module not available"
        )
    
    logger.info(f"🤖 [RPA] Config reload requested by {username} (force={request.force})")
    
    try:
        old_count = len(rpa_config.list_insurers())
        errors = rpa_config.load_all_configs(force=request.force)
        new_count = len(rpa_config.list_insurers())
        
        return RPAReloadResponse(
            success=True,
            message=f"Reloaded {new_count} configurations (was {old_count})",
            configs_loaded=new_count,
            insurers=rpa_config.list_insurers(),
            errors=[]
        )
        
    except Exception as e:
        logger.error(f"❌ [RPA] Config reload failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Config reload failed: {str(e)}"
        )

# =========================
# RPA Config File Management Endpoints
# =========================

@app.get("/rpa/configs")
async def rpa_list_configs(username: str = Depends(verify_basic_auth)):
    """
    List all available YAML configuration files.
    Returns list of insurer names (without .yaml extension).
    """
    if not RPA_MODULE_LOADED:
        raise HTTPException(status_code=503, detail="RPA module not available")
    
    config_dir = Path("rpa/configs")
    if not config_dir.exists():
        return {"configs": [], "count": 0, "config_dir": str(config_dir)}
    
    configs = []
    for f in config_dir.glob("*.yaml"):
        if '.disabled' in f.name or '.backup' in f.name or '.old' in f.name or '.trash' in f.name:
            continue
        configs.append(f.stem)
    
    configs.sort()
    logger.info(f"🤖 [RPA] Listed {len(configs)} config files by {username}")
    
    return {
        "configs": configs,
        "count": len(configs),
        "config_dir": str(config_dir)
    }

@app.get("/rpa/configs/{insurer_name}")
async def rpa_read_config(insurer_name: str, username: str = Depends(verify_basic_auth)):
    """
    Read the content of a specific insurer's YAML configuration file.
    """
    if not RPA_MODULE_LOADED:
        raise HTTPException(status_code=503, detail="RPA module not available")
    
    safe_name = sanitize_insurer_name(insurer_name)
    if safe_name != insurer_name.lower().replace(' ', '_'):
        logger.warning(f"⚠️ [RPA] Suspicious insurer name rejected: {insurer_name}")
        raise HTTPException(status_code=400, detail="Invalid insurer name format")
    
    config_path = Path("rpa/configs") / f"{safe_name}.yaml"
    
    if not config_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Config file not found: {safe_name}.yaml"
        )
    
    try:
        content = config_path.read_text(encoding='utf-8')
        logger.info(f"🤖 [RPA] Read config for {safe_name} ({len(content)} bytes) by {username}")
        
        return {
            "insurer": safe_name,
            "file_path": str(config_path),
            "content": content,
            "size_bytes": len(content)
        }
    except Exception as e:
        logger.error(f"❌ [RPA] Failed to read config {safe_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read config: {str(e)}")

@app.put("/rpa/configs/{insurer_name}")
async def rpa_update_config(
    insurer_name: str,
    request: YAMLConfigUpdateRequest,
    username: str = Depends(verify_basic_auth)
):
    """
    Update an insurer's YAML configuration file.
    """
    if not RPA_MODULE_LOADED:
        raise HTTPException(status_code=503, detail="RPA module not available")
    
    safe_name = sanitize_insurer_name(insurer_name)
    if safe_name != insurer_name.lower().replace(' ', '_'):
        logger.warning(f"⚠️ [RPA] Suspicious insurer name rejected for update: {insurer_name}")
        raise HTTPException(status_code=400, detail="Invalid insurer name format")
    
    config_path = Path("rpa/configs") / f"{safe_name}.yaml"
    backup_path = Path("rpa/configs") / f"{safe_name}.yaml.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
        parsed_yaml = yaml.safe_load(request.content)
        if not parsed_yaml:
            raise HTTPException(status_code=400, detail="YAML content is empty or invalid")
        
        if 'insurer_name' not in parsed_yaml:
            raise HTTPException(status_code=400, detail="Missing required field: 'insurer_name'")
        if 'base_url' not in parsed_yaml:
            raise HTTPException(status_code=400, detail="Missing required field: 'base_url'")
        if 'workflows' not in parsed_yaml:
            raise HTTPException(status_code=400, detail="Missing required field: 'workflows'")
            
    except yaml.YAMLError as e:
        logger.error(f"❌ [RPA] Invalid YAML syntax for {safe_name}: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid YAML syntax: {str(e)}")
    
    backup_created = None
    try:
        if config_path.exists():
            existing_content = config_path.read_text(encoding='utf-8')
            backup_path.write_text(existing_content, encoding='utf-8')
            backup_created = backup_path.name
            logger.info(f"📦 [RPA] Created backup: {backup_path.name}")
        
        config_path.write_text(request.content, encoding='utf-8')
        logger.info(f"✅ [RPA] Updated config for {safe_name} ({len(request.content)} bytes) by {username}")
        
        rpa_config.load_all_configs(force=True)
        configs_loaded = len(rpa_config.list_insurers())
        logger.info(f"🔄 [RPA] Configs reloaded after update ({configs_loaded} total)")
        
        return {
            "success": True,
            "insurer": safe_name,
            "file_path": str(config_path),
            "size_bytes": len(request.content),
            "backup_created": backup_created,
            "message": f"Config updated and reloaded for {safe_name}",
            "configs_loaded": configs_loaded
        }
        
    except Exception as e:
        logger.error(f"❌ [RPA] Failed to update config {safe_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")

# =========================
# Docker Execute Command Endpoint (NEW v3.16.0)
# =========================

@app.post("/rpa/execute-command", response_model=ExecuteCommandResponse)
@app.post("/crawl4ai/rpa/execute-command", response_model=ExecuteCommandResponse)
async def execute_command_endpoint(
    request: ExecuteCommandRequest,
    username: str = Depends(verify_basic_auth)
):
    """
    Execute a whitelisted Docker command.
    
    Allowed actions:
    - build: docker-compose build [--no-cache] [service]
    - up: docker-compose up -d [service]
    - down: docker-compose down
    - restart: docker-compose restart [service]
    - logs: docker-compose logs --tail=N [service]
    - ps: docker-compose ps
    - docker-ps: docker ps [-a]
    - docker-logs: docker logs [--tail=N] <container>
    
    Security:
    - Strict whitelisting of actions, services, and arguments
    - All commands are logged for audit
    - Timeout protection (default 120s)
    - Output sanitization
    """
    docker_commands_total.inc()
    
    # Check if Docker commands are enabled
    if not ENABLE_DOCKER_COMMANDS:
        logger.warning(f"⚠️ [DOCKER] Command execution disabled, rejected request from {username}")
        return ExecuteCommandResponse(
            success=False,
            error="Docker command execution is disabled. Set ENABLE_DOCKER_COMMANDS=true to enable.",
            command=request.raw_command or f"{request.action} {request.service or ''}",
            executed_at=datetime.now().isoformat()
        )
    
    # Log the request
    logger.info(f"🐳 [DOCKER] Command request from {username}: action={request.action}, service={request.service}, args={request.args}")
    
    # Execute the command
    success, output, error = execute_docker_command_sync(
        action=request.action,
        service=request.service,
        args=request.args
    )
    
    return ExecuteCommandResponse(
        success=success,
        output=output if success else None,
        error=error if not success else None,
        command=request.raw_command or f"{request.action} {request.service or ''} {' '.join(request.args or [])}".strip(),
        executed_at=datetime.now().isoformat()
    )

# =========================
# Metrics & Shutdown
# =========================

@app.get("/metrics/prometheus")
async def prometheus_metrics(username: str = Depends(verify_basic_auth)):
    return Response(generate_latest(), media_type="text/plain")

@app.on_event("shutdown")
async def shutdown_event():
    await callback_manager.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
