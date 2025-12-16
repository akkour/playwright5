# 🤖 Module RPA - VESPEO/Elya

## 📋 Vue d'ensemble

Module RPA (Robotic Process Automation) pour le scraping automatisé de devis d'assurance sur les simulateurs marocains.

**Version**: 1.0.0  
**Status**: MVP - Phase 1 (Allianz Maroc implémenté)

### 🎯 Fonctionnalités

- ✅ Scraping de simulateurs d'assurance publics
- ✅ Workflows configurables via YAML
- ✅ Support multi-produits (auto, moto, habitation, etc.)
- ✅ Retry automatique avec backoff exponentiel
- ✅ Hot-reload de configuration
- ✅ Métriques Prometheus
- ✅ Screenshots de debug
- ✅ Isolation complète du crawler existant (zéro régression)

---

## 🏗️ Architecture

```
/rpa/
├── __init__.py              # Exports publics
├── models.py                # Pydantic models (validation)
├── exceptions.py            # Exceptions custom
├── config_manager.py        # Gestion des configs YAML
├── quote_scraper.py         # Moteur principal
├── insurers/
│   ├── __init__.py         # Factory de scrapers
│   ├── base.py             # BaseInsurer (classe abstraite)
│   ├── generic.py          # GenericYAMLScraper
│   └── allianz_maroc.py    # Scraper Allianz (implémenté)
└── configs/
    └── allianz_maroc.yaml  # Config Allianz
```

---

## 🚀 Démarrage rapide

### 1. Installation des dépendances

Le module RPA utilise les mêmes dépendances que le crawler Playwright existant, donc **aucune dépendance supplémentaire** n'est nécessaire.

### 2. Configuration d'un assureur

Créer un fichier YAML dans `/rpa/configs/` :

```yaml
# rpa/configs/allianz_maroc.yaml
insurer_name: "Allianz Maroc"
base_url: "https://www.allianz.ma"
simulator_path: "/particuliers/simulation"
country: "MA"
complexity: 3
rating: 4.6

workflows:
  auto:
    steps:
      - action: navigate
        url: "{{base_url}}{{simulator_path}}/auto"
      
      - action: fill_form
        selectors:
          driver_age: "#age"
          vehicle_brand: "#brand"
          vehicle_model: "#model"
      
      - action: click
        selector: "button[type='submit']"
        wait_after: 3000
      
      - action: extract
        fields:
          price_monthly: ".price-monthly"
          price_yearly: ".price-yearly"
          reference: ".quote-ref"
```

### 3. Démarrage du service

```bash
# Le service démarre automatiquement avec main.py
python main.py

# Ou avec Docker
docker-compose up -d
```

### 4. Tester l'endpoint RPA

```bash
curl -X POST http://localhost:8000/rpa/quote \
  -u admin:Hg.54.uyt.$$!!.xcv \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "test_123",
    "callback_url": "https://your-callback-url.com/rpa-callback",
    "product_code": "auto",
    "insurer_name": "Allianz Maroc",
    "form_data": {
      "driver_age": 35,
      "vehicle_brand": "Renault",
      "vehicle_model": "Clio",
      "usage": "private"
    },
    "config_yaml": "..."
  }'
```

---

## 📡 Endpoints API

### 1. POST `/rpa/quote` - Lancer un scraping de devis

**Authentification**: Basic Auth

**Request Body**:
```json
{
  "job_id": "job_1736180123_a3f9",
  "callback_url": "https://supabase.co/functions/v1/rpa-callback",
  "product_code": "auto",
  "insurer_name": "Allianz Maroc",
  "form_data": {
    "driver_age": 35,
    "vehicle_brand": "Renault",
    "vehicle_model": "Clio",
    "usage": "private"
  },
  "config_yaml": "...",
  "timeout": 60
}
```

**Response**:
```json
{
  "status": "queued",
  "job_id": "job_1736180123_a3f9",
  "duration_ms": 0,
  "timestamp": "2025-01-06T10:30:00Z"
}
```

**Callback (après exécution)**:
```json
{
  "status": "success",
  "job_id": "job_1736180123_a3f9",
  "result": {
    "price_monthly": 234.50,
    "price_yearly": 2345.00,
    "currency": "MAD",
    "coverage_details": {...},
    "quote_reference": "REF-123456"
  },
  "duration_ms": 4532,
  "screenshots": []
}
```

### 2. POST `/rpa/reload-config` - Recharger les configurations

**Authentification**: Basic Auth (admin)

**Request Body**:
```json
{
  "force": true
}
```

**Response**:
```json
{
  "success": true,
  "message": "Reloaded 6 configurations",
  "configs_loaded": 6,
  "insurers": ["Allianz Maroc", "Atlanta Sanad", ...],
  "timestamp": "2025-01-06T10:30:00Z"
}
```

### 3. GET `/rpa/stats` - Statistiques RPA

**Authentification**: Basic Auth

**Response**:
```json
{
  "rpa_version": "1.0.0",
  "config": {
    "total_insurers": 6,
    "insurers": ["Allianz Maroc", ...],
    "last_reload": "2025-01-06T10:00:00Z"
  },
  "metrics": {
    "total_requests": 42,
    "successful_requests": 38,
    "failed_requests": 4
  },
  "available_scrapers": {
    "Allianz Maroc": true,
    "Atlanta Sanad": false,
    ...
  }
}
```

---

## 🔧 Développement

### Ajouter un nouvel assureur

1. **Créer le fichier de configuration YAML** :

```yaml
# rpa/configs/atlanta_sanad.yaml
insurer_name: "Atlanta Sanad"
base_url: "https://www.atlantasanad.ma"
...
```

2. **(Optionnel) Créer un scraper spécifique** :

```python
# rpa/insurers/atlanta_sanad.py
from .base import BaseInsurer

class AtlantaSanadScraper(BaseInsurer):
    async def scrape_quote(self, page, product_code, form_data):
        # Logique custom si nécessaire
        workflow = self.config.workflows[product_code]
        return await self.execute_workflow(page, workflow, form_data)
```

3. **Enregistrer le scraper** :

```python
# rpa/insurers/__init__.py
from .atlanta_sanad import AtlantaSanadScraper

INSURER_SCRAPERS = {
    "Allianz Maroc": AllianzMarocScraper,
    "Atlanta Sanad": AtlantaSanadScraper,  # ✅ Ajouté
    ...
}
```

**Si pas de scraper spécifique** : Le `GenericYAMLScraper` sera automatiquement utilisé (il suffit du fichier YAML).

### Actions YAML disponibles

| Action | Description | Paramètres |
|--------|-------------|------------|
| `navigate` | Navigation vers URL | `url`, `timeout` |
| `wait` | Attente fixe | `duration` (ms) |
| `wait_for` | Attendre un sélecteur | `selector`, `timeout` |
| `fill_form` | Remplir formulaire | `selectors: {field: selector}` |
| `click` | Cliquer sur élément | `selector`, `wait_after` |
| `select` | Sélectionner option | `selector`, `field` |
| `extract` | Extraire données | `fields: {name: selector}` |
| `screenshot` | Prendre screenshot | `force` |
| `scroll` | Scroller la page | `direction`, `amount` |

---

## 🧪 Tests

### Test unitaire (avec pytest)

```python
# tests/test_config_manager.py
import pytest
from rpa import config_manager

def test_load_allianz_config():
    config = config_manager.get_config("Allianz Maroc")
    assert config.insurer_name == "Allianz Maroc"
    assert "auto" in config.workflows
```

### Test d'intégration (avec le service)

```bash
# Lancer le service
python main.py &

# Tester l'endpoint
pytest tests/integration/test_rpa_endpoints.py
```

---

## 📊 Monitoring

### Métriques Prometheus

Le module RPA expose les métriques suivantes sur `/metrics/prometheus` :

- `rpa_requests_total` : Nombre total de requêtes RPA
- `rpa_success_total` : Nombre de succès
- `rpa_failures_total` : Nombre d'échecs
- `rpa_duration_seconds` : Durée des scrapings (histogram)

### Logs

```python
logger.info(f"🤖 [RPA] Quote request for {insurer} / {product}")
logger.error(f"🤖 [RPA] Job {job_id} failed: {error}")
```

---

## ⚠️ Points d'attention

### Sélecteurs CSS

Les sélecteurs dans les fichiers YAML **doivent être mis à jour** après inspection manuelle des sites réels. Les exemples fournis sont **illustratifs**.

### Anti-bot

Certains simulateurs peuvent avoir des protections :
- CAPTCHA (détecté automatiquement)
- Rate limiting (géré par retry)
- User-Agent (randomisé)

### Conformité légale

✅ **Sites publics** : Tous les simulateurs ciblés sont des sites publics accessibles sans compte.

❌ **Extranets privés** : Pour Zéphir, Solly Azar, April (mentionnés dans les specs VESPEO pour le marché français), des **comptes de test** seront nécessaires.

---

## 🗺️ Roadmap

### Phase 1 (Actuel - MVP)
- ✅ Architecture RPA complète
- ✅ Allianz Maroc implémenté
- ✅ Endpoints API + callbacks
- ✅ Hot-reload config

### Phase 2 (Semaine 1-2)
- ⏳ Atlanta Sanad
- ⏳ AXA Assurance Maroc
- ⏳ RMA Watanya

### Phase 3 (Semaine 2-3)
- ⏳ Sanlam
- ⏳ Wafa Assurance
- ⏳ Tests d'intégration complets

### Phase 4 (Semaine 3-4)
- ⏳ Dashboard admin pour monitoring
- ⏳ Statistiques avancées
- ⏳ Gestion des erreurs enrichie

---

## 🤝 Intégration avec VESPEO

### Frontend → Backend → Playwright RPA

```
1. User clique "Comparer" sur le frontend
   ↓
2. Frontend → Edge Function (rpa-quote)
   POST /functions/v1/rpa-quote
   {
     product_code: "auto",
     form_data: {...},
     insurers: ["Allianz Maroc", "AXA", ...]
   }
   ↓
3. Edge Function → Supabase
   - Crée quote_request
   - Récupère configs YAML depuis table insurers
   - Crée rpa_jobs
   ↓
4. Edge Function → Playwright (pour chaque assureur)
   POST /rpa/quote
   {
     job_id: "job_123",
     callback_url: "https://.../rpa-callback",
     insurer_name: "Allianz Maroc",
     config_yaml: "...",
     form_data: {...}
   }
   ↓
5. Playwright RPA Module
   - Parse config YAML
   - Exécute workflow
   - Scrape devis
   ↓
6. Playwright → Edge Function (rpa-callback)
   POST /functions/v1/rpa-callback
   {
     status: "success",
     job_id: "job_123",
     result: {price_monthly: 234.50, ...}
   }
   ↓
7. Edge Function → Supabase
   - Met à jour rpa_job (completed)
   - Crée quote
   ↓
8. Supabase Realtime → Frontend
   Affichage temps réel du devis
```

### Schéma des tables Supabase

```sql
-- Table des assureurs
CREATE TABLE insurers (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  config_yaml TEXT NOT NULL,  -- Configuration YAML
  is_active BOOLEAN DEFAULT true,
  country TEXT DEFAULT 'MA',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table des demandes de devis
CREATE TABLE quote_requests (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES auth.users,
  product_code TEXT NOT NULL,
  form_data JSONB NOT NULL,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table des jobs RPA
CREATE TABLE rpa_jobs (
  id UUID PRIMARY KEY,
  job_id TEXT UNIQUE NOT NULL,
  quote_request_id UUID REFERENCES quote_requests,
  insurer_id UUID REFERENCES insurers,
  status TEXT DEFAULT 'queued',
  input_payload JSONB,
  output_result JSONB,
  error_message TEXT,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- Table des devis obtenus
CREATE TABLE quotes (
  id UUID PRIMARY KEY,
  quote_request_id UUID REFERENCES quote_requests,
  insurer_id UUID REFERENCES insurers,
  product_code TEXT NOT NULL,
  price_monthly DECIMAL,
  price_yearly DECIMAL,
  currency TEXT DEFAULT 'MAD',
  coverage_details JSONB,
  quote_reference TEXT,
  raw_data JSONB,
  scraped_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 📞 Support

**Équipe VESPEO**  
Pour toute question sur le module RPA : `contact@vespeo.fr`

**Documentation complète** : [Lien vers Notion/Confluence]

---

## 📄 Licence

Propriétaire - VESPEO © 2025
