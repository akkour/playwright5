import os
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

import resend
from datetime import datetime, timedelta

# Configuration
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
PROJECT_DIR = os.getenv("PROJECT_DIR", "/workspace")

SERVICES = {
    "admin-dashboard": {"name": "Admin Dashboard", "color": "#2196F3"},
    "playwright-crawler": {"name": "Playwright Crawler", "color": "#4CAF50"},
    "document-processor-web": {"name": "Document Processor", "color": "#FF9800"},
    "document-processor-worker": {"name": "Celery Worker", "color": "#9C27B0"},
    "redis": {"name": "Redis", "color": "#f44336"},
    "ocr-service": {"name": "OCR Service", "color": "#3F51B5"},
    "easyocr-service": {"name": "EasyOCR Service", "color": "#009688"},
    "browserless-browserless-1": {"name": "browserless-browserless", "color": "#607D8B"},
}

# Email configuration
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "onboarding@resend.dev")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "300"))

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

alert_history: Dict[str, datetime] = {}
previous_service_states: Dict[str, str] = {}

app = FastAPI(title="EvaRAG Admin Dashboard")
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USER)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

async def run_docker_command(cmd: List[str]) -> Dict[str, Any]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return {
            "success": process.returncode == 0,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "returncode": process.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1
        }

async def get_service_status() -> List[Dict[str, Any]]:
    result = await run_docker_command(["docker", "ps", "-a", "--format", "{{json .}}"])
    if not result["success"]:
        return []

    services = []
    for line in result["stdout"].strip().split('\n'):
        if line:
            try:
                data = json.loads(line)
                name = data.get("Names", "")
                status = data.get("Status", "")
                state = data.get("State", "")

                if state == "running":
                    state_clean = "running"
                elif state == "restarting":
                    state_clean = "restarting"
                elif state == "exited":
                    state_clean = "stopped"
                else:
                    state_clean = state

                service_name = name.replace("playwright-crawler-", "").replace("-1", "")
                display_name = SERVICES.get(service_name, {}).get("name", name)

                services.append({
                    "name": service_name,
                    "display_name": display_name,
                    "state": state_clean,
                    "status": status,
                    "color": SERVICES.get(service_name, {}).get("color", "#607D8B")
                })
            except:
                pass
    return services

async def get_resource_usage() -> List[Dict[str, Any]]:
    result = await run_docker_command(["docker", "stats", "--no-stream", "--format", "{{json .}}"])
    if not result["success"]:
        return []

    resources = []
    for line in result["stdout"].strip().split('\n'):
        if line:
            try:
                data = json.loads(line)
                resources.append({
                    "name": data.get("Name", ""),
                    "cpu": data.get("CPUPerc", "0%"),
                    "memory": data.get("MemUsage", "0B / 0B")
                })
            except:
                pass
    return resources

async def send_email_alert(service_name: str, status: str, previous_status: str):
    if not RESEND_API_KEY or not ALERT_EMAIL_TO:
        print("⚠️ Email alerts not configured")
        return
    
    now = datetime.now()
    last_alert = alert_history.get(service_name)
    if last_alert and (now - last_alert).seconds < ALERT_COOLDOWN:
        return
    
    try:
        display_name = SERVICES.get(service_name, {}).get("name", service_name)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="background: #f44336; color: white; padding: 20px; border-radius: 5px;">
                <h2>🚨 Service Alert - EvaRAG</h2>
            </div>
            <div style="margin-top: 20px; padding: 20px; border: 1px solid #ddd;">
                <p><strong>Service:</strong> {display_name}</p>
                <p><strong>Status:</strong> <span style="color: #f44336;">{status.upper()}</span></p>
                <p><strong>Previous:</strong> {previous_status}</p>
                <p><strong>Time:</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><a href="https://admin.evaleads.com">Open Dashboard</a></p>
            </div>
        </body>
        </html>
        """
        
        params = {
            "from": ALERT_EMAIL_FROM,
            "to": [ALERT_EMAIL_TO],
            "subject": f"🚨 ALERT: {display_name} - {status.upper()}",
            "html": html_content,
        }
        
        email = resend.Emails.send(params)
        alert_history[service_name] = now
        print(f"📧 Alert sent for {service_name}: {status} (ID: {email.get('id')})")
        
    except Exception as e:
        print(f"❌ Email alert failed: {e}")

async def check_service_changes(services: List[Dict[str, Any]]):
    for service in services:
        name = service.get("name")
        state = service.get("state")
        
        if name in previous_service_states:
            previous_state = previous_service_states[name]
            if previous_state == "running" and state in ["stopped", "exited"]:
                asyncio.create_task(send_email_alert(name, state, previous_state))
        
        previous_service_states[name] = state

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            services = await get_service_status()
            resources = await get_resource_usage()
            
            try:
                await check_service_changes(services)
            except Exception as e:
                print(f"⚠️ Alert check error: {e}")
            
            try:
                await websocket.send_json({
                    "services": services,
                    "resources": resources
                })
            except Exception as e:
                print(f"⚠️ WebSocket send error: {e}")
                break
            
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        print("ℹ️ WebSocket disconnected")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")

@app.get("/")
async def index(username: str = Depends(verify_credentials)):
    html = Path(__file__).parent / "templates" / "index.html"
    if html.exists():
        return HTMLResponse(content=html.read_text())
    return HTMLResponse("<h1>Dashboard</h1><p>Template not found</p>")

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.post("/api/service/{service_name}/start")
async def start_service(service_name: str, username: str = Depends(verify_credentials)):
    """Démarrer un service"""
    try:
        # Réactiver restart policy
        await run_docker_command(["docker", "update", "--restart=always", service_name])
        
        # Démarrer
        result = await run_docker_command(["docker", "start", service_name])
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Service '{service_name}' démarré",
                "service": service_name,
                "action": "start"
            }
        else:
            raise HTTPException(status_code=500, detail=result["stderr"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/service/{service_name}/stop")
async def stop_service(service_name: str, username: str = Depends(verify_credentials)):
    """Arrêter un service"""
    try:
        # Désactiver restart policy
        await run_docker_command(["docker", "update", "--restart=no", service_name])
        
        # Arrêter
        result = await run_docker_command(["docker", "stop", service_name])
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Service '{service_name}' arrêté",
                "service": service_name,
                "action": "stop"
            }
        else:
            raise HTTPException(status_code=500, detail=result["stderr"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/service/{service_name}/restart")
async def restart_service(service_name: str, username: str = Depends(verify_credentials)):
    """Redémarrer un service"""
    try:
        # Réactiver restart policy
        await run_docker_command(["docker", "update", "--restart=always", service_name])
        
        # Redémarrer
        result = await run_docker_command(["docker", "restart", service_name])
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Service '{service_name}' redémarré",
                "service": service_name,
                "action": "restart"
            }
        else:
            raise HTTPException(status_code=500, detail=result["stderr"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/service/{service_name}/logs")
async def get_service_logs(
    service_name: str,
    lines: int = 50,
    username: str = Depends(verify_credentials)
):
    """Récupérer les logs d'un service"""
    try:
        lines = max(10, min(lines, 1000))
        result = await run_docker_command(["docker", "logs", "--tail", str(lines), service_name])

        if result["success"]:
            logs = result["stdout"]
            if result["stderr"]:
                logs = logs + "\n" + result["stderr"]
            return {
                "success": True,
                "service": service_name,
                "lines": lines,
                "logs": logs if logs else "Aucun log disponible"
            }
        else:
            raise HTTPException(status_code=500, detail=result["stderr"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
