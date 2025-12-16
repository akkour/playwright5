"""
RPA Generic YAML Scraper
Version: 1.0.0

Scraper générique qui exécute les workflows YAML sans logique custom
"""

import logging
from playwright.async_api import Page

from .base import BaseInsurer
from ..models import InsurerConfig, QuoteFormData, QuoteResult
from ..exceptions import ProductNotSupportedError

logger = logging.getLogger(__name__)


class GenericYAMLScraper(BaseInsurer):
    """
    Scraper générique basé sur les workflows YAML
    
    Utilisé pour les assureurs qui n'ont pas encore de scraper spécifique
    mais dont le workflow YAML est suffisant.
    """
    
    def __init__(self, config: InsurerConfig):
        super().__init__(config)
        logger.info(f"Initialized GenericYAMLScraper for {self.name}")
    
    async def scrape_quote(
        self,
        page: Page,
        product_code: str,
        form_data: QuoteFormData
    ) -> QuoteResult:
        """
        Scrape un devis en utilisant uniquement le workflow YAML
        
        Args:
            page: Page Playwright
            product_code: Code du produit
            form_data: Données du formulaire
            
        Returns:
            Résultat du scraping
            
        Raises:
            ProductNotSupportedError si produit non configuré
        """
        logger.info(f"[{self.name}] Generic scraping for {product_code}")
        
        # Vérifier que le workflow existe
        if product_code not in self.config.workflows:
            available = list(self.config.workflows.keys())
            raise ProductNotSupportedError(
                f"Product '{product_code}' not configured for {self.name}. "
                f"Available products: {available}",
                insurer=self.name
            )
        
        try:
            # Récupérer le workflow
            workflow = self.config.workflows[product_code]
            
            # Exécuter le workflow générique
            result = await self.execute_workflow(page, workflow, form_data)
            
            logger.info(
                f"[{self.name}] Successfully scraped {product_code}: "
                f"{result.price_monthly or result.price_yearly} {result.currency}"
            )
            
            return result
            
        except Exception as e:
            await self.handle_errors(e, page)
            raise
