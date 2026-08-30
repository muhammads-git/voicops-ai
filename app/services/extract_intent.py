# services/extract_intent.py
import json
import logging
from groq import APIConnectionError, RateLimitError, APIStatusError
from app.services.api_service import client

logger = logging.getLogger(__name__)

# --- extract_intent.py: 3-layer defense against Whisper mishearings ---
#
#  Layer 1 — Transcript Normalizer : pre-LLM text corrections
#  Layer 2 — Fuzzy Resolver        : post-LLM edit-distance matching
#  Layer 3 — Phonetic Rescuer      : post-LLM sound-alike + substring rescue

SUPPORTED_SERVICES = {"postgresql", "mysql", "mongodb", "redis", "fastapi", "nodejs", "docker", "flask", "django"}

# ═══════════════════════════════════════════════════════════════
#  Layer 1: Transcript Normalizer
#  Pre-LLM — fixes known Whisper mishearings in the raw text
#  before the LLM ever sees it. Expand KNOWN_CORRECTIONS as you
#  discover new mishearings during testing.
# ═══════════════════════════════════════════════════════════════
KNOWN_CORRECTIONS = {
    # nodejs
    "nordjust": "nodejs",
    "not just": "nodejs",
    "not js": "nodejs",
    "notjs": "nodejs",
    "node js": "nodejs",
    "node.js": "nodejs",
    "no js": "nodejs",
    "node j s": "nodejs",
    "note js": "nodejs",
    # postgresql
    "postgres equal": "postgresql",
    "post gres": "postgresql",
    "post grass": "postgresql",
    "post card": "postgresql",
    "postbird": "postgresql",
    "post bird": "postgresql",
    "postgras": "postgresql",
    "post grest": "postgresql",
    "post rest": "postgresql",
    # mysql
    "my sequel": "mysql",
    "my school": "mysql",
    "my sql": "mysql",
    "mike sql": "mysql",
    # mongodb
    "mon go": "mongodb",
    "mongo db": "mongodb",
    "mongo baby": "mongodb",
    "mon go db": "mongodb",
    "mango db": "mongodb",
    # redis
    "red is": "redis",
    "read is": "redis",
    "read us": "redis",
    "red us": "redis",
    "radish": "redis",
    "reddish": "redis",
    "rattish": "redis",
    # fastapi
    "fast api": "fastapi",
    "fast appy": "fastapi",
    "fastappy": "fastapi",
    "past api": "fastapi",
    "fast a pi": "fastapi",
    # docker
    "dock her": "docker",
    "dock er": "docker",
    "darker": "docker",
    "doc her": "docker",
    # flask
    "flask": "flask",
    "flash": "flask",
    "fl ask": "flask",
    # django
    "jan go": "django",
    "jango": "django",
    "djan go": "django",
    "jangle": "django",
    # cloud
    "ali baba": "alibaba",
    "ali cloud": "alibaba cloud",
    "alba": "alibaba",
    "allibaba": "alibaba",
}

# ═══════════════════════════════════════════════════════════════
#  Layer 3: Phonetic Rescuer
#  Sound-alike clusters for the last-resort rescue scan on the
#  unsupported list. If Whisper hears "mongo" instead of "mongodb",
#  this catches it even when Layers 1 & 2 missed it.
# ═══════════════════════════════════════════════════════════════
PHONETIC_ALIASES = {
    "postgresql": ["postgres", "postgre", "postgras", "postgrest", "postcard", "postbird", "postgress"],
    "mysql":      ["mysequel", "mysqul", "mikesql", "myschool"],
    "mongodb":    ["mongo", "mongod", "mongob", "mangodb", "mongode", "mongol"],
    "redis":      ["reddis", "redish", "radish", "reddish", "redissh", "rediss", "redi"],
    "nodejs":     ["node", "nodejs", "nodjs", "notjs", "nojs", "nods"],
    "fastapi":    ["fastapi", "fastapy", "fastappy", "pastapi"],
    "docker":     ["dock", "doker", "docer", "dokka"],
    "flask":      ["flash", "flaask"],
    "django":     ["jango", "jengo", "jangle", "djengo"],
}


# ── Layer 1: Transcript Normalizer ──
def normalize_transcript(transcript: str) -> str:
    """Replace known Whisper mishearings in the raw transcript before LLM processing."""
    lowered = transcript.lower()
    for wrong, right in KNOWN_CORRECTIONS.items():
        lowered = lowered.replace(wrong, right)
    return lowered


# ── Layer 2: Fuzzy Resolver (helpers) ──
def _edit_distance(a: str, b: str) -> int:
    """Classic Levenshtein distance — no dependencies needed."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _fuzzy_match(word: str, max_distance: int = 2) -> str | None:
    """Find the closest supported service by edit distance."""
    word = word.lower().strip()
    best, best_dist = None, max_distance + 1
    for svc in SUPPORTED_SERVICES:
        d = _edit_distance(word, svc)
        if d < best_dist:
            best, best_dist = svc, d
    return best if best_dist <= max_distance else None


def fuzzy_resolve(services: list[str], unsupported: list[str]) -> tuple[list[str], list[str]]:
    """
    Layer 2 + Layer 3: resolve misheard service names across both lists.

    Layer 2 (Fuzzy Resolver) — edit-distance matching on unrecognized names
              in the services list (e.g. "redish" -> "redis").
    Layer 3 (Phonetic Rescuer) — sound-alike alias + substring scan on the
              unsupported list to recover missed services (e.g. "mongo" -> "mongodb").
    """
    corrected = []
    still_unsupported = []

    # ── Layer 2: Fuzzy Resolver — edit-distance on unrecognized services ──
    for svc in services:
        if svc in SUPPORTED_SERVICES:
            if svc not in corrected:
                corrected.append(svc)
            continue
        match = _fuzzy_match(svc)
        if match and match not in corrected:
            logger.info(f"Fuzzy corrected service: '{svc}' -> '{match}'")
            corrected.append(match)
        elif match and match in corrected:
            logger.info(f"Fuzzy duplicate removed: '{svc}' (already have '{match}')")
        else:
            still_unsupported.append(svc)

    # ── Layer 3: Phonetic Rescuer — sound-alike + substring rescue ──
    for item in unsupported:
        lower = item.lower().strip()
        matched = None

        # Check phonetic aliases first
        for svc, aliases in PHONETIC_ALIASES.items():
            if lower in aliases or any(alias in lower for alias in aliases):
                matched = svc
                break

        # Fallback: substring match (e.g. "postcard" contains "postg" ~ postgres)
        if not matched:
            for svc in SUPPORTED_SERVICES:
                if len(svc) >= 5 and svc[:4] in lower:
                    matched = svc
                    break

        # Fallback: edit distance
        if not matched:
            matched = _fuzzy_match(lower, max_distance=2)

        if matched and matched not in corrected:
            logger.info(f"Rescued from unsupported: '{item}' -> '{matched}'")
            corrected.append(matched)
        elif matched and matched in corrected:
            pass  # duplicate, silently remove
        else:
            still_unsupported.append(item)

    return corrected, still_unsupported

SYSTEM_PROMPT = """Extract only known infrastructure services mentioned in the user's request.
Also detect if the user wants cloud deployment (Alibaba Cloud, cloud hosting, deploy to cloud, on the cloud).
Respond only with JSON in this exact shape:
{"services": ["postgresql", "redis"], "unsupported": ["kafka"], "deploy_cloud": true}

Only use these values in "services": postgresql, mysql, mongodb, redis, fastapi, nodejs, flask, django, docker.
Any service mentioned that is NOT in that list goes into "unsupported" instead, using the user's own word for it.
If there are no unsupported services, return an empty list for "unsupported".
Set "deploy_cloud" to true only when the user explicitly mentions cloud deployment, Alibaba Cloud, cloud infrastructure, "on the cloud", or "deploy to the cloud". Otherwise set it to false."""


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

    # Split raw LLM output into recognized vs unrecognized
    raw_services = parsed.get("services", [])
    raw_unsupported = parsed.get("unsupported", [])

    # Anything the LLM put in "services" that isn't a known service gets
    # moved to the correction pile rather than blindly trusted.
    valid_services = [s for s in raw_services if s in SUPPORTED_SERVICES]
    leaked_unsupported = [s for s in raw_services if s not in SUPPORTED_SERVICES]

    # Layer 2+3: fuzzy_resolve misheard service names across both lists
    corrected_services, corrected_unsupported = fuzzy_resolve(
        valid_services + leaked_unsupported,
        raw_unsupported,
    )

    deploy_cloud = parsed.get("deploy_cloud", False)
    if not isinstance(deploy_cloud, bool):
        deploy_cloud = False

    print(f"[INTENT] services={corrected_services}, unsupported={corrected_unsupported}, cloud={deploy_cloud}")

    return {
        "services": corrected_services,
        "unsupported": corrected_unsupported,
        "deploy_cloud": deploy_cloud,
    }