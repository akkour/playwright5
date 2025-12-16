"""
RPA Allianz Maroc Scraper
Version: 1.0.0

Scraper spécifique pour Allianz Maroc
URL: https://www.allianz.ma
"""

import logging
from playwright.async_api import Page

from .base import BaseInsurer
from ..models import InsurerConfig, QuoteFormData, QuoteResult
from ..exceptions import ExtractionError, NavigationError

logger = logging.getLogger(__name__)


class AllianzMarocScraper(BaseInsurer):
    """Scraper pour Allianz Maroc"""
    
    def __init__(self, config: InsurerConfig):
        super().__init__(config)
        logger.info(f"Initialized AllianzMarocScraper")
    
    async def scrape_quote(
        self,
        page: Page,
        product_code: str,
        form_data: QuoteFormData
    ) -> QuoteResult:
        """
        Scrape un devis Allianz Maroc
        
        Stratégie:
        1. Utiliser le workflow YAML générique si disponible
        2. Sinon, utiliser la logique custom ci-dessous
        """
        try:
            # Récupérer le workflow pour ce produit
            workflow = self.config.workflows.get(product_code)
            
            if workflow:
                # Utiliser le workflow YAML générique
                logger.info(f"[{self.name}] Using YAML workflow for {product_code}")
                return await self.execute_workflow(page, workflow, form_data)
            else:
                # Logique custom (fallback)
                logger.warning(f"[{self.name}] No workflow for {product_code}, using custom logic")
                return await self._scrape_custom(page, product_code, form_data)
                
        except Exception as e:
            await self.handle_errors(e, page)
            raise
    
    async def _scrape_custom(
        self,
        page: Page,
        product_code: str,
        form_data: QuoteFormData
    ) -> QuoteResult:
        """
        Logique custom pour Allianz Maroc
        
        Cette méthode est un fallback si pas de workflow YAML.
        Dans un MVP, on privilégiera toujours les workflows YAML.
        """
        logger.info(f"[{self.name}] Starting custom scraping for {product_code}")
        
        if product_code == 'auto':
            return await self._scrape_auto_custom(page, form_data)
        else:
            raise ExtractionError(
                f"Product {product_code} not supported in custom mode",
                insurer=self.name
            )
    
    async def _scrape_auto_custom(self, page: Page, form_data: QuoteFormData) -> QuoteResult:
        """Scraping custom pour assurance auto"""
        
        # 1. Navigation
        simulator_url = f"{self.base_url}{self.config.simulator_path or '/particuliers/devis-auto'}"
        logger.info(f"[{self.name}] Navigating to: {simulator_url}")
        
        try:
            await page.goto(simulator_url, wait_until='domcontentloaded', timeout=30000)
        except Exception as e:
            raise NavigationError(f"Failed to reach simulator: {e}", insurer=self.name)
        
        # Détecter CAPTCHA
        if await self.detect_captcha(page):
            from ..exceptions import CaptchaDetectedError
            raise CaptchaDetectedError("CAPTCHA detected on Allianz simulator", insurer=self.name)
        
        # 2. Remplissage du formulaire
        # NOTE: Ces sélecteurs sont des EXEMPLES et doivent être vérifiés
        # sur le vrai site Allianz Maroc
        
        try:
            # Usage du véhicule
            if form_data.usage:
                logger.debug(f"[{self.name}] Selecting usage: {form_data.usage}")
                await page.select_option("select#usage", form_data.usage)
            
            # Marque
            if form_data.vehicle_brand:
                logger.debug(f"[{self.name}] Filling brand: {form_data.vehicle_brand}")
                await page.fill("input#brand", form_data.vehicle_brand)
            
            # Modèle
            if form_data.vehicle_model:
                logger.debug(f"[{self.name}] Filling model: {form_data.vehicle_model}")
                await page.fill("input#model", form_data.vehicle_model)
            
            # Âge du conducteur
            if form_data.driver_age:
                logger.debug(f"[{self.name}] Filling driver age: {form_data.driver_age}")
                await page.fill("input#driver_age", str(form_data.driver_age))
            
            # Soumettre
            logger.debug(f"[{self.name}] Submitting form")
            await page.click("button[type='submit']")
            
            # Attendre les résultats
            await page.wait_for_selector(".quote-result, .price-display", timeout=15000)
            
        except Exception as e:
            from ..exceptions import FormFillingError
            raise FormFillingError(f"Failed to fill form: {e}", insurer=self.name)
        
        # 3. Extraction des données
        try:
            # Prix mensuel
            price_monthly_text = await page.locator(".price-monthly, .monthly-price").first.text_content()
            price_monthly = self._parse_price(price_monthly_text)
            
            # Prix annuel
            price_yearly_text = await page.locator(".price-yearly, .annual-price").first.text_content()
            price_yearly = self._parse_price(price_yearly_text)
            
            # Référence (optionnelle)
            try:
                reference = await page.locator(".quote-reference, .ref-number").first.text_content()
            except:
                reference = None
            
            # Formule
            try:
                formula_name = await page.locator(".formula-name, .plan-name").first.text_content()
            except:
                formula_name = None
            
            logger.info(f"[{self.name}] Successfully extracted quote: {price_monthly} MAD/mois")
            
            return QuoteResult(
                price_monthly=price_monthly,
                price_yearly=price_yearly,
                currency="MAD",
                quote_reference=reference,
                formula_name=formula_name,
                coverage_details={
                    "Responsabilité civile": "Incluse",
                    "Dommages collision": "Inclus",
                    "Vol": "Inclus",
                    "Incendie": "Inclus"
                }
            )
            
        except Exception as e:
            raise ExtractionError(f"Failed to extract quote data: {e}", insurer=self.name)
