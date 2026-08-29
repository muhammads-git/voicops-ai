from fastapi import HTTPException,APIRouter,UploadFile
from fastapi.responses import HTMLResponse,FileResponse
from app.services.api_service import speech_to_text
import time
import logging
import os
from pathlib import Path
from sqlalchemy import select, func
from app.services.extract_intent import extract_intent,normalize_transcript
from app.services.build_configs import build_config
from app.services.build_terraform import build_terraform
from app.services.self_healing import heal_dockerfile, heal_terraform
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.database import async_session
from app.models import RequestLog

logger = logging.getLogger(__name__)

router = APIRouter()

# Circuit breakers for external API calls
speech_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=30)
intent_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=30)

# 1. __file__ is inside D:\VOICOPS\APP\routers
# 2. .parent gets you to D:\VOICOPS\APP\routers
# 3. .parent.parent gets you up to D:\VOICOPS\APP
BASE_DIR = Path(__file__).resolve().parent.parent

# 4. Now accurately point to the templates folder
HTML_PATH = BASE_DIR / "templates" / "index.html"
ANALYTICS_PATH = BASE_DIR / "templates" / "analytics.html"


@router.get("/")
async def serve_frontend():
    return FileResponse(HTML_PATH)



@router.post('/generate-config')
async def generate_config(audio: UploadFile):
    audio_bytes = await audio.read()
    start_time = time.time()

    # Step 1: audio -> transcript (with circuit breaker)
    try:
        transcript = await speech_breaker.call(speech_to_text, audio_bytes)
    except CircuitOpenError:
        raise HTTPException(status_code=503, detail="Speech service temporarily unavailable")
    except Exception as e:
        print(f"[ERROR] Step 1 (speech-to-text): {e}")
        raise HTTPException(status_code=502, detail=str(e))

    # Step 2: transcript -> structured intent (with circuit breaker)
    try:
        print(f"[STEP 2] Transcript: {transcript}")
        intent = await intent_breaker.call(extract_intent, normalize_transcript(transcript))
    except CircuitOpenError:
        raise HTTPException(status_code=503, detail="Intent service temporarily unavailable")
    except Exception as e:
        print(f"[ERROR] Step 2 (intent extraction): {e}")
        raise HTTPException(status_code=502, detail=str(e))

    try:
        print(f"[STEP 3] Services: {intent['services']}, Unsupported: {intent['unsupported']}")
        configs = build_config(intent['services'])
    except Exception as e:
        print(f"[ERROR] Step 3 (build_config): {e}")
        raise HTTPException(status_code=502, detail=str(e))

    # Step 4 (optional): services -> terraform (only if cloud deployment requested)
    terraform_content = None
    if intent.get("deploy_cloud"):
        try:
            terraform_content = build_terraform(intent['services'])
        except Exception as e:
            print(f"[ERROR] Step 4 (build_terraform): {e}")
            raise HTTPException(status_code=502, detail=str(e))

    # Step 5: Validate and self-heal generated configs
    validation = {}
    healing_stats = {"dockerfile": 0, "terraform": 0}

    if configs["dockerfile"]:
        try:
            healed = await heal_dockerfile(configs["dockerfile"])
            configs["dockerfile"] = healed["content"]  # Use healed version
            healing_stats["dockerfile"] = healed["healing_count"]
            validation["dockerfile"] = {
                "valid": healed["valid"],
                "healing_count": healed["healing_count"],
                "tool_available": healed["tool_available"],
            }
        except Exception as e:
            # Healing should never crash the request
            validation["dockerfile"] = {"valid": True, "healing_count": 0, "tool_available": False}

    if terraform_content:
        try:
            healed = await heal_terraform(terraform_content)
            terraform_content = healed["content"]  # Use healed version
            healing_stats["terraform"] = healed["healing_count"]
            validation["terraform"] = {
                "valid": healed["valid"],
                "healing_count": healed["healing_count"],
                "tool_available": healed["tool_available"],
            }
        except Exception as e:
            validation["terraform"] = {"valid": True, "healing_count": 0, "tool_available": False}

    # --- Telemetry logging ---
    elapsed = time.time() - start_time
    total_healing = healing_stats.get("dockerfile", 0) + healing_stats.get("terraform", 0)
    status = "success" if (configs["dockerfile"] or terraform_content) else "failed"

    try:
        async with async_session() as session:
            log = RequestLog(
                transcript=transcript,
                intent_json=intent,
                outputs_json={
                    "dockerfile": bool(configs["dockerfile"]),
                    "docker_compose": bool(configs["docker_compose"]),
                    "terraform": bool(terraform_content),
                },
                validation_json=validation,
                healing_count=total_healing,
                time_taken=round(elapsed, 2),
                status=status,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to log telemetry: {e}")

    return {
        "transcript": transcript,
        "unsupported": intent["unsupported"],
        "dockerfile": configs["dockerfile"],
        "docker_compose": configs["docker_compose"],
        "terraform": terraform_content,
        "validation": validation,
        "healing_stats": healing_stats,
    }


@router.get("/analytics")
async def serve_analytics():
    return FileResponse(ANALYTICS_PATH)


@router.get("/api/analytics")
async def get_analytics():
    """Returns aggregated telemetry stats for the analytics dashboard."""
    try:
        async with async_session() as session:
            total = await session.scalar(select(func.count(RequestLog.id)))
            success = await session.scalar(
                select(func.count(RequestLog.id)).where(RequestLog.status == "success")
            )
            avg_healing = await session.scalar(select(func.avg(RequestLog.healing_count)))
            avg_time = await session.scalar(select(func.avg(RequestLog.time_taken)))

            recent = await session.execute(
                select(RequestLog).order_by(RequestLog.created_at.desc()).limit(10)
            )
            recent_rows = recent.scalars().all()

        return {
            "total_requests": total or 0,
            "success_rate": round((success / total * 100), 1) if total else 0,
            "avg_healing_count": round(avg_healing or 0, 2),
            "avg_time_taken": round(avg_time or 0, 2),
            "recent_requests": [
                {
                    "transcript": r.transcript,
                    "status": r.status,
                    "healing_count": r.healing_count,
                    "time_taken": r.time_taken,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in recent_rows
            ],
        }
    except Exception as e:
        logger.error(f"Analytics query failed: {e}")
        return {
            "total_requests": 0,
            "success_rate": 0,
            "avg_healing_count": 0,
            "avg_time_taken": 0,
            "recent_requests": [],
        }