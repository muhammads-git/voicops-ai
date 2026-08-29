from fastapi import HTTPException,APIRouter,UploadFile
from fastapi.responses import HTMLResponse,FileResponse
from app.services.api_service import speech_to_text
import os
from pathlib import Path
from app.services.extract_intent import extract_intent,normalize_transcript
from app.services.build_configs import build_config

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
async def generate_config(audio: UploadFile):
    audio_bytes = await audio.read()

    # Step 1: audio -> transcript
    try:
        transcript = await speech_to_text(audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Step 2: transcript -> structured intent
    try:
        print(transcript)
        intent = await extract_intent(normalize_transcript(transcript))
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        print(intent['services'], intent['unsupported'])
        configs = build_config(intent['services'])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Today's stopping point: return both, confirm the full chain works
    return {
    "transcript": transcript,
    "unsupported": intent["unsupported"],
    "dockerfile": configs["dockerfile"],
    "docker_compose": configs["docker_compose"],
}