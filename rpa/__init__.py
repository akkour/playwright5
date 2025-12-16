"""
RPA Module - Robotic Process Automation pour scraping d'assureurs
Version: 1.0.0

Module complet d'automatisation RPA pour VESPEO/Elya

Composants principaux:
- ConfigManager: Gestion des configurations YAML
- QuoteScraper: Moteur de scraping de devis
- BaseInsurer: Classe de base pour les scrapers
- Models: Pydantic models pour validation
- Exceptions: Gestion d'erreurs spécifiques

Usage:
    from rpa import quote_scraper, config_manager
    from rpa.models import RPAQuoteRequest, QuoteFormData
    
    request = RPAQuoteRequest(
        job_id="job_123",
        callback_url="https://...",
        product_code="auto",
        insurer_name="Allianz Maroc",
        form_data=QuoteFormData(driver_age=35, vehicle_brand="Renault"),
        config_yaml="..."
    )
    
    response = await quote_scraper.scrape_quote(request)
"""

__version__ = "1.0.0"
__author__ = "VESPEO Team"

# Imports principaux
from .config_manager import ConfigManager, config_manager
from .quote_scraper import QuoteScraper, quote_scraper
from .models import (
    RPAQuoteRequest,
    RPAQuoteResponse,
    QuoteFormData,
    QuoteResult,
    InsurerConfig,
    RPAStats,
    ConfigReloadRequest,
    ConfigReloadResponse
)
from .exceptions import (
    RPAException,
    ConfigurationError,
    WorkflowExecutionError,
    FormFillingError,
    ExtractionError,
    InsurerNotFoundError,
    ProductNotSupportedError,
    ValidationError,
    TimeoutError,
    NavigationError,
    SelectorNotFoundError,
    CaptchaDetectedError,
    PriceNotFoundError,
    SimulatorUnavailableError
)

# Insurers
from .insurers import (
    BaseInsurer,
    AllianzMarocScraper,
    create_scraper,
    register_scraper,
    list_available_scrapers
)

__all__ = [
    # Version
    '__version__',
    
    # Core managers
    'ConfigManager',
    'config_manager',
    'QuoteScraper',
    'quote_scraper',
    
    # Models
    'RPAQuoteRequest',
    'RPAQuoteResponse',
    'QuoteFormData',
    'QuoteResult',
    'InsurerConfig',
    'RPAStats',
    'ConfigReloadRequest',
    'ConfigReloadResponse',
    
    # Exceptions
    'RPAException',
    'ConfigurationError',
    'WorkflowExecutionError',
    'FormFillingError',
    'ExtractionError',
    'InsurerNotFoundError',
    'ProductNotSupportedError',
    'ValidationError',
    'TimeoutError',
    'NavigationError',
    'SelectorNotFoundError',
    'CaptchaDetectedError',
    'PriceNotFoundError',
    'SimulatorUnavailableError',
    
    # Insurers
    'BaseInsurer',
    'AllianzMarocScraper',
    'create_scraper',
    'register_scraper',
    'list_available_scrapers',
]
