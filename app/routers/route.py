from fastapi import HTTPException,APIRouter,UploadFile
from app.services.api_service import speech_to_text


router = APIRouter()

@router.post('generate-config')
async def generate_config(audio:UploadFile):
   audio_bytes = await audio.read()
   # send the audio bytes to GroqApi
   try:
      trans_text = await speech_to_text(audio_bytes)
   except Exception as e:
      print(f'Error: {e}')