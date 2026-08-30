from groq import AsyncGroq, APIConnectionError, RateLimitError, APIStatusError
import os
from dotenv import load_dotenv

load_dotenv()
############## GROQ API SERVICE ###############3

API_KEY = os.getenv('GROQ_API_KEY')
client = AsyncGroq(api_key=API_KEY)

async def speech_to_text(audio_bytes: bytes) -> str:
    try:
        transcription = await client.audio.transcriptions.create(
            file=("command.wav", audio_bytes),
            model="whisper-large-v3-turbo"
        )
        return transcription.text
    except RateLimitError:
        raise Exception("Groq is rate-limiting us, try again shortly")
    except APIConnectionError:
        raise Exception("Could not reach Groq — check network")
    except APIStatusError as e:
        raise Exception(f"Groq API error {e.status_code}: {e.message}")

