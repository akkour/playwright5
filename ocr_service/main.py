import pytesseract
from fastapi import FastAPI, File, UploadFile, HTTPException
from PIL import Image
import io

# Initialisation de l'application FastAPI
app = FastAPI(title="Service OCR Auto-Hébergé")

@app.post("/ocr", summary="Extraire le texte d'une image")
async def perform_ocr(
    # 'file' est le nom du champ attendu dans la requête multipart/form-data
    file: UploadFile = File(...) 
):
    """
    Accepte une image, la traite avec Tesseract et retourne le texte extrait.
    """
    try:
        # 1. Lire les données de l'image en mémoire
        image_data = await file.read()
        
        # 2. Ouvrir l'image avec Pillow pour la préparer pour Pytesseract
        image = Image.open(io.BytesIO(image_data))
        
        # 3. Lancer Tesseract OCR sur l'image
        # On spécifie 'fra' pour le français. Ajoutez d'autres langues si besoin (ex: 'fra+eng')
        text = pytesseract.image_to_string(image, lang='fra')
        
        # 4. Retourner le résultat dans un format JSON propre
        return {"text": text.strip()}

    except Exception as e:
        # Gérer les erreurs potentielles (fichier corrompu, etc.)
        raise HTTPException(status_code=500, detail=f"Une erreur est survenue: {str(e)}")
