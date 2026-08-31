from deepgram import AsyncDeepgramClient
from groq import AsyncGroq, APIConnectionError, RateLimitError, APIStatusError
import os
from dotenv import load_dotenv

load_dotenv()

############## DEEPGRAM API SERVICE (Speech-to-Text) ###############

DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
deepgram_client = AsyncDeepgramClient(api_key=DEEPGRAM_API_KEY)

############## GROQ API SERVICE (Chat Completions / LLM) ###############

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
groq_client = AsyncGroq(api_key=GROQ_API_KEY)


async def speech_to_text(audio_bytes: bytes) -> str:
    """Transcribe audio using Deepgram Nova-3 model."""
    try:
        response = await deepgram_client.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model="nova-3",
            smart_format=True,
            keyterm=["postgresql", "mysql", "mongodb", "redis",
                     "fastapi", "nodejs", "flask", "django", "docker"],
        )
        transcript = response.results.channels[0].alternatives[0].transcript
        return transcript or ""
    except Exception as e:
        raise Exception(f"Deepgram API error: {str(e)}")


############## GROQ SPEECH-TO-TEXT (COMMENTED OUT — using Deepgram instead) ###############

# GROQ_API_KEY = os.getenv('GROQ_API_KEY')
# groq_client = AsyncGroq(api_key=GROQ_API_KEY)
#
# async def speech_to_text_groq(audio_bytes: bytes) -> str:
#     try:
#         transcription = await groq_client.audio.transcriptions.create(
#             file=("command.wav", audio_bytes),
#             model="whisper-large-v3-turbo",
#             prompt="postgresql, mysql, mongodb, redis, fastapi, nodejs, flask, django, docker",
#         )
#         return transcription.text
#     except RateLimitError:
#         raise Exception("Groq is rate-limiting us, try again shortly")
#     except APIConnectionError:
#         raise Exception("Could not reach Groq — check network")
#     except APIStatusError as e:
#         raise Exception(f"Groq API error {e.status_code}: {e.message}")
