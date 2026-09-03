# services/extract_intent.py
import json
import logging
from groq import APIConnectionError, RateLimitError, APIStatusError
from app.services.api_service import groq_client

logger = logging.getLogger(__name__)

# --- extract_intent.py: 3-layer defense against Whisper mishearings ---
#
#  Layer 1 — Transcript Normalizer : pre-LLM text corrections
#  Layer 2 — Fuzzy Resolver        : post-LLM edit-distance matching
#  Layer 3 — Phonetic Rescuer      : post-LLM curated sound-alike matching only
#
#  NOTE: Layer 3 previously also included a prefix-substring fallback
#  (checking if a service's first 4 letters appeared anywhere in an
#  unrecognized word). It was removed — see reasoning below the
#  fuzzy_resolve function.

SUPPORTED_SERVICES = {"postgresql", "mysql", "mongodb", "redis", "fastapi", "nodejs", "flask", "django"}

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
    "mango": "mongodb",  # confirmed real mishearing during testing (edit distance 3, missed by Layer 2's max_distance=2)
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
    # flask
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
#  Curated sound-alike clusters only. Every entry here was added
#  because it was actually observed during testing — not guessed.
#  This is deliberately the ONLY mechanism in Layer 3. The prefix-
#  substring fallback that used to sit alongside this was removed:
#  it checked whether a service's first 4 letters appeared anywhere
#  in an unrecognized word, which produces false positives on
#  ordinary English words that coincidentally share those letters
#  (e.g. "flashlight" contains "flas", the first 4 letters of
#  "flask" — the check would wrongly report "Flask" was requested).
#  A missed correction is honest (user sees "not supported yet");
#  a false rescue is silently wrong (user sees a confident answer
#  that doesn't match what they said). This list only grows when a
#  real mishearing is confirmed through actual testing.
# ═══════════════════════════════════════════════════════════════
PHONETIC_ALIASES = {
    "postgresql": ["postgres", "postgre", "postgras", "postgrest", "postcard", "postbird", "postgress"],
    "mysql":      ["mysequel", "mysqul", "mikesql", "myschool"],
    "mongodb":    ["mongo", "mongod", "mongob", "mangodb", "mongode", "mongol", "mango"],
    "redis":      ["reddis", "redish", "radish", "reddish", "redissh", "rediss", "redi"],
    "nodejs":     ["node", "nodejs", "nodjs", "notjs", "nojs", "nods"],
    "fastapi":    ["fastapi", "fastapy", "fastappy", "pastapi"],
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
    Layer 3 (Phonetic Rescuer) — curated sound-alike lookup on the
              unsupported list only (e.g. "mongo" -> "mongodb").
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

    # ── Layer 3: Phonetic Rescuer — curated alias lookup only ──
    for item in unsupported:
        lower = item.lower().strip()
        matched = None

        for svc, aliases in PHONETIC_ALIASES.items():
            if lower in aliases:
                matched = svc
                break

        # REMOVED: prefix-substring fallback (checked if svc[:4] appeared
        # anywhere in `lower`). Deleted because it produces false positives
        # on unrelated English words sharing a 4-letter fragment with a
        # service name (e.g. "flashlight" -> falsely matched "flask").
        # A confident wrong match is worse than an honest "unsupported" —
        # it hides the mistake instead of surfacing it to the user.

        # REMOVED: blind final fuzzy-match fallback on the raw unsupported
        # word. This ran full edit-distance matching against every
        # genuinely-unsupported word (e.g. "kafka", "terraform"), risking
        # the same silent false-positive problem — an unrelated or
        # not-yet-supported word coincidentally landing within edit
        # distance 2 of a real service and getting reported as understood.

        if matched and matched not in corrected:
            logger.info(f"Rescued from unsupported: '{item}' -> '{matched}'")
            corrected.append(matched)
        elif matched and matched in corrected:
            pass  # duplicate, silently remove
        else:
            still_unsupported.append(item)

    return corrected, still_unsupported


def build_corrected_transcript(raw_transcript: str, corrected_services: list[str]) -> str:
    """
    Rebuild the transcript with all layers' corrections applied.
    Replaces misheard service names in the text with the correct ones,
    so the frontend can show what was 'understood' vs what was 'heard'.
    """
    text = raw_transcript.lower()

    # Layer 1: apply KNOWN_CORRECTIONS (longest phrases first to avoid partial matches)
    for wrong, right in sorted(KNOWN_CORRECTIONS.items(), key=lambda x: -len(x[0])):
        text = text.replace(wrong, right)

    # Layer 2+3: replace phonetic aliases and fuzzy matches in the text
    for svc in corrected_services:
        if svc not in SUPPORTED_SERVICES:
            continue

        # Replace single-word phonetic aliases (whole words only, skip self)
        for alias in PHONETIC_ALIASES.get(svc, []):
            if alias != svc:
                words = text.split()
                for i, word in enumerate(words):
                    if word.strip(".,!?;:") == alias:
                        words[i] = word.replace(alias, svc)
                text = " ".join(words)

        # Word-level scan: single-word fuzzy match only.
        #
        # REMOVED: the multi-word prefix catch that used
        # `cleaned.startswith(prefix)` to find and replace words sharing
        # a service's first few letters. Same risk as the fallback removed
        # from fuzzy_resolve above — .startswith() is stricter than the
        # old `in` check, but it still misfires on ordinary words that
        # genuinely start with those letters ("post" -> postcard, poster,
        # postpone; "flas" -> flashlight, flashback). This function only
        # needs to display what was already safely corrected upstream —
        # it doesn't need its own independent, riskier matching logic.
        words = text.split()
        i = 0
        while i < len(words):
            cleaned = words[i].strip(".,!?;:")

            if cleaned == svc:
                i += 1
                continue

            if _fuzzy_match(cleaned) == svc:
                words[i] = words[i].replace(cleaned, svc)

            i += 1

        text = " ".join(words)

    return text


SYSTEM_PROMPT = """Extract only known infrastructure services mentioned in the user's request.
Also detect if the user wants cloud deployment (Alibaba Cloud, cloud hosting, deploy to cloud, on the cloud).
Respond only with JSON in this exact shape:
{"services": ["postgresql", "redis"], "unsupported": ["kafka"], "deploy_cloud": true}

Only use these values in "services": postgresql, mysql, mongodb, redis, fastapi, nodejs, flask, django.
Any service mentioned that is NOT in that list goes into "unsupported" instead, using the user's own word for it.
If there are no unsupported services, return an empty list for "unsupported".
Set "deploy_cloud" to true only when the user explicitly mentions cloud deployment, Alibaba Cloud, cloud infrastructure, "on the cloud", or "deploy to the cloud". Otherwise set it to false."""


async def extract_intent(transcript: str) -> dict:
    try:
        response = await groq_client.chat.completions.create(
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

    raw_content = response.choices[0].message.content
    print(f'Raw script: {raw_content}')

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error(f"Model returned non-JSON content: {raw_content}")
        raise Exception("Could not parse intent from model response")

    raw_services = parsed.get("services", [])
    raw_unsupported = parsed.get("unsupported", [])

    valid_services = [s for s in raw_services if s in SUPPORTED_SERVICES]
    leaked_unsupported = [s for s in raw_services if s not in SUPPORTED_SERVICES]

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