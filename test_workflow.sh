#!/bin/bash

# 1. Copier le fichier YAML dans le conteneur
docker cp playwright-crawler/rpa/configs/acheel_recording_based.yaml playwright-crawler:/app/rpa/configs/acheel_recording_based.yaml

# 2. Valider le YAML
docker exec playwright-crawler python3 -c "
import yaml
with open('/app/rpa/configs/acheel_recording_based.yaml', 'r') as f:
    config = yaml.safe_load(f)
print('✅ YAML valide -', len(config.get('workflow', {}).get('steps', [])), 'étapes')
"

# 3. Exécuter le workflow avec logging complet
docker exec playwright-crawler python3 << 'PYTHON_SCRIPT'
import asyncio
import logging
from datetime import datetime

# Logging détaillé
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

async def run_test():
    from playwright.async_api import async_playwright
    from rpa.quote_scraper import QuoteScraper
    from rpa.models import RPAQuoteRequest
    
    logger.info("🚀 Démarrage du test workflow acheel_recording_based")
    
    request = RPAQuoteRequest(
        insurer_slug="acheel_recording_based",
        quote_data={
            "immatriculation": "EW137XR",
            "date_naissance": "15/03/1985",
            "date_permis": "20/06/2005",
            "nom": "Dupont",
            "prenom": "Jean",
            "email": "test@example.com",
            "telephone": "0612345678"
        }
    )
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        scraper = QuoteScraper()
        
        try:
            logger.info("📋 Lancement du scraping...")
            result = await scraper.scrape_quote(request, browser)
            logger.info(f"✅ SUCCÈS! Résultat: {result}")
            print("\n" + "="*60)
            print("RÉSULTAT FINAL:")
            print(result)
            print("="*60)
        except Exception as e:
            logger.error(f"❌ ÉCHEC: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

asyncio.run(run_test())
PYTHON_SCRIPT

# 4. Récupérer tous les screenshots générés
echo ""
echo "📸 Récupération des screenshots..."
mkdir -p /tmp/acheel_screenshots
docker cp playwright-crawler:/app/. /tmp/acheel_screenshots/ 2>/dev/null
ls -la /tmp/acheel_screenshots/*.png 2>/dev/null || echo "Aucun screenshot trouvé dans /app/"

# Chercher aussi dans d'autres emplacements possibles
docker exec playwright-crawler find /app -name "*.png" -mmin -10 2>/dev/null | while read f; do
    echo "Found: $f"
    docker cp "playwright-crawler:$f" /tmp/acheel_screenshots/
done

echo ""
echo "📁 Screenshots disponibles:"
ls -la /tmp/acheel_screenshots/*.png 2>/dev/null

