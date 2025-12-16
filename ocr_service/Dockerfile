# Utiliser une image Python officielle et légère
FROM python:3.10-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Mettre à jour les paquets et installer Tesseract OCR + le pack de langue français
# C'est l'étape la plus importante pour l'auto-hébergement
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-fra && \
    rm -rf /var/lib/apt/lists/*

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY main.py .

# Exposer le port sur lequel l'API va écouter
EXPOSE 8000

# Commande pour démarrer l'application avec Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
