# 🏆 Workflows RPA Validés

Ce dossier contient les workflows RPA testés et validés avec succès.

## Liste des workflows

| Fichier | Assureur | Produit | Date | Durée | Statut |
|---------|----------|---------|------|-------|--------|
| acheel_mrh.yaml | Acheel | MRH (Habitation) | 2025-12-12 | ~56s | ✅ 100% |

---

## 📋 Acheel MRH - Détails

### Payload de réponse (callback)
```json
{
  "status": "success",
  "job_id": "acheel_xxx",
  "result": {
    "price_monthly": 16.82,
    "price_yearly": 201.80,
    "currency": "EUR",
    "quote_reference": "STANDARD:16.82EUR/mois,201.80EUR/an|PREMIUM:22.35EUR/mois,268.25EUR/an",
    "guarantees": "Responsabilité Civile|Incendie et Risques Annexes|Catastrophe Naturelle et Technologique|Dégâts des Eaux|Protection Juridique|Défense Pénale et Recours|Événements climatiques|Assistance",
    "valid_until": "Standard:Responsabilité Civile|...|Premium(+):Vol et Vandalisme|Bris de Glace|Assistance Premium|Protection Juridique Étendue"
  },
  "duration_ms": 56134,
  "timestamp": "2025-12-12T21:10:33.195000"
}
```

### Parser les offres (Edge Function)
```typescript
function parseAcheelQuote(result: QuoteResult) {
  const offers = [];
  
  // Parse quote_reference: "STANDARD:16.82EUR/mois,201.80EUR/an|PREMIUM:22.35EUR/mois,268.25EUR/an"
  const parts = result.quote_reference?.split('|') || [];
  
  for (const part of parts) {
    const [name, prices] = part.split(':');
    const [monthly, yearly] = prices.split(',');
    
    offers.push({
      name: name,
      price_monthly: parseFloat(monthly.replace('EUR/mois', '')),
      price_yearly: parseFloat(yearly.replace('EUR/an', '')),
      currency: 'EUR'
    });
  }
  
  // Parse guarantees
  const standardGuarantees = result.guarantees?.split('|') || [];
  const premiumExtras = result.valid_until?.split('||')[1]?.replace('Premium(+):', '').split('|') || [];
  
  offers[0].guarantees = standardGuarantees;
  offers[1].guarantees = [...standardGuarantees, ...premiumExtras];
  offers[1].recommended = true;
  
  return offers;
}
```

### Offres détaillées

**Standard** : 16,82€/mois (201,80€/an)
- Responsabilité Civile
- Incendie et Risques Annexes  
- Catastrophe Naturelle et Technologique
- Dégâts des Eaux
- Protection Juridique
- Défense Pénale et Recours
- Événements climatiques
- Assistance

**Premium** : 22,35€/mois (268,25€/an) ⭐ Recommandé
- Toutes les garanties Standard +
- Vol et Vandalisme
- Bris de Glace
- Assistance Premium
- Protection Juridique Étendue

---

## 🚀 Utilisation
```bash
# 1. Copier le workflow vers le container
docker cp acheel_mrh.yaml playwright-crawler:/app/rpa/configs/acheel.yaml
docker restart playwright-crawler

# 2. Lancer un devis
curl -X POST http://localhost:30001/rpa/quote \
  -u admin:password \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "unique_id",
    "callback_url": "https://your-edge-function.supabase.co/functions/v1/rpa-callback",
    "product_code": "habitation",
    "insurer_name": "Acheel",
    "form_data": {}
  }'
```

---

## 📁 Structure des fichiers
```
validated/
├── README.md              # Cette documentation
├── acheel_mrh.yaml        # Workflow Acheel MRH validé
└── *.yaml.bak             # Sauvegardes datées
```
