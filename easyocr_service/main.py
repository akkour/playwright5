import io
from fastapi import FastAPI, UploadFile, File, HTTPException
import easyocr
from PIL import Image

# --- Initialisation ---
print("Chargement des modèles EasyOCR (français, anglais)...")
reader = easyocr.Reader(['fr', 'en'], gpu=False)
print("Modèles EasyOCR chargés.")

app = FastAPI(title="EasyOCR Service")

@app.post("/ocr", summary="Extraire le texte d'une image avec EasyOCR")
async def perform_easyocr(file: UploadFile = File(...)):
    print(f"EasyOCR: Reçu une requête pour le fichier {file.filename}")
    try:
        image_bytes = await file.read()
        result = reader.readtext(image_bytes, detail=0, paragraph=True)
        full_text = "\n".join(result)
        print(f"EasyOCR: Extraction terminée.")
        return {"filename": file.filename, "text": full_text}
    except Exception as e:
        print(f"EasyOCR: ERREUR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "EasyOCR", "languages": ["fr", "en"]}
