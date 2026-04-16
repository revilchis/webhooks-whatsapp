import os
from fastapi import FastAPI, Request, Response, HTTPException
from dotenv import load_dotenv
import httpx

# Esto carga las variables en local, en Render usará el panel de control
load_dotenv()

app = FastAPI(title="GeommaAI Gateway")

# Variables de entorno
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Validación obligatoria para Meta"""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token de verificación inválido", status_code=403)

@app.post("/webhook")
async def receive_messages(request: Request):
    """Receptor de mensajes"""
    data = await request.json()
    print(f"📩 Evento recibido: {data}")
    
    # Aquí es donde integrarás tu Agent 10 más adelante
    return {"status": "success"}

@app.get("/")
async def health():
    return {"status": "online"}