#!/bin/bash
# =============================================================================
# Patch automatique pour base.py - Extraction enrichie
# Version: 1.0.0
# =============================================================================

echo "=== Patch base.py pour extraction enrichie ==="

# 1. Copier le fichier original hors du container
docker cp playwright-crawler:/app/rpa/insurers/base.py ./base.py.original
echo "✅ Copié base.py original"

# 2. Créer le nouveau fichier base.py avec le patch
# On va chercher la ligne où commence _build_quote_result et remplacer tout jusqu'à _parse_price

python3 << 'PYTHON_SCRIPT'
import re

# Lire le fichier original
with open('base.py.original', 'r') as f:
    content = f.read()

# Nouveau code pour _build_quote_result
new_method = '''    def _build_quote_result(self, extracted_data: Dict[str, Any]) -> QuoteResult:
        """
        Construit un QuoteResult depuis les données extraites
        
        Supporte:
        - Format legacy (price_monthly, price_yearly, guarantees)
        - Format enrichi (extracted_json avec formules, commission, broker_fees)
        """
        import json
        
        # =====================================================================
        # 1. DETECTER ET PARSER LE JSON ENRICHI
        # =====================================================================
        enriched_data = {}
        formules = []
        
        if 'extracted_json' in extracted_data and extracted_data['extracted_json']:
            try:
                raw_json = extracted_data['extracted_json']
                if isinstance(raw_json, str):
                    enriched_data = json.loads(raw_json)
                else:
                    enriched_data = raw_json
                    
                formules = enriched_data.get('formules', [])
                logger.info(f"[{self.name}] Parsed enriched JSON: {len(formules)} formules")
                
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[{self.name}] Failed to parse extracted_json: {e}")
        
        # =====================================================================
        # 2. CONSTRUIRE quote_reference DEPUIS LES FORMULES
        # =====================================================================
        if formules:
            quote_ref_parts = []
            for f in formules:
                pm = f.get('price_monthly', 0)
                py = f.get('price_yearly', pm * 12)
                quote_ref_parts.append(f"{f['name']}:{pm}EUR/mois,{py}EUR/an")
            
            quote_reference = "|".join(quote_ref_parts)
            price_monthly = formules[0].get('price_monthly')
            price_yearly = formules[0].get('price_yearly')
            guarantees = "|".join(formules[0].get('guarantees', []))
            
        else:
            # =====================================================================
            # 3. FALLBACK: FORMAT LEGACY
            # =====================================================================
            price_monthly = self._parse_price(extracted_data.get('price_monthly'))
            price_yearly = self._parse_price(extracted_data.get('price_yearly'))
            quote_reference = extracted_data.get('reference') or extracted_data.get('quote_reference', '')
            guarantees = extracted_data.get('guarantees') or None
        
        # =====================================================================
        # 4. CONSTRUIRE LE COVERAGE_DETAILS ENRICHI
        # =====================================================================
        coverage_details = extracted_data.get('coverage') or {}
        
        if enriched_data:
            coverage_details = {
                'formules': formules,
                'commission': enriched_data.get('commission', {}),
                'broker_fees': enriched_data.get('broker_fees', {}),
                'insurer': enriched_data.get('insurer', self.name),
                'extraction_date': enriched_data.get('extraction_date'),
            }
        
        # =====================================================================
        # 5. CONSTRUIRE ET RETOURNER LE QUOTE RESULT
        # =====================================================================
        return QuoteResult(
            price_monthly=price_monthly,
            price_yearly=price_yearly,
            currency=extracted_data.get('currency') or 'EUR',
            quote_reference=quote_reference,
            guarantees=guarantees,
            coverage_details=coverage_details,
            deductible=self._parse_price(extracted_data.get('deductible')),
            valid_until=extracted_data.get('valid_until'),
            insurer_name=self.name
        )

'''

# Pattern pour trouver l'ancienne méthode
# On cherche de "def _build_quote_result" jusqu'à "def _parse_price"
pattern = r'(    def _build_quote_result\(self, extracted_data.*?)(\n    def _parse_price)'

# Remplacer
new_content = re.sub(pattern, new_method + r'\2', content, flags=re.DOTALL)

# Écrire le nouveau fichier
with open('base.py.patched', 'w') as f:
    f.write(new_content)

print("✅ Patch appliqué - base.py.patched créé")
PYTHON_SCRIPT

# 3. Copier le fichier patché dans le container
docker cp base.py.patched playwright-crawler:/app/rpa/insurers/base.py
echo "✅ Copié base.py patché dans le container"

# 4. Redémarrer le container
docker restart playwright-crawler
echo "✅ Container redémarré"

# 5. Attendre et vérifier
sleep 5
echo ""
echo "=== Vérification ==="
docker exec playwright-crawler grep -c "Parsed enriched JSON" /app/rpa/insurers/base.py
echo "Lignes trouvées (devrait être 1)"

# Nettoyage
rm -f base.py.original base.py.patched
echo ""
echo "✅ Patch terminé ! Testez maintenant le formulaire."
