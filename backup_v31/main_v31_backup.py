"""
EvaRAG Enhanced Crawler Service v3.1
Service de crawling avec Playwright — version complète, sans régression.

Points clés:
- Endpoints exposés en double (compat):
  * /crawl4ai/health  et /health
  * /crawl4ai/crawl   et /crawl           (sync)
  * /crawl4ai/jobs    et /jobs            (async, avec callback + Bearer)
  * /monitor, /metrics, /metrics/prometheus, /export/{filename}
- Crawl "auto | static | rendered", BFS, depth & max_pages
- Nettoyage Unicode (suppression caractères de contrôle) pour sorties lisibles
- Extraction de liens côté navigateur (a.href) pour SPA
- Cache Redis optionnel
"""

from __future__ import annotations

import os
import re
import json
import time
import psutil
import hashlib
import asyncio
import aiofiles
from datetime import datetime
from collections import deque, defaultdict
from typing import List, Optional, Dict, Any, Tuple

from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import redis.asyncio as redis

from fastapi import (
    FastAPI, Request, HTTPException, BackgroundTasks, Header
)
from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, AnyHttpUrl

from prometheus_client import Counter, Histogram, Gauge, generate_latest

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# =========================
# Configuration & Globals
# =========================

APP_NAME = "EvaRAG Crawler Service"
APP_VERSION = "3.1.0"

# Compat avec les Edge Functions existantes
CRAWLER_WORKER_SECRET = os.getenv("CRAWLER_WORKER_SECRET", "")
DEFAULT_CALLBACK_URL = os.getenv("CRAWLER_CALLBACK_URL", "")

class Config:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    DEFAULT_NAV_TIMEOUT = 60_000
    STATIC_TIMEOUT = 30.0
    MAX_LINKS_RETURNED = 15         # pour l'affichage; la file BFS peut en pousser plus
    MAX_CONCURRENT_PAGES = 5
    MAX_RETRIES = 3
    CACHE_TTL = 3600
    MONITORING_INTERVAL = 5
    METRICS_RETENTION = 86400
    LOG_DIR = Path("logs")
    DATA_DIR = Path("data")

# Nettoyage caractères de contrôle (dont \x00) pour Postgres / affichage
SAFE_CTRL_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')

def safe_text(s: Any) -> str:
    if s is None:
        return ""
    if not isinstance(s, str):
        try:
            s = s.decode("utf-8", "ignore")
        except Exception:
            s = str(s)
    s = SAFE_CTRL_RE.sub("", s)
    return s.strip()

# =========================
# FastAPI app
# =========================

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Service de crawling avancé avec Playwright et monitoring temps réel",
)

# CORS permissif par défaut (adapter si besoin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Prometheus metrics
# =========================

crawl_requests_total = Counter("crawl_requests_total", "Total crawl requests")
crawl_success_total = Counter("crawl_success_total", "Successful crawls")
crawl_failures_total = Counter("crawl_failures_total", "Failed crawls")
pages_processed_total = Counter("pages_processed_total", "Total pages processed")
documents_created_total = Counter("documents_created_total", "Total documents created")

crawl_duration_seconds = Histogram("crawl_duration_seconds", "Crawl duration in seconds")
page_load_duration_seconds = Histogram("page_load_duration_seconds", "Page load duration")

active_crawls = Gauge("active_crawls", "Number of active crawls")
memory_usage_bytes = Gauge("memory_usage_bytes", "Memory usage in bytes")
cpu_usage_percent = Gauge("cpu_usage_percent", "CPU usage percentage")

# =========================
# Stats & Monitoring
# =========================

class CrawlStats:
    def __init__(self):
        self.reset_daily_stats()
        self.app_start_time = time.time()
        self.hourly_stats = defaultdict(lambda: {
            "requests": 0, "success": 0, "failed": 0, "pages": 0, "documents": 0
        })

    def reset_daily_stats(self):
        self.daily_stats = {
            "total_requests": 0,
            "successful_crawls": 0,
            "failed_crawls": 0,
            "total_pages_processed": 0,
            "total_pages_found": 0,
            "total_documents_created": 0,
            "last_request_time": None,
            "total_processing_time": 0.0,
            "avg_response_time": 0.0,
            "strategies_used": defaultdict(int),
            "domains_crawled": set(),
            "errors_by_type": defaultdict(int),
        }

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.daily_stats:
                if isinstance(self.daily_stats[key], (int, float)):
                    self.daily_stats[key] += value
                elif isinstance(self.daily_stats[key], set):
                    self.daily_stats[key].add(value)
                else:
                    self.daily_stats[key] = value
        hour = datetime.now().strftime("%H:00")
        for key, value in kwargs.items():
            if key in ["requests", "success", "failed", "pages", "documents"]:
                self.hourly_stats[hour][key] += value

    def _format_uptime(self, seconds: float) -> str:
        d = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        m = int((seconds % 3600) // 60)
        if d > 0: return f"{d}d {h}h {m}m"
        if h > 0: return f"{h}h {m}m"
        return f"{m}m"

    def get_stats(self):
        uptime = time.time() - self.app_start_time
        total = self.daily_stats["total_requests"]
        success_rate = (self.daily_stats["successful_crawls"] / total * 100) if total else 0.0
        stats = self.daily_stats.copy()
        stats["domains_crawled"] = list(stats["domains_crawled"])
        stats["success_rate"] = round(success_rate, 2)
        stats["uptime_seconds"] = round(uptime, 2)
        stats["uptime_human"] = self._format_uptime(uptime)
        stats["hourly_stats"] = dict(self.hourly_stats)
        stats["system"] = {
            "memory_usage_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 2),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "disk_usage_percent": psutil.disk_usage("/").percent,
        }
        return stats

crawl_stats = CrawlStats()

# =========================
# Redis Cache (optionnel)
# =========================

class CacheManager:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.connected = False

    async def connect(self):
        try:
            self.redis = await redis.from_url(Config.REDIS_URL)
            await self.redis.ping()
            self.connected = True
            print("✅ Connected to Redis cache")
        except Exception as e:
            print(f"⚠️ Redis not available: {e}")
            self.connected = False

    async def get(self, key: str) -> Optional[str]:
        if not self.connected:
            return None
        try:
            v = await self.redis.get(key)
            return v.decode() if v else None
        except Exception:
            return None

    async def set(self, key: str, value: str, ttl: int = Config.CACHE_TTL):
        if not self.connected:
            return
        try:
            await self.redis.setex(key, ttl, value)
        except Exception:
            pass

    async def close(self):
        if self.redis:
            await self.redis.close()

cache_manager = CacheManager()

# =========================
# Pydantic Models
# =========================

class SiteOverride(BaseModel):
    pattern: str = Field(..., description="Pattern pour matcher l'URL")
    strategy: Optional[str] = Field(None, pattern="^(static|rendered|auto)$")
    wait_selector: Optional[str] = None
    sleep_after: Optional[float] = Field(None, ge=0, le=10)
    wait_until: Optional[str] = Field(None, pattern="^(load|domcontentloaded|networkidle|commit)$")
    include_html: Optional[bool] = None
    extract_text: Optional[bool] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=10000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=1000)

class CrawlRequest(BaseModel):
    urls: List[AnyHttpUrl] = Field(..., min_items=1, max_items=100)
    depth: int = Field(1, ge=0, le=5)
    max_pages: int = Field(10, ge=1, le=1000)

    strategy: str = Field("auto", pattern="^(auto|static|rendered)$")
    include_html_auto: bool = True
    render_js: bool = True

    wait_selector: Optional[str] = None
    sleep_after: float = Field(2.0, ge=0, le=10)
    wait_until: str = Field("networkidle", pattern="^(load|domcontentloaded|networkidle|commit)$")
    user_agent: Optional[str] = None
    locale: str = "fr-FR"
    viewport_width: int = Field(1366, ge=320, le=3840)
    viewport_height: int = Field(900, ge=240, le=2160)

    extract_text: bool = True
    include_html: bool = False
    chunk_size: int = Field(1000, ge=100, le=10000)
    chunk_overlap: int = Field(100, ge=0, le=1000)

    overrides: Optional[List[SiteOverride]] = None

    follow_redirects: bool = True
    ignore_robots: bool = False
    custom_headers: Optional[Dict[str, str]] = None
    cookies: Optional[Dict[str, str]] = None

    export_format: Optional[str] = Field(None, pattern="^(json|csv|html|markdown)$")

class CrawlResponse(BaseModel):
    pages: List[Dict[str, Any]]
    summary: Dict[str, Any]
    export_url: Optional[str] = None
    job_id: Optional[str] = None

# Job API (compat /crawl4ai/jobs)
class CrawlJobRequest(BaseModel):
    site_id: str
    organization_id: Optional[str] = None
    url: AnyHttpUrl
    depth: int = 2
    max_pages: int = 10
    render_js: bool = True
    extract_text: bool = True
    chunk_size: int = 1000
    chunk_overlap: int = 100
    callback_url: Optional[AnyHttpUrl] = None
    correlation_id: Optional[str] = None

# =========================
# Job Manager
# =========================

class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.job_results: Dict[str, Dict[str, Any]] = {}

    def create_job(self, request: CrawlRequest) -> str:
        job_id = hashlib.md5(f"{request.urls[0]}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        self.jobs[job_id] = {
            "id": job_id,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "request": request.dict(),
            "progress": 0,
            "total": request.max_pages,
            "current_url": None,
            "error": None,
        }
        return job_id

    def update_job(self, job_id: str, **kwargs):
        if job_id in self.jobs:
            self.jobs[job_id].update(kwargs)

    def complete_job(self, job_id: str, result: Dict):
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "completed"
            self.jobs[job_id]["completed_at"] = datetime.now().isoformat()
            self.job_results[job_id] = result

    def fail_job(self, job_id: str, error: str):
        if job_id in self.jobs:
            self.jobs[job_id]["status"] = "failed"
            self.jobs[job_id]["error"] = error
            self.jobs[job_id]["failed_at"] = datetime.now().isoformat()

    def get_job(self, job_id: str) -> Optional[Dict]:
        return self.jobs.get(job_id)

    def get_job_result(self, job_id: str) -> Optional[Dict]:
        return self.job_results.get(job_id)

    def list_jobs(self, limit: int = 20) -> List[Dict]:
        jobs_list = list(self.jobs.values())
        jobs_list.sort(key=lambda x: x["created_at"], reverse=True)
        return jobs_list[:limit]

job_manager = JobManager()

# =========================
# Helpers
# =========================

def _absolute_dedup(base_url: str, hrefs: List[str]) -> List[str]:
    seen = set()
    out = []
    for h in hrefs or []:
        try:
            if not h:
                continue
            absolute = urljoin(base_url, h)
            parsed = urlparse(absolute)
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean += f"?{parsed.query}"
            if clean not in seen:
                seen.add(clean)
                out.append(clean)
        except Exception:
            continue
    return out

def detect_spa_by_html(html: str) -> bool:
    spa_indicators = [
        r'<div[^>]*\sid=["\']root["\']', r'<div[^>]*\sid=["\']app["\']',
        r'__NEXT_DATA__', r'window\.__NUXT__',
        r'ng-app', r'data-ng-app', r'<router-outlet',
        r'window\.Vue', r'window\.angular', r'React\.createElement', r'_app\.mount\('
    ]
    for pattern in spa_indicators:
        if re.search(pattern, html, re.IGNORECASE):
            return True
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(strip=True)
    return len(text) < 100 and len(html) > 5000

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup(["script", "style", "meta", "link", "noscript"]):
        el.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def apply_overrides_for_url(url: str, req: CrawlRequest) -> Dict[str, Any]:
    opts = {
        "strategy": req.strategy,
        "wait_selector": req.wait_selector,
        "sleep_after": req.sleep_after,
        "wait_until": req.wait_until,
        "include_html": req.include_html,
        "extract_text": req.extract_text,
        "chunk_size": req.chunk_size,
        "chunk_overlap": req.chunk_overlap,
    }
    if req.overrides:
        for o in req.overrides:
            if o.pattern and o.pattern.lower() in url.lower():
                d = o.dict(exclude_none=True)
                for k, v in d.items():
                    if k != "pattern":
                        opts[k] = v
    return opts

# =========================
# Fetchers
# =========================

async def fetch_static(url: str, ua: Optional[str], headers: Optional[Dict] = None) -> Tuple[str, str]:
    default_headers = {
        "User-Agent": ua or ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if headers:
        default_headers.update(headers)
    async with httpx.AsyncClient(follow_redirects=True, timeout=Config.STATIC_TIMEOUT, verify=False) as client:
        resp = await client.get(url, headers=default_headers)
        resp.raise_for_status()
        # httpx gère la décompression; on sécurise le texte
        html = resp.text if isinstance(resp.text, str) else resp.content.decode("utf-8", "ignore")
        return str(resp.url), safe_text(html)

async def render_playwright(context, url: str, opts: Dict[str, Any]) -> Tuple[str, str, str, List[str]]:
    page = await context.new_page()
    page.set_default_navigation_timeout(Config.DEFAULT_NAV_TIMEOUT)
    page.set_default_timeout(Config.DEFAULT_NAV_TIMEOUT)
    try:
        await page.goto(url, wait_until=opts.get("wait_until", "networkidle"), timeout=Config.DEFAULT_NAV_TIMEOUT)
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeoutError:
            pass
        if opts.get("wait_selector"):
            try:
                await page.wait_for_selector(opts["wait_selector"], timeout=15_000)
            except PlaywrightTimeoutError:
                pass
        # scroll pour lazy-load
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.2)
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        # Attente d'ancres si possible
        try:
            await page.wait_for_selector("a[href]", timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        html = await page.content()
        title = await page.title()
        current_url = page.url

        # Extraction SPA-friendly: URLs absolues
        hrefs = await page.evaluate("() => Array.from(document.querySelectorAll('a[href]'), a => a.href)")
        links = _absolute_dedup(current_url, hrefs)

        return current_url, title, html, links
    finally:
        await page.close()

# =========================
# Crawl pipelines
# =========================

async def crawl_one_static(url: str, req: CrawlRequest, opts: Dict[str, Any]) -> Dict[str, Any]:
    try:
        t0 = time.time()
        final_url, html = await fetch_static(url, req.user_agent, req.custom_headers)
        soup = BeautifulSoup(html, "html.parser")
        title = safe_text(soup.title.string if soup.title and soup.title.string else "")
        hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
        links = _absolute_dedup(final_url, hrefs)

        item: Dict[str, Any] = {
            "url": final_url,
            "title": title,
            "links": links[:Config.MAX_LINKS_RETURNED],
            "strategy_used": "static",
            "load_time": round(time.time() - t0, 2),
        }
        if opts.get("extract_text", True):
            text = safe_text(html_to_text(html))
            item["text"] = text
            item["text_length"] = len(text)
            if opts.get("chunk_size"):
                item["chunks"] = chunk_text(text, opts["chunk_size"], opts["chunk_overlap"])
                item["chunks_count"] = len(item["chunks"])
        if opts.get("include_html", False) or req.include_html_auto:
            item["html"] = html[:5000]
        return item
    except Exception as e:
        return {"url": url, "error": str(e), "strategy_used": "static", "error_type": type(e).__name__}

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> List[str]:
    if not text or chunk_size <= 0:
        return []
    chunks = []
    start = 0
    L = len(text)
    while start < L:
        end = min(start + chunk_size, L)
        if end < L:
            for sep in [". ", "! ", "? ", "\n\n", "\n", " "]:
                p = text.rfind(sep, start + overlap, end)
                if p != -1:
                    end = p + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < L else end
    return chunks

async def crawl_one_rendered(context, url: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    try:
        t0 = time.time()
        current_url, title, html, links = await render_playwright(context, url, opts)
        title = safe_text(title)
        item: Dict[str, Any] = {
            "url": current_url,
            "title": title,
            "links": links[:Config.MAX_LINKS_RETURNED],
            "strategy_used": "rendered",
            "load_time": round(time.time() - t0, 2),
        }
        if opts.get("extract_text", True):
            text = safe_text(html_to_text(html))
            item["text"] = text
            item["text_length"] = len(text)
            if opts.get("chunk_size"):
                item["chunks"] = chunk_text(text, opts["chunk_size"], opts["chunk_overlap"])
                item["chunks_count"] = len(item["chunks"])
        if opts.get("include_html", False):
            item["html"] = safe_text(html)[:5000]
        return item
    except Exception as e:
        return {"url": url, "error": str(e), "strategy_used": "rendered", "error_type": type(e).__name__}

async def crawl_one_auto(context, url: str, req: CrawlRequest, opts: Dict[str, Any]) -> Dict[str, Any]:
    try:
        cache_key = f"crawl:{hashlib.md5(url.encode()).hexdigest()}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return json.loads(cached)

        t0 = time.time()
        final_url, html = await fetch_static(url, req.user_agent, req.custom_headers)
        if not detect_spa_by_html(html):
            soup = BeautifulSoup(html, "html.parser")
            title = safe_text(soup.title.string if soup.title and soup.title.string else "")
            hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
            links = _absolute_dedup(final_url, hrefs)
            item: Dict[str, Any] = {
                "url": final_url,
                "title": title,
                "links": links[:Config.MAX_LINKS_RETURNED],
                "strategy_used": "static",
                "is_spa": False,
                "load_time": round(time.time() - t0, 2),
            }
            if opts.get("extract_text", True):
                text = safe_text(html_to_text(html))
                item["text"] = text
                item["text_length"] = len(text)
                if opts.get("chunk_size"):
                    item["chunks"] = chunk_text(text, opts["chunk_size"], opts["chunk_overlap"])
                    item["chunks_count"] = len(item["chunks"])
            if opts.get("include_html", False) or req.include_html_auto:
                item["html"] = html[:5000]
            await cache_manager.set(cache_key, json.dumps(item))
            return item
        else:
            current_url, title, html, links = await render_playwright(context, url, opts)
            title = safe_text(title)
            item: Dict[str, Any] = {
                "url": current_url,
                "title": title,
                "links": links[:Config.MAX_LINKS_RETURNED],
                "strategy_used": "rendered",
                "is_spa": True,
                "load_time": round(time.time() - t0, 2),
            }
            if opts.get("extract_text", True):
                text = safe_text(html_to_text(html))
                item["text"] = text
                item["text_length"] = len(text)
                if opts.get("chunk_size"):
                    item["chunks"] = chunk_text(text, opts["chunk_size"], opts["chunk_overlap"])
                    item["chunks_count"] = len(item["chunks"])
            if opts.get("include_html", False):
                item["html"] = safe_text(html)[:5000]
            await cache_manager.set(cache_key, json.dumps(item))
            return item
    except Exception as e:
        return {"url": url, "error": str(e), "strategy_used": "auto", "error_type": type(e).__name__}

# =========================
# Core crawl (sync)
# =========================

async def crawl_sync(req: CrawlRequest) -> CrawlResponse:
    results: List[Dict[str, Any]] = []
    count = 0
    total_pages_found = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent=(req.user_agent or
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
            locale=req.locale,
            viewport={"width": req.viewport_width, "height": req.viewport_height},
            extra_http_headers=req.custom_headers or {},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        queue = deque([(str(u), 0) for u in req.urls])
        seen = set()

        while queue and count < req.max_pages:
            url, level = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            opts = apply_overrides_for_url(url, req)
            strategy = (opts.get("strategy") or "auto").lower()

            if strategy == "static":
                item = await crawl_one_static(url, req, opts)
            elif strategy == "rendered":
                if not req.render_js:
                    item = {"url": url, "error": "Rendered strategy requested but render_js is False", "strategy_used": "rendered"}
                else:
                    item = await crawl_one_rendered(context, url, opts)
            else:
                item = await crawl_one_auto(context, url, req, opts)

            crawl_stats.update(strategies_used={item.get("strategy_used", "unknown"): 1})
            results.append(item)
            count += 1
            pages_processed_total.inc()
            crawl_stats.update(total_pages_processed=1)

            # Empiler TOUS les liens (BFS) pour exploration; l'item peut n'en afficher que 15
            if isinstance(item, dict) and "links" in item and level < req.depth:
                links_found = len(item["links"])
                total_pages_found += links_found
                crawl_stats.update(total_pages_found=links_found)
                for link in item["links"]:
                    if link not in seen and len(seen) + len(queue) < req.max_pages * 5:
                        queue.append((link, level + 1))

        await context.close()
        await browser.close()

    summary = {
        "total_pages": count,
        "total_links_found": total_pages_found,
        "successful": sum(1 for r in results if "error" not in r),
        "failed": sum(1 for r in results if "error" in r),
        "strategies": dict(crawl_stats.daily_stats["strategies_used"]),
        "duration_seconds": round(time.time() - crawl_stats.app_start_time, 2),
    }

    export_url = None
    if req.export_format:
        export_url = await export_results(results, req.export_format)

    crawl_stats.update(total_documents_created=len(results))
    documents_created_total.inc(len(results))

    return CrawlResponse(pages=results, summary=summary, export_url=export_url)

# =========================
# Async job runner + callbacks
# =========================

async def post_callback(callback_url: str, payload: Dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(callback_url, json=payload)
        except Exception:
            pass

async def crawl_async(req: CrawlRequest, job_id: str):
    try:
        job_manager.update_job(job_id, status="running")
        result = await crawl_sync(req)
        job_manager.complete_job(job_id, result.dict())
    except Exception as e:
        job_manager.fail_job(job_id, str(e))

async def run_job_async(job: CrawlJobRequest, auth_org: Optional[str], bearer: Optional[str]) -> None:
    callback_url = str(job.callback_url or DEFAULT_CALLBACK_URL)
    # heartbeat initial si callback
    if callback_url:
        await post_callback(callback_url, {
            "success": True, "status": "running",
            "site_id": job.site_id, "organization_id": job.organization_id,
            "correlation_id": job.correlation_id,
            "pages_found": 0, "pages_crawled": 0, "documents_created": 0,
            "message": "Job started"
        })

    # Pass rapide (aperçu)
    quick_req = CrawlRequest(
        urls=[job.url], depth=max(0, job.depth - 1),
        max_pages=max(1, min(5, job.max_pages // 2)),
        render_js=job.render_js, extract_text=job.extract_text,
        chunk_size=job.chunk_size, chunk_overlap=job.chunk_overlap,
    )
    quick = await crawl_sync(quick_req)
    if callback_url:
        await post_callback(callback_url, {
            "success": True, "status": "running",
            "site_id": job.site_id, "organization_id": job.organization_id,
            "correlation_id": job.correlation_id,
            "pages_found": quick.summary.get("total_links_found", 0),
            "pages_crawled": quick.summary.get("total_pages", 0),
            "documents_created": len(quick.pages),
            "partial": True, "batch": quick.pages, "message": "Partial progress"
        })

    # Pass complet
    full_req = CrawlRequest(
        urls=[job.url], depth=job.depth, max_pages=job.max_pages,
        render_js=job.render_js, extract_text=job.extract_text,
        chunk_size=job.chunk_size, chunk_overlap=job.chunk_overlap,
    )
    full = await crawl_sync(full_req)
    if callback_url:
        await post_callback(callback_url, {
            "success": True, "status": "completed",
            "site_id": job.site_id, "organization_id": job.organization_id,
            "correlation_id": job.correlation_id,
            "pages_found": full.summary.get("total_links_found", 0),
            "pages_crawled": full.summary.get("total_pages", 0),
            "documents_created": len(full.pages),
            "result": {"pages": full.pages, "summary": full.summary},
            "message": "Job completed"
        })

# =========================
# Exports
# =========================

async def export_results(results: List[Dict], format: str) -> str:
    Config.DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"crawl_export_{ts}.{format}"
    filepath = Config.DATA_DIR / filename

    if format == "json":
        async with aiofiles.open(filepath, "w") as f:
            await f.write(json.dumps(results, indent=2, ensure_ascii=False))

    elif format == "csv":
        import csv, io
        output = io.StringIO()
        if results:
            writer = csv.DictWriter(output, fieldnames=sorted({k for r in results for k in r.keys()}))
            writer.writeheader()
            for r in results:
                writer.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
        async with aiofiles.open(filepath, "w") as f:
            await f.write(output.getvalue())

    elif format == "html":
        html_content = "<html><head><meta charset='utf-8'><title>Crawl Results</title></head><body>"
        html_content += "<h1>Crawl Results</h1>"
        for r in results:
            html_content += f"<div><h2>{safe_text(r.get('title','No title'))}</h2>"
            u = safe_text(r.get('url',''))
            html_content += f"<p>URL: <a href='{u}'>{u}</a></p>"
            if 'text' in r:
                t = safe_text(r['text'])
                html_content += f"<p>{t[:500]}...</p>"
            html_content += "</div><hr>"
        html_content += "</body></html>"
        async with aiofiles.open(filepath, "w") as f:
            await f.write(html_content)

    elif format == "markdown":
        md = "# Crawl Results\n\n"
        for r in results:
            md += f"## {safe_text(r.get('title','No title'))}\n\n"
            u = safe_text(r.get('url',''))
            md += f"**URL:** [{u}]({u})\n\n"
            if 'text' in r:
                md += f"{safe_text(r['text'])[:500]}...\n\n"
            md += "---\n\n"
        async with aiofiles.open(filepath, "w") as f:
            await f.write(md)

    return f"/export/{filename}"

# =========================
# Startup / Shutdown
# =========================

@app.on_event("startup")
async def startup_event():
    Config.LOG_DIR.mkdir(exist_ok=True)
    Config.DATA_DIR.mkdir(exist_ok=True)
    await cache_manager.connect()
    print(f"🚀 {APP_NAME} {APP_VERSION} started")
    print("📊 Monitoring at /monitor   |  📈 Metrics at /metrics")

@app.on_event("shutdown")
async def shutdown_event():
    await cache_manager.close()
    print("👋 Crawler Service stopped")

# =========================
# HTTP Endpoints (root)
# =========================

@app.get("/")
async def root():
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "status": "online",
        "documentation": "/docs",
        "monitoring": "/monitor",
        "metrics": "/metrics",
    }

@app.get("/health")
async def health():
    memory = psutil.Process().memory_info().rss / 1024 / 1024
    cpu = psutil.cpu_percent(interval=0.1)
    status = "healthy"
    if memory > 1000 or cpu > 80:
        status = "warning"
    return {
        "status": status,
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - crawl_stats.app_start_time, 2),
        "uptime_human": crawl_stats._format_uptime(time.time() - crawl_stats.app_start_time),
        "memory_mb": round(memory, 2),
        "cpu_percent": cpu,
        "cache_connected": cache_manager.connected,
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/metrics")
async def metrics():
    stats = crawl_stats.get_stats()
    memory_usage_bytes.set(stats["system"]["memory_usage_mb"] * 1024 * 1024)
    cpu_usage_percent.set(stats["system"]["cpu_percent"])
    return JSONResponse(stats)

@app.get("/metrics/prometheus")
async def prometheus_metrics():
    return Response(content=generate_latest(), media_type="text/plain")

@app.get("/export/{filename}")
async def get_export(filename: str):
    filepath = Config.DATA_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return StreamingResponse(
        open(filepath, "rb"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@app.get("/monitor")
async def monitor():
    # Simple fallback si le fichier n'existe pas
    path = Path("monitoring_dashboard.html")
    if not path.exists():
        html = "<html><body><h1>EvaRAG Crawler Monitoring</h1><pre id='stats'></pre><script>fetch('/metrics').then(r=>r.json()).then(j=>{document.getElementById('stats').textContent = JSON.stringify(j,null,2)})</script></body></html>"
        return HTMLResponse(content=html)
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# ---- Sync crawl ----
@app.post("/crawl")
async def crawl_endpoint(req: CrawlRequest, background_tasks: BackgroundTasks):
    crawl_stats.update(total_requests=1, domains_crawled=urlparse(str(req.urls[0])).netloc)
    crawl_stats.daily_stats["last_request_time"] = datetime.now().isoformat()
    crawl_requests_total.inc()
    try:
        with active_crawls.track_inprogress():
            with crawl_duration_seconds.time():
                result = await crawl_sync(req)
        crawl_stats.update(successful_crawls=1, total_processing_time=result.summary["duration_seconds"])
        crawl_success_total.inc()
        return result
    except Exception as e:
        crawl_stats.update(failed_crawls=1, errors_by_type={type(e).__name__: 1})
        crawl_failures_total.inc()
        raise HTTPException(status_code=500, detail=str(e))

# ---- Jobs (async interne, sans callback) ----
@app.get("/jobs")
async def list_jobs(limit: int = 20):
    return job_manager.list_jobs(limit)

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "completed":
        job["result"] = job_manager.get_job_result(job_id)
    return job

# ---- Jobs (compat Edge: /crawl4ai/jobs) ----
@app.post("/jobs")
async def submit_job_compat(
    job: CrawlJobRequest,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    x_organization_id: Optional[str] = Header(default=None),
):
    if not CRAWLER_WORKER_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured (no CRAWLER_WORKER_SECRET).")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    if token != CRAWLER_WORKER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid bearer token.")
    if not job.callback_url and not DEFAULT_CALLBACK_URL:
        raise HTTPException(status_code=400, detail="callback_url is required (or set CRAWLER_CALLBACK_URL).")

    background.add_task(run_job_async, job, x_organization_id, authorization)
    return {
        "success": True,
        "status": "queued",
        "site_id": job.site_id,
        "organization_id": job.organization_id,
        "correlation_id": job.correlation_id,
        "message": "Job accepted",
    }

# =========================
# Aliases sous /crawl4ai/*
# =========================

from fastapi import APIRouter

router = APIRouter(prefix="/crawl4ai")

@router.get("/health")
async def health_alias():
    return await health()

@router.get("/metrics")
async def metrics_alias():
    return await metrics()

@router.get("/metrics/prometheus")
async def prometheus_alias():
    return await prometheus_metrics()

@router.get("/monitor")
async def monitor_alias():
    return await monitor()

@router.get("/export/{filename}")
async def export_alias(filename: str):
    return await get_export(filename)

@router.post("/crawl")
async def crawl_alias(req: CrawlRequest, background_tasks: BackgroundTasks):
    return await crawl_endpoint(req, background_tasks)

@router.get("/jobs")
async def jobs_list_alias(limit: int = 20):
    return await list_jobs(limit)

@router.get("/jobs/{job_id}")
async def jobs_get_alias(job_id: str):
    return await get_job(job_id)

@router.post("/jobs")
async def jobs_submit_alias(
    job: CrawlJobRequest,
    background: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    x_organization_id: Optional[str] = Header(default=None),
):
    return await submit_job_compat(job, background, authorization, x_organization_id)

app.include_router(router)

# =========================
# Entrypoint (docker CMD)
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "11235")),
        reload=False,
        workers=int(os.environ.get("UVICORN_WORKERS", "2")),
    )

