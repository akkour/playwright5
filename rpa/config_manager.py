"""
RPA ConfigManager - Gestion des configurations YAML des assureurs
Version: 1.0.0

Responsabilités:
- Charger les configs depuis Supabase (si disponible) ou fichiers locaux
- Parser et valider les YAML
- Hot-reload sur demande
- Cache en mémoire
"""

import os
import yaml
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

from .models import InsurerConfig
from .exceptions import ConfigurationError, InsurerNotFoundError

logger = logging.getLogger(__name__)


class ConfigManager:
    """Gestionnaire de configurations RPA"""
    
    def __init__(self, config_dir: str = "rpa/configs"):
        self.config_dir = Path(config_dir)
        self.configs: Dict[str, InsurerConfig] = {}
        self.last_reload: Optional[datetime] = None
        self.cache_ttl = timedelta(hours=1)  # Cache de 1h
        
        # Créer le répertoire de configs si inexistant
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"ConfigManager initialized with directory: {self.config_dir}")
    
    def load_all_configs(self, force: bool = False) -> Dict[str, InsurerConfig]:
        """
        Charge toutes les configurations YAML
        
        Args:
            force: Forcer le rechargement même si cache valide
            
        Returns:
            Dict des configurations par nom d'assureur
        """
        # Vérifier si cache valide
        if not force and self.last_reload:
            cache_age = datetime.now() - self.last_reload
            if cache_age < self.cache_ttl:
                logger.info(f"Using cached configs (age: {cache_age.total_seconds():.0f}s)")
                return self.configs
        
        logger.info("Loading all insurer configurations...")
        configs_loaded = 0
        errors = []
        
        # Scanner le répertoire de configs
        yaml_files = list(self.config_dir.glob("*.yaml")) + list(self.config_dir.glob("*.yml"))
        
        for yaml_file in yaml_files:
            try:
                config = self._load_yaml_file(yaml_file)
                if config:
                    self.configs[config.insurer_name] = config
                    configs_loaded += 1
                    logger.info(f"✅ Loaded config for {config.insurer_name}")
            except Exception as e:
                error_msg = f"Failed to load {yaml_file.name}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        self.last_reload = datetime.now()
        
        logger.info(f"Loaded {configs_loaded} configurations")
        if errors:
            logger.warning(f"Encountered {len(errors)} errors during loading")
        
        return self.configs
    
    def _load_yaml_file(self, filepath: Path) -> Optional[InsurerConfig]:
        """Charge et valide un fichier YAML"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                yaml_data = yaml.safe_load(f)
            
            if not yaml_data:
                raise ConfigurationError(f"Empty YAML file: {filepath.name}")
            
            # Valider avec Pydantic
            config = InsurerConfig(**yaml_data)
            
            # Validations supplémentaires
            self._validate_config(config)
            
            return config
            
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML syntax in {filepath.name}: {str(e)}")
        except Exception as e:
            raise ConfigurationError(f"Error loading {filepath.name}: {str(e)}")
    
    def load_config_from_string(self, yaml_string: str, insurer_name: str) -> InsurerConfig:
        """
        Charge une configuration depuis une string YAML (pour Edge Functions)
        
        Args:
            yaml_string: Configuration YAML en string
            insurer_name: Nom de l'assureur
            
        Returns:
            Configuration validée
        """
        try:
            yaml_data = yaml.safe_load(yaml_string)
            
            if not yaml_data:
                raise ConfigurationError(f"Empty YAML for {insurer_name}")
            
            # S'assurer que le nom correspond
            if 'insurer_name' not in yaml_data:
                yaml_data['insurer_name'] = insurer_name
            
            config = InsurerConfig(**yaml_data)
            self._validate_config(config)
            
            # Mettre en cache
            self.configs[insurer_name] = config
            
            return config
            
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML syntax for {insurer_name}: {str(e)}")
        except Exception as e:
            raise ConfigurationError(f"Error parsing config for {insurer_name}: {str(e)}")
    
    def _validate_config(self, config: InsurerConfig):
        """Validations métier supplémentaires"""
        
        # Vérifier que base_url est valide
        if not config.base_url.startswith(('http://', 'https://')):
            raise ConfigurationError(f"Invalid base_url for {config.insurer_name}: must start with http:// or https://")
        
        # Vérifier qu'il y a au moins un workflow
        if not config.workflows:
            raise ConfigurationError(f"No workflows defined for {config.insurer_name}")
        
        # Valider la structure des workflows
        for product, workflow in config.workflows.items():
            if 'steps' not in workflow:
                raise ConfigurationError(f"Missing 'steps' in workflow '{product}' for {config.insurer_name}")
            
            if not isinstance(workflow['steps'], list):
                raise ConfigurationError(f"'steps' must be a list in workflow '{product}' for {config.insurer_name}")
            
            if len(workflow['steps']) == 0:
                raise ConfigurationError(f"Empty 'steps' in workflow '{product}' for {config.insurer_name}")
    
    def get_config(self, insurer_name: str) -> InsurerConfig:
        """
        Récupère la configuration d'un assureur
        
        Args:
            insurer_name: Nom de l'assureur
            
        Returns:
            Configuration de l'assureur
            
        Raises:
            InsurerNotFoundError si non trouvé
        """
        if insurer_name not in self.configs:
            # Tenter de charger si pas encore fait
            if not self.configs:
                self.load_all_configs()
            
            # Si toujours pas trouvé
            if insurer_name not in self.configs:
                raise InsurerNotFoundError(
                    f"Insurer '{insurer_name}' not found. Available: {list(self.configs.keys())}",
                    insurer=insurer_name
                )
        
        return self.configs[insurer_name]
    
    def get_workflow(self, insurer_name: str, product_code: str) -> Dict:
        """
        Récupère un workflow spécifique
        
        Args:
            insurer_name: Nom de l'assureur
            product_code: Code du produit (auto, moto, etc.)
            
        Returns:
            Configuration du workflow
        """
        config = self.get_config(insurer_name)
        
        if product_code not in config.workflows:
            raise ConfigurationError(
                f"Product '{product_code}' not supported by {insurer_name}. "
                f"Available: {list(config.workflows.keys())}",
                insurer=insurer_name
            )
        
        return config.workflows[product_code]
    
    def list_insurers(self) -> List[str]:
        """Liste tous les assureurs configurés"""
        if not self.configs:
            self.load_all_configs()
        return list(self.configs.keys())
    
    def list_products(self, insurer_name: str) -> List[str]:
        """Liste tous les produits supportés par un assureur"""
        config = self.get_config(insurer_name)
        return list(config.workflows.keys())
    
    def get_stats(self) -> Dict:
        """Statistiques sur les configurations"""
        return {
            "total_insurers": len(self.configs),
            "insurers": list(self.configs.keys()),
            "last_reload": self.last_reload.isoformat() if self.last_reload else None,
            "cache_ttl_seconds": self.cache_ttl.total_seconds(),
            "products_by_insurer": {
                name: list(config.workflows.keys())
                for name, config in self.configs.items()
            }
        }
    
    def reload(self, force: bool = True) -> Dict:
        """
        Recharge toutes les configurations
        
        Args:
            force: Forcer le rechargement
            
        Returns:
            Résultat du rechargement
        """
        logger.info("🔄 Reloading all configurations...")
        
        old_count = len(self.configs)
        self.configs.clear()
        
        try:
            self.load_all_configs(force=True)
            new_count = len(self.configs)
            
            return {
                "success": True,
                "message": f"Reloaded {new_count} configurations (was {old_count})",
                "configs_loaded": new_count,
                "insurers": list(self.configs.keys()),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to reload configs: {e}")
            return {
                "success": False,
                "message": f"Failed to reload: {str(e)}",
                "configs_loaded": 0,
                "insurers": [],
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }


# Instance globale (singleton)
config_manager = ConfigManager()
