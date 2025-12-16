"""
RPA Exceptions - Exceptions personnalisées pour le module RPA
Version: 1.0.0
"""


class RPAException(Exception):
    """Exception de base pour toutes les erreurs RPA"""
    def __init__(self, message: str, insurer: str = None, job_id: str = None):
        self.message = message
        self.insurer = insurer
        self.job_id = job_id
        super().__init__(self.message)


class ConfigurationError(RPAException):
    """Erreur de configuration YAML"""
    pass


class WorkflowExecutionError(RPAException):
    """Erreur lors de l'exécution d'un workflow"""
    pass


class FormFillingError(RPAException):
    """Erreur lors du remplissage de formulaire"""
    pass


class ExtractionError(RPAException):
    """Erreur lors de l'extraction de données"""
    pass


class InsurerNotFoundError(RPAException):
    """Assureur non trouvé dans la configuration"""
    pass


class ProductNotSupportedError(RPAException):
    """Produit non supporté par l'assureur"""
    pass


class ValidationError(RPAException):
    """Erreur de validation des données"""
    pass


class TimeoutError(RPAException):
    """Timeout lors de l'exécution"""
    pass


class NavigationError(RPAException):
    """Erreur de navigation"""
    pass


class SelectorNotFoundError(RPAException):
    """Sélecteur introuvable sur la page"""
    def __init__(self, selector: str, insurer: str = None, job_id: str = None):
        message = f"Selector not found: {selector}"
        super().__init__(message, insurer, job_id)
        self.selector = selector


class CaptchaDetectedError(RPAException):
    """CAPTCHA détecté"""
    pass


class PriceNotFoundError(ExtractionError):
    """Prix non trouvé dans la page"""
    pass


class SimulatorUnavailableError(RPAException):
    """Simulateur indisponible"""
    pass

class ScrapingTimeoutError(RPAException):
    """Erreur de timeout lors du scraping"""
    def __init__(self, message: str, insurer: str = None, timeout: int = None):
        super().__init__(message, insurer)
        self.timeout = timeout
