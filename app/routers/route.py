from fastapi import HTTPException,APIRouter,UploadFile
from fastapi.responses import HTMLResponse,FileResponse
from app.services.api_service import speech_to_text
import os
from pathlib import Path

router = APIRouter()

# 1. __file__ is inside D:\VOICOPS\APP\routers
# 2. .parent gets you to D:\VOICOPS\APP\routers
# 3. .parent.parent gets you up to D:\VOICOPS\APP
BASE_DIR = Path(__file__).resolve().parent.parent

# 4. Now accurately point to the templates folder
HTML_PATH = BASE_DIR / "templates" / "index.html"


@router.get("/")
async def serve_frontend():
    return FileResponse(HTML_PATH)





@router.post('/generate-config')
async def generate_config(audio:UploadFile):
   audio_bytes = await audio.read()
   print(audio_bytes)
   # send the audio bytes to GroqApi
   trans_text =''
   try:
      trans_text = await speech_to_text(audio_bytes)
   except Exception as e:
      print(f'Error: {e}')

   return {'transcript':trans_text or None}

   
