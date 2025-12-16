"""
RPA QuoteScraper - Moteur principal de scraping de devis
Version: 1.0.1 (Retry Fix C1-9)

CHANGELOG (C1-9):
- Fixed retry logic in _scrape_with_retry to create a new browser context
  and page for each attempt, preventing cookie/state bleed-over.
- scrape_quote now passes the browser object, not the page object.

Version: 1.0.0
Orchestre le processus complet de scraping:
1. Chargement de la configuration
2. Création du scraper approprié
3. Exécution du scraping
4. Gestion des erreurs et retry
"""

import asyncio
import logging
import time
from typing import Optional
from datetime import datetime

from playwright.async_api import (
    async_playwright, Page, Browser, BrowserContext, Error as PlaywrightError
)

from .models import RPAQuoteRequest, RPAQuoteResponse, QuoteResult, InsurerConfig
from .config_manager import config_manager
from .insurers import create_scraper
from .exceptions import (
    RPAException,
    TimeoutError as RPATimeoutError,
    ConfigurationError
)

logger = logging.getLogger(__name__)


class QuoteScraper:
    """Moteur principal de scraping de devis"""
    
    def __init__(self, config_manager_instance=config_manager, timeout=60):
        self.browser: Optional[Browser] = None
        self.playwright_instance = None
        self.config_manager = config_manager_instance
        self.default_timeout = timeout * 1000 # Convertir en ms
        logger.info("QuoteScraper initialized")

    
    async def scrape_quote(self, request: RPAQuoteRequest) -> RPAQuoteResponse:
        """
        Scrape un devis d'assurance
        
        Args:
            request: Requête de scraping
            
        Returns:
            Résultat du scraping
        """
        start_time = time.time()
        job_id = request.job_id
        
        logger.info(
            f"[Job {job_id}] Starting quote scraping: "
            f"{request.insurer_name} / {request.product_code}"
        )
        
        scraper = None
        
        try:
            # 1. Charger la configuration
            config = await self._load_config(request)
            
            # 2. Créer le scraper
            scraper = create_scraper(config)
            
            # 3. Initialiser Playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                
                try:
                    # 4. Exécuter le scraping avec retry
                    result = await self._scrape_with_retry(
                        scraper=scraper,
                        browser=browser, # <-- MODIFICATION (C1-9)
                        product_code=request.product_code,
                        form_data=request.form_data,
                        config=config,
                        request=request
                    )
                    
                    duration_ms = int((time.time() - start_time) * 1000)
                    
                    logger.info(
                        f"[Job {job_id}] ✅ Success in {duration_ms}ms: "
                        f"{result.price_monthly or result.price_yearly} EUR"
                    )
                    
                    return RPAQuoteResponse(
                        status="success",
                        job_id=job_id,
                        result=result,
                        duration_ms=duration_ms,
                        screenshots=scraper.screenshots
                    )
                
                finally:
                    await browser.close()
        
        except (RPATimeoutError, PlaywrightError) as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[Job {job_id}] ⏰ Timeout: {e}")
            
            return RPAQuoteResponse(
                status="timeout",
                job_id=job_id,
                error_message=str(e),
                duration_ms=duration_ms,
                screenshots=scraper.screenshots if scraper else []
            )
        
        except RPAException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[Job {job_id}] ❌ RPA Error: {e}")
            
            return RPAQuoteResponse(
                status="failed",
                job_id=job_id,
                error_message=str(e),
                duration_ms=duration_ms,
                screenshots=scraper.screenshots if scraper else []
            )
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[Job {job_id}] 💥 Unexpected error: {e}", exc_info=True)
            
            return RPAQuoteResponse(
                status="failed",
                job_id=job_id,
                error_message=f"Unexpected error: {str(e)}",
                duration_ms=duration_ms,
                screenshots=scraper.screenshots if scraper else []
            )
    
    async def _load_config(self, request: RPAQuoteRequest):
        """Charge la configuration de l'assureur"""
        try:
            # Option 1: Utiliser la config_yaml fournie dans la requête
            if request.config_yaml:
                logger.info(f"Loading config from request for {request.insurer_name}")
                return self.config_manager.load_config_from_string(
                    request.config_yaml,
                    request.insurer_name
                )
            
            # Option 2: Charger depuis le fichier local
            logger.info(f"Loading config from file for {request.insurer_name}")
            return self.config_manager.get_config(request.insurer_name)
            
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load config for {request.insurer_name}: {e}",
                insurer=request.insurer_name,
                job_id=request.job_id
            )
    
    async def _scrape_with_retry(
        self,
        scraper,
        browser: Browser, # <-- MODIFICATION (C1-9)
        product_code: str,
        form_data: dict,
        config: InsurerConfig,
        request: RPAQuoteRequest # Ajouté pour le timeout
    ) -> QuoteResult:
        """
        Exécute le scraping avec mécanisme de retry.
        CRÉE UNE NOUVELLE PAGE POUR CHAQUE TENTATIVE.
        """
        last_error = None
        
        for attempt in range(1, config.max_retries + 1):
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            
            try:
                logger.info(
                    f"[{scraper.name}] Attempt {attempt}/{config.max_retries} for {product_code}"
                )
                
                # --- MODIFICATION (C1-9) : Création isolée pour chaque tentative ---
                context = await browser.new_context(
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    locale='fr-FR',
                    timezone_id='Africa/Casablanca'
                )
                page = await context.new_page()
                # --- FIN DE LA MODIFICATION ---

                # Définir le timeout (utilise le timeout de la requête)
                page.set_default_timeout(request.timeout * 1000)
                
                # Exécuter le scraping
                result = await scraper.scrape_quote(
                    page=page,
                    product_code=request.product_code,
                    form_data=request.form_data
                )
                
                # Nettoyage en cas de succès
                if page: await page.close()
                if context: await context.close()
                
                return result # Succès
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"[{scraper.name}] Attempt {attempt} failed: {e}"
                )
                
                # Screenshot d'erreur (géré dans base.py mais au cas où)
                if page and config.screenshot_on_error:
                    try:
                        path = f"error_{scraper.name}_attempt_{attempt}.png"
                        await page.screenshot(path=path)
                        scraper.screenshots.append(path)
                        logger.info(f"[{scraper.name}] Error screenshot saved: {path}")
                    except Exception as se:
                        logger.error(f"[{scraper.name}] Failed to take error screenshot: {se}")

                # Si c'est la dernière tentative, lever l'erreur
                if attempt == config.max_retries:
                    logger.error(f"[{scraper.name}] All {config.max_retries} attempts failed.")
                    raise
                
                # Attendre avant retry (backoff exponentiel)
                wait_time = min(2 ** attempt, 10)  # Max 10 secondes
                logger.info(f"[{scraper.name}] Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
            
            finally:
                # --- MODIFICATION (C1-9) : Nettoyer la page/contexte ---
                if page and not page.is_closed():
                    await page.close()
                if context:
                    await context.close()
                # --- FIN DE LA MODIFICATION ---
        
        # Ne devrait jamais arriver ici
        raise last_error if last_error else RPAException("Unknown error in retry loop", insurer=scraper.name)


# Instance globale
quote_scraper = QuoteScraper(config_manager_instance=config_manager)
