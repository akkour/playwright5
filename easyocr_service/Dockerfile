# Utiliser une image Python officielle
FROM python:3.10-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier et installer les dépendances Python
# Note: Le téléchargement de torch peut prendre plusieurs minutes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY . .

# Exposer le port interne du service
EXPOSE 8001

# Commande pour démarrer le service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
