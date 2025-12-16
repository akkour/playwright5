#!/usr/bin/env python3
"""
Test script pour vérifier le sélecteur de durée d'assurance Acheel
"""

import asyncio
from playwright.async_api import async_playwright

async def test_insurance_duration_selector():
    """Test le nouveau sélecteur de durée d'assurance"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        try:
            print('📍 Navigation vers Acheel...')
            await page.goto('https://www.acheel.com/subscribe/auto')
            await page.wait_for_timeout(3000)

            print('📍 Acceptation des cookies...')
            try:
                await page.click('button#didomi-notice-agree-button', timeout=5000)
            except:
                pass
            await page.wait_for_timeout(2000)

            print('📍 Remplissage plaque d\'immatriculation...')
            await page.fill("input[type='text']", 'EW-137-XR')
            await page.wait_for_timeout(1000)

            print('📍 Clic RECHERCHER...')
            await page.click("div.w-full > button")
            await page.wait_for_timeout(5000)

            print('📍 Attente résultats véhicule...')
            await page.wait_for_selector('text=Marque & Modèle', timeout=15000)
            await page.wait_for_timeout(2000)

            print('📍 Navigation à travers le formulaire...')
            # Continue through form...
            await page.click("button:has-text('je continue')")
            await page.wait_for_timeout(3000)

            await page.click("button:has-text('non')")
            await page.wait_for_timeout(3000)

            await page.click("button:has-text('1.6 DCI 130 STYLE EDITION')")
            await page.wait_for_timeout(4000)

            await page.click('text=Oui, c')
            await page.wait_for_timeout(5000)

            # Clic OUI (assuré)
            await page.evaluate('''() => {
                const divs = Array.from(document.querySelectorAll('div'));
                const oui = divs.find(d => d.textContent.trim() === 'Oui' && d.getBoundingClientRect().width > 0);
                if (oui) oui.click();
            }''')
            await page.wait_for_timeout(5000)

            await page.fill('input#purchase_date', '2020-01-15')
            await page.wait_for_timeout(2000)

            # Continue buttons
            await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const target = btns.find(b => b.textContent.toLowerCase().includes('continue'));
                if (target) target.click();
            }''')
            await page.wait_for_timeout(5000)

            # Skip to the insurance duration step...
            print('📍 Navigation rapide vers durée d\'assurance...')

            # Comptant ou don
            await page.click("div[role='button']:has-text('Comptant ou don')")
            await page.wait_for_timeout(3000)

            # Moi
            await page.click("div[role='button']:has-text('Moi')")
            await page.wait_for_timeout(3000)

            # Usage
            await page.click("div[role='button']:has-text('Privés et trajets travail')")
            await page.wait_for_timeout(3000)

            # Kilométrage
            await page.click('text=Entre 8000 et 20000 km')
            await page.wait_for_timeout(3000)

            # Garage
            await page.click("div[role='button']:has-text('Box ou garage fermé')")
            await page.wait_for_timeout(3000)

            # Adresse
            await page.fill("input[placeholder='N°, Rue, Ville']", '10 Avenue Mohammed V, Casablanca')
            await page.wait_for_timeout(2000)
            try:
                await page.click('li:first-of-type', timeout=2000)
            except:
                pass
            await page.wait_for_timeout(2000)

            # Continue
            await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const target = btns.find(b => b.textContent.toLowerCase().includes('continue'));
                if (target) target.click();
            }''')
            await page.wait_for_timeout(3000)

            # Driver info
            await page.click("button:has-text('Non')")  # Pas de conducteur secondaire
            await page.wait_for_timeout(3000)

            await page.click("div[role='button']:has-text('Un homme')")
            await page.wait_for_timeout(3000)

            await page.fill('input#drivers_birthday', '1990-05-15')
            await page.wait_for_timeout(2000)

            await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const target = btns.find(b => b.textContent.toLowerCase().includes('continue'));
                if (target) target.click();
            }''')
            await page.wait_for_timeout(3000)

            # Profession
            await page.click("div[role='button']:has-text('En activité professionnelle')")
            await page.wait_for_timeout(3000)

            await page.click("input[placeholder='Sélectionnez votre activité professionnelle…']")
            await page.wait_for_timeout(1000)

            await page.click("li:has-text('Fonctionnaire')")
            await page.wait_for_timeout(2000)

            await page.click("button:has-text('Non')")
            await page.wait_for_timeout(3000)

            # Permis
            await page.click("div[role='button']:has-text('Permis B')")
            await page.wait_for_timeout(3000)

            await page.fill('input#drivers_license_date', '2008-03-20')
            await page.wait_for_timeout(2000)

            await page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const target = btns.find(b => b.textContent.toLowerCase().includes('continue'));
                if (target) target.click();
            }''')
            await page.wait_for_timeout(3000)

            # Contrat
            await page.click("button:has-text('Non')")  # Contrat résilié
            await page.wait_for_timeout(3000)

            await page.click("button:has-text('Oui')")  # Conducteur assuré
            await page.wait_for_timeout(3000)

            await page.click("div[role='button']:has-text('Un an ou plus')")
            await page.wait_for_timeout(3000)

            await page.click("button:has-text('JE CONTINUE')")
            await page.wait_for_timeout(5000)

            # ===== TEST DU NOUVEAU SÉLECTEUR =====
            print('\n🎯 TEST DU SÉLECTEUR DE DURÉE D\'ASSURANCE')
            print('=' * 60)

            # D'abord, inspection complète de la page
            print('📍 Inspection de la page...')
            page_info = await page.evaluate('''() => {
                const h2 = document.querySelector('h2, h3');
                const question = document.querySelector('p, div[class*="question"]');
                const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
                const buttons = Array.from(document.querySelectorAll('button'));
                const divClickable = Array.from(document.querySelectorAll('div[role="button"]'));

                return {
                    title: h2 ? h2.textContent.trim() : 'N/A',
                    question: question ? question.textContent.trim().substring(0, 100) : 'N/A',
                    url: window.location.href,
                    inputs: inputs.map(i => ({
                        placeholder: i.placeholder || '',
                        value: i.value || '',
                        visible: i.getBoundingClientRect().width > 0
                    })),
                    buttons: buttons.map(b => b.textContent.trim()).filter(t => t.length > 0 && t.length < 30),
                    divClickable: divClickable.map(d => d.textContent.trim()).filter(t => t.length > 0 && t.length < 50)
                };
            }''')

            print(f'   URL: {page_info["url"]}')
            print(f'   Titre: {page_info["title"]}')
            print(f'   Question: {page_info["question"]}')
            print(f'   Inputs trouvés: {len(page_info["inputs"])}')
            for inp in page_info["inputs"]:
                print(f'      - placeholder="{inp["placeholder"]}" value="{inp["value"]}" visible={inp["visible"]}')
            print(f'   Buttons: {page_info["buttons"][:5]}')
            print(f'   Div clickables: {page_info["divClickable"][:5]}')

            await page.screenshot(path='/tmp/inspection.png', full_page=True)
            print('📸 Screenshot sauvegardé: /tmp/inspection.png')

            print('\n📍 Recherche de l\'input durée...')
            clicked = await page.evaluate('''() => {
                const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
                const target = inputs.find(i => i.placeholder && i.placeholder.includes('durée'));
                if (target) {
                    target.click();
                    target.focus();
                    return true;
                }
                return false;
            }''')

            if not clicked:
                print('❌ Pas d\'input trouvé - C\'est un système de boutons !')
                print('🔍 Recherche des boutons de durée...')

                # Rechercher tous les boutons et divs cliquables avec leur texte complet
                duration_options = await page.evaluate('''() => {
                    const elements = Array.from(document.querySelectorAll('button, div[role="button"], [class*="option"], [class*="choice"]'));
                    return elements
                        .filter(el => el.getBoundingClientRect().width > 0)
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            text: el.textContent.trim(),
                            classes: el.className,
                            hasYear: /\d+\s*(an|année)/i.test(el.textContent)
                        }))
                        .filter(el => el.text.length > 0 && el.text.length < 100);
                }''')

                print(f'📋 Options trouvées: {len(duration_options)}')
                for opt in duration_options[:20]:
                    year_marker = ' 📅' if opt['hasYear'] else ''
                    print(f'   {opt["tag"]}: "{opt["text"]}"{year_marker}')

                # Rechercher spécifiquement "1 à 2 ans"
                print('\n📍 Clic sur "1 à 2 ans"...')
                clicked_button = await page.evaluate('''() => {
                    const elements = Array.from(document.querySelectorAll('button, div[role="button"]'));
                    const target = elements.find(el => {
                        const text = el.textContent.trim();
                        return /1\s*à\s*2\s*ans?/i.test(text) && el.getBoundingClientRect().width > 0;
                    });
                    if (target) {
                        target.click();
                        return true;
                    }
                    return false;
                }''')

                if not clicked_button:
                    print('❌ Bouton "1 à 2 ans" non trouvé')
                    return False

                print('✅ Bouton cliqué avec succès')
                await page.wait_for_timeout(2000)

            print('📍 Vérification de la navigation...')
            current_url = page.url
            print(f'   URL: {current_url}')

            page_title = await page.evaluate('''() => {
                const h2 = document.querySelector('h2, h3');
                return h2 ? h2.textContent.trim() : 'N/A';
            }''')
            print(f'   Titre: {page_title}')

            await page.screenshot(path='/tmp/test_success.png', full_page=True)
            print('\n✅ TEST COMPLET RÉUSSI!')
            print('📸 Screenshot: /tmp/test_success.png')
            return True

        except Exception as e:
            print(f'\n❌ ERREUR: {e}')
            import traceback
            traceback.print_exc()
            await page.screenshot(path='/tmp/test_error.png')
            return False

        finally:
            await browser.close()

if __name__ == '__main__':
    success = asyncio.run(test_insurance_duration_selector())
    exit(0 if success else 1)


