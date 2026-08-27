# services/extract_intent.py
import json
import logging
from groq import APIConnectionError, RateLimitError, APIStatusError
from app.services.api_service import client

logger = logging.getLogger(__name__)

SUPPORTED_SERVICES = {"postgresql", "mysql", "mongodb", "redis", "fastapi", "nodejs", "docker", "flask", "django"}
SYSTEM_PROMPT = """Extract only known infrastructure services mentioned in the user's request.
Respond only with JSON in this exact shape:
{"services": ["postgresql", "redis"], "unsupported": ["kafka"]}

Only use these values in "services": postgresql, mysql, mongodb, redis, fastapi, nodejs, flask, django, docker.
Any service mentioned that is NOT in that list goes into "unsupported" instead, using the user's own word for it.
If there are no unsupported services, return an empty list for "unsupported"."""
## Coreections are for the LLM to discover the right word...
KNOWN_CORRECTIONS = {
    "not just": "node.js",
    "node js": "node.js",
    "postgres equal": "postgresql",
    # add more as you discover them during testing
}

def normalize_transcript(transcript: str) -> str:
    lowered = transcript.lower()
    for wrong, right in KNOWN_CORRECTIONS.items():
        lowered = lowered.replace(wrong, right)
    return lowered

##################3
async def extract_intent(transcript: str) -> dict:
    """
    Sends the transcript to the LLM, returns a dict:
    {"services": [...], "unsupported": [...]}
    Raises Exception on API failure OR on malformed model output —
    both are failure cases the route needs to handle, not silently pass through.
    """
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            response_format={"type": "json_object"},
        )

    except RateLimitError:
        logger.warning("Groq rate limit hit during intent extraction")
        raise Exception("Intent service is rate-limited, try again shortly")

    except APIConnectionError as e:
        logger.error(f"Could not reach Groq: {e}")
        raise Exception("Could not reach intent extraction service")

    except APIStatusError as e:
        logger.error(f"Groq API error {e.status_code}: {e.message}")
        raise Exception(f"Intent extraction failed (status {e.status_code})")

    # The API call succeeding doesn't guarantee valid/expected JSON shape.
    # This is a SEPARATE failure mode from the API errors above — handle it too.
    raw_content = response.choices[0].message.content
    print(f'Raw script: {raw_content}')

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error(f"Model returned non-JSON content: {raw_content}")
        raise Exception("Could not parse intent from model response")

    services = parsed.get("services", [])
    unsupported = parsed.get("unsupported", [])

    # Defensive check: don't trust the model to perfectly obey the allowed list.
    # Anything it slipped into "services" that isn't actually supported gets
    # reclassified rather than silently trusted.
    valid_services = [s for s in services if s in SUPPORTED_SERVICES]
    leaked_unsupported = [s for s in services if s not in SUPPORTED_SERVICES]

    return {
        "services": valid_services,
        "unsupported": unsupported + leaked_unsupported,
    }