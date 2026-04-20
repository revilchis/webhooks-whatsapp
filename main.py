import os
import httpx
import logging
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Response

# IMPORTANTE: Aquí importas la lógica de tu IA, sea cual sea.
# 'analizador' es tu archivo .py y 'procesar_mensaje' es tu función.
try:
    from analizador import procesar_mensaje 
except ImportError:
    async def procesar_mensaje(texto):
        return "⚠️ Error: El motor de análisis no está conectado."

# CONFIGURACIÓN DE LOGS
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("GeommaAI.Gateway")

def cargar_entorno():
    load_dotenv() # Carga .env local si existe
    logger.info("Entorno configurado.")

cargar_entorno()

class WhatsAppGateway:
    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN")
        self.phone_id = os.getenv("WHATSAPP_PHONE_ID")
        self.verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.base_url = f"https://graph.facebook.com/v21.0/{self.phone_id}/messages"

    async def enviar_texto(self, numero: str, texto: str):
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text",
            "text": {"body": texto}
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                return response.json()
            except Exception as e:
                logger.error(f"❌ Error WhatsApp: {e}")
                return None

app = FastAPI()
gw = WhatsAppGateway()

@app.get("/webhook")
async def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == gw.verify_token:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(status_code=403)

@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    try:
        # Navegamos el JSON de Meta para llegar al mensaje
        messages = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [])
        
        if messages:
            msg = messages[0]
            numero = msg["from"]
            
            if msg.get("type") == "text":
                texto_usuario = msg["text"]["body"]
                logger.info(f"📩 Mensaje de {numero}: {texto_usuario}")

                # --- AQUÍ CONECTAS CON TU OTRO ARCHIVO ---
                # No importa si es OpenAI, Claude o un script propio.
                respuesta_ia = await procesar_mensaje(texto_usuario)

                # Enviar respuesta de vuelta
                await gw.enviar_texto(numero, respuesta_ia)
                logger.info(f"📤 Respuesta enviada.")

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"🔥 Error: {e}")
        return {"status": "error"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))