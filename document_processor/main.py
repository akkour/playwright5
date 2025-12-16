# /document_processor/main.py
from fastapi import FastAPI, UploadFile, File, Form
from tasks import process_document_task # Importe la tâche depuis le nouveau fichier tasks.py

app = FastAPI(title="Document Processing Service - Web API")

@app.post("/process-document-async", summary="Met une tâche de traitement en file d'attente")
async def process_document_async(
    job_id: str = Form(...),
    callback_url: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Reçoit une requête, la valide, et la transmet au worker Celery
    pour un traitement en arrière-plan. Répond immédiatement.
    """
    print(f"[Job {job_id}] Requête reçue pour {file.filename}, mise en file d'attente pour Celery.")
    
    file_bytes = await file.read()
    
    # .delay() est la méthode pour lancer une tâche Celery en arrière-plan
    process_document_task.delay(
        file_bytes,
        file.filename,
        file.content_type,
        job_id,
        callback_url
    )
    
    return {"status": "processing_enqueued", "job_id": job_id}
