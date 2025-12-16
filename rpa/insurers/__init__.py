"""
RPA Insurers Module - Factory pour créer les scrapers
Version: 1.0.0
"""

import logging
from typing import Dict, Type

from .base import BaseInsurer
from .allianz_maroc import AllianzMarocScraper
from ..models import InsurerConfig
from ..exceptions import InsurerNotFoundError

logger = logging.getLogger(__name__)


# Registry des scrapers disponibles
INSURER_SCRAPERS: Dict[str, Type[BaseInsurer]] = {
    "Allianz Maroc": AllianzMarocScraper,
    "Atlanta Sanad": None,  # À implémenter
    "AXA Assurance Maroc": None,  # À implémenter
    "RMA Watanya": None,  # À implémenter
    "Sanlam": None,  # À implémenter
    "Wafa Assurance": None,  # À implémenter
}


def create_scraper(config: InsurerConfig) -> BaseInsurer:
    """
    Factory pour créer un scraper à partir d'une configuration
    
    Args:
        config: Configuration de l'assureur
        
    Returns:
        Instance du scraper approprié
        
    Raises:
        InsurerNotFoundError si aucun scraper trouvé
    """
    insurer_name = config.insurer_name
    
    # Rechercher le scraper dans le registry
    scraper_class = INSURER_SCRAPERS.get(insurer_name)
    
    if scraper_class is None:
        # Scraper pas encore implémenté, utiliser un scraper générique
        logger.warning(
            f"No specific scraper found for '{insurer_name}', "
            f"will use GenericYAMLScraper"
        )
        from .generic import GenericYAMLScraper
        return GenericYAMLScraper(config)
    
    # Instancier le scraper
    logger.info(f"Creating scraper for {insurer_name}")
    return scraper_class(config)


def register_scraper(insurer_name: str, scraper_class: Type[BaseInsurer]):
    """
    Enregistre un nouveau scraper dans le registry
    
    Args:
        insurer_name: Nom de l'assureur
        scraper_class: Classe du scraper
    """
    INSURER_SCRAPERS[insurer_name] = scraper_class
    logger.info(f"Registered scraper for {insurer_name}")


def list_available_scrapers() -> Dict[str, bool]:
    """
    Liste tous les scrapers disponibles
    
    Returns:
        Dict {insurer_name: is_implemented}
    """
    return {
        name: (scraper_class is not None)
        for name, scraper_class in INSURER_SCRAPERS.items()
    }


__all__ = [
    'BaseInsurer',
    'AllianzMarocScraper',
    'create_scraper',
    'register_scraper',
    'list_available_scrapers',
    'INSURER_SCRAPERS'
]
