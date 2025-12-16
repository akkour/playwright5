# Plan d'implémentation du module RPA pour VESPEO

## 🎯 Objectif
Implémenter le module RPA manquant dans le service Playwright pour compléter l'architecture frontend/backend existante.

## 📋 Phase 1 : Infrastructure RPA (Priorité CRITIQUE)

### 1.1 Créer la structure du module RPA

```
/rpa/
├── __init__.py                    # Exports publics
├── config_manager.py              # Gestion des configs YAML
├── quote_scraper.py               # Moteur de scraping de devis
├── workflow_engine.py             # Orchestration des workflows
├── models.py                      # Pydantic models (QuoteRequest, QuoteResult)
├── exceptions.py                  # Exceptions custom
└── insurers/
    ├── __init__.py
    ├── base.py                    # Classe abstraite BaseInsurer
    ├── allianz_maroc.py           # Implémentation Allianz
    ├── atlanta_sanad.py           # Implémentation Atlanta Sanad
    ├── axa_maroc.py               # Implémentation AXA
    ├── rma_watanya.py             # Implémentation RMA Watanya
    ├── sanlam.py                  # Implémentation Sanlam
    └── wafa_assurance.py          # Implémentation Wafa
```

### 1.2 Ajouter les endpoints manquants dans main.py

```python
# Nouveaux endpoints RPA à ajouter
@app.post("/crawl4ai/rpa/quote")
async def rpa_quote_endpoint(...)
    """Lance un job de scraping de devis"""

@app.post("/crawl4ai/rpa/reload-config")
async def rpa_reload_config(...)
    """Recharge les configurations YAML depuis Supabase"""

@app.get("/crawl4ai/rpa/stats")
async def rpa_stats_endpoint(...)
    """Statistiques RPA (jobs, success rate, durées)"""
```

### 1.3 ConfigManager : Parser et valider les YAML

**Responsabilités :**
- Charger les configs depuis Supabase (table `insurers`)
- Parser et valider les YAML
- Hot-reload sur demande
- Cache en mémoire

**Schéma YAML attendu :**
```yaml
insurer_name: "Allianz Maroc"
base_url: "https://www.allianz.ma"
simulator_path: "/particuliers/devis-auto"
country: "MA"
complexity: 3
rating: 4.6

workflows:
  auto:
    steps:
      - action: navigate
        url: "{{base_url}}{{simulator_path}}"
      
      - action: fill_form
        selectors:
          usage: "#usage"
          brand: "#brand"
          model: "#model"
          driver_age: "#age"
        
      - action: wait_for
        selector: "#quote_result"
        timeout: 10000
      
      - action: extract
        fields:
          price_monthly: "#price_monthly"
          price_yearly: "#price_yearly"
          reference: "#quote_ref"

validation_rules:
  - field: driver_age
    min: 18
    max: 99
    required: true
```

## 📋 Phase 2 : Implémentation des scrapers (Priorité HAUTE)

### 2.1 BaseInsurer (Classe abstraite)

```python
from abc import ABC, abstractmethod
from playwright.async_api import Page

class BaseInsurer(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name = config['insurer_name']
        self.base_url = config['base_url']
    
    @abstractmethod
    async def scrape_auto_quote(self, page: Page, form_data: dict) -> dict:
        """Implémentation spécifique par assureur"""
        pass
    
    async def handle_errors(self, error: Exception) -> dict:
        """Gestion des erreurs commune"""
        pass
```

### 2.2 Exemple : AllianzMarocScraper

```python
class AllianzMarocScraper(BaseInsurer):
    async def scrape_auto_quote(self, page: Page, form_data: dict) -> dict:
        workflow = self.config['workflows']['auto']
        
        # Exécuter chaque step du workflow
        for step in workflow['steps']:
            if step['action'] == 'navigate':
                await page.goto(step['url'].replace('{{base_url}}', self.base_url))
            
            elif step['action'] == 'fill_form':
                await self._fill_form(page, step['selectors'], form_data)
            
            elif step['action'] == 'extract':
                return await self._extract_data(page, step['fields'])
        
        raise Exception("Workflow incomplet")
    
    async def _fill_form(self, page, selectors, data):
        # Remplir le formulaire
        pass
    
    async def _extract_data(self, page, fields):
        # Extraire les données
        pass
```

## 📋 Phase 3 : Intégration avec Edge Functions (Priorité HAUTE)

### 3.1 Flux complet

```
1. User → Frontend : Demande un devis auto
2. Frontend → Edge Function (rpa-quote) : POST /functions/v1/rpa-quote
3. Edge Function → Supabase : 
   - Crée quote_request
   - Récupère insurers actifs
   - Crée rpa_jobs pour chaque assureur
4. Edge Function → Playwright : POST /crawl4ai/rpa/quote (par assureur)
5. Playwright → RPA Module :
   - Charge config YAML depuis ConfigManager
   - Instancie le scraper approprié
   - Exécute le workflow
6. Playwright → Edge Function (rpa-callback) : POST /functions/v1/rpa-callback
7. Edge Function → Supabase :
   - Met à jour rpa_job (status: completed)
   - Crée quote
8. Supabase Realtime → Frontend : Mise à jour temps réel
```

### 3.2 Structure du payload

**Request (Edge → Playwright) :**
```json
{
  "job_id": "job_1736180123_a3f9",
  "callback_url": "https://xxx.supabase.co/functions/v1/rpa-callback",
  "product_code": "auto",
  "insurer_name": "Allianz Maroc",
  "form_data": {
    "driver_age": 35,
    "vehicle_brand": "Renault",
    "vehicle_model": "Clio",
    "usage": "private"
  },
  "config_yaml": "..." // Config complète de l'assureur
}
```

**Response (Playwright → Edge callback) :**
```json
{
  "status": "success",
  "job_id": "job_1736180123_a3f9",
  "result": {
    "price_monthly": 234.50,
    "price_yearly": 2345.00,
    "currency": "MAD",
    "coverage_details": {
      "Responsabilité civile": "Incluse",
      "Dommages collision": "Inclus"
    },
    "quote_reference": "REF-ALLIANZ-123456"
  },
  "duration_ms": 4532
}
```

## 📋 Phase 4 : Tests et stabilisation (Priorité MOYENNE)

### 4.1 Tests unitaires
- ConfigManager : parsing YAML, validation
- Chaque scraper : workflows, extraction

### 4.2 Tests d'intégration
- Flux complet Edge → Playwright → Callback
- Hot-reload de config
- Gestion d'erreurs

### 4.3 Monitoring
- Logs structurés
- Métriques Prometheus
- Dashboard admin (stats RPA)

## 🚨 Points critiques à valider

1. **Accès aux simulateurs** : Avez-vous des comptes de test pour chaque assureur ?
2. **Anti-bot** : Certains simulateurs ont-ils des protections (CAPTCHA, rate limiting) ?
3. **Environnement** : Playwright tourne déjà en production avec le main.py actuel ?
4. **Supabase schema** : Les tables (insurers, quotes, rpa_jobs) sont-elles déjà créées ?

## 📅 Estimation

- **Phase 1** : 2-3 jours (infrastructure + endpoints)
- **Phase 2** : 3-5 jours (6 scrapers × ~4-6h chacun)
- **Phase 3** : 1-2 jours (intégration + tests)
- **Phase 4** : 2-3 jours (stabilisation)

**TOTAL : 8-13 jours** pour un MVP fonctionnel avec 6 assureurs marocains.

## 🎯 Livrables

1. Module RPA complet et isolé
2. 6 scrapers fonctionnels (Allianz, Atlanta Sanad, AXA, RMA, Sanlam, Wafa)
3. Endpoints REST pour Edge Functions
4. Documentation technique
5. Scripts de test
6. Monitoring/logs

## 🔄 Approche itérative recommandée

1. **Sprint 0** (Phase 0) : Valider les accès aux simulateurs ⚠️
2. **Sprint 1** : Infrastructure RPA + 1 scraper pilote (ex: Allianz)
3. **Sprint 2** : 2-3 scrapers supplémentaires
4. **Sprint 3** : 3 derniers scrapers + stabilisation
5. **Sprint 4** : Tests, monitoring, doc

---

**Prochaine étape immédiate** : Créer le module `/rpa/` avec l'architecture de base et le premier endpoint `/crawl4ai/rpa/quote`.
