from groq import Groq
from dotenv import load_dotenv
import os


load_dotenv()

#client
GROQ_API = os.getenv('GROQ_API_KEY')
client = Groq(api_key=GROQ_API)

def speech_to_text(audio_bytes: bytes) -> str:
   # call groq-api
   transcription = client.audio.transcriptions.create(
      file=('command_wbm',audio_bytes),
      model='whisper-large-v3-turbo'
   )
   return transcription.text
