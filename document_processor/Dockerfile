# /document_processor/Dockerfile

# Utiliser une image Python officielle et légère
FROM python:3.10-slim

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Installer les dépendances système (crucial pour la conversion des PDF)
RUN apt-get update && apt-get install -y poppler-utils && rm -rf /var/lib/apt/lists/*

# Copier le fichier des dépendances
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# --- CORRECTION ---
# Copier TOUS les fichiers du répertoire (main.py, tasks.py, etc.)
# dans le répertoire de travail /app du conteneur.
COPY . .

# Exposer le port sur lequel l'API va écouter
EXPOSE 11236

# Commande pour démarrer le service web avec Uvicorn
# Cette commande est utilisée par le service 'web'. Le service 'worker'
# la remplace par sa propre commande Celery via le docker-compose.yml.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "11236"]
