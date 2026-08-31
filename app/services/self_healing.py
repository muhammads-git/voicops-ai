# --- self_healing: validates generated code and auto-fixes errors via LLM ---

import logging
from app.services.api_service import groq_client
from app.services.validator import validate_dockerfile, validate_terraform

logger = logging.getLogger(__name__)

MAX_HEALING_ATTEMPTS = 3

HEALING_PROMPT_DOCKER = """You generated a Dockerfile that failed validation.
Original Dockerfile:
```
{content}
```
Validation errors:
{errors}

Fix the Dockerfile. Respond ONLY with the corrected Dockerfile, no explanations or markdown fences."""

HEALING_PROMPT_TERRAFORM = """You generated a Terraform main.tf that failed validation.
Original main.tf:
```
{content}
```
Validation errors:
{errors}

Fix the Terraform file. Respond ONLY with the corrected main.tf content, no explanations or markdown fences."""


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences that the LLM may wrap around its response."""
    text = text.strip()
    # Remove opening fence (with optional language identifier like ```dockerfile or ```hcl)
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 2
        text = text[first_newline + 1:]
    # Remove closing fence
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def heal_dockerfile(content: str) -> dict:
    """
    Validates a Dockerfile and attempts to heal it if invalid.
    Returns {"content": str, "valid": bool, "healing_count": int, "tool_available": bool}.
    """
    result = await validate_dockerfile(content)

    # If valid or tool not available, return immediately
    if result["valid"] or not result["tool_available"]:
        return {
            "content": content,
            "valid": result["valid"],
            "healing_count": 0,
            "tool_available": result["tool_available"],
        }

    current_content = content
    errors = result["errors"]

    for attempt in range(1, MAX_HEALING_ATTEMPTS + 1):
        logger.info(f"Dockerfile healing attempt {attempt}/{MAX_HEALING_ATTEMPTS}")

        try:
            prompt = HEALING_PROMPT_DOCKER.format(
                content=current_content,
                errors="\n".join(f"- {e}" for e in errors),
            )
            response = await groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "You are a Dockerfile expert. Fix the given Dockerfile based on the validation errors. Return ONLY the fixed Dockerfile."},
                    {"role": "user", "content": prompt},
                ],
            )
            fixed_content = strip_code_fences(response.choices[0].message.content)

            # Re-validate the fixed content
            result = await validate_dockerfile(fixed_content)
            current_content = fixed_content

            if result["valid"]:
                logger.info(f"Dockerfile healed successfully on attempt {attempt}")
                return {
                    "content": current_content,
                    "valid": True,
                    "healing_count": attempt,
                    "tool_available": True,
                }

            errors = result["errors"]

        except Exception as e:
            logger.error(f"Dockerfile healing attempt {attempt} failed: {e}")
            # Return the last version we have — healing failure should never crash the request
            return {
                "content": current_content,
                "valid": False,
                "healing_count": attempt - 1,
                "tool_available": True,
            }

    # Exhausted all attempts
    logger.warning(f"Dockerfile still invalid after {MAX_HEALING_ATTEMPTS} healing attempts")
    return {
        "content": current_content,
        "valid": False,
        "healing_count": MAX_HEALING_ATTEMPTS,
        "tool_available": True,
    }


async def heal_terraform(content: str) -> dict:
    """
    Validates a Terraform main.tf and attempts to heal it if invalid.
    Returns {"content": str, "valid": bool, "healing_count": int, "tool_available": bool}.
    """
    result = await validate_terraform(content)

    # If valid or tool not available, return immediately
    if result["valid"] or not result["tool_available"]:
        return {
            "content": content,
            "valid": result["valid"],
            "healing_count": 0,
            "tool_available": result["tool_available"],
        }

    current_content = content
    errors = result["errors"]

    for attempt in range(1, MAX_HEALING_ATTEMPTS + 1):
        logger.info(f"Terraform healing attempt {attempt}/{MAX_HEALING_ATTEMPTS}")

        try:
            prompt = HEALING_PROMPT_TERRAFORM.format(
                content=current_content,
                errors="\n".join(f"- {e}" for e in errors),
            )
            response = await groq_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "You are a Terraform expert. Fix the given main.tf based on the validation errors. Return ONLY the fixed Terraform code."},
                    {"role": "user", "content": prompt},
                ],
            )
            fixed_content = strip_code_fences(response.choices[0].message.content)

            # Re-validate the fixed content
            result = await validate_terraform(fixed_content)
            current_content = fixed_content

            if result["valid"]:
                logger.info(f"Terraform healed successfully on attempt {attempt}")
                return {
                    "content": current_content,
                    "valid": True,
                    "healing_count": attempt,
                    "tool_available": True,
                }

            errors = result["errors"]

        except Exception as e:
            logger.error(f"Terraform healing attempt {attempt} failed: {e}")
            return {
                "content": current_content,
                "valid": False,
                "healing_count": attempt - 1,
                "tool_available": True,
            }

    # Exhausted all attempts
    logger.warning(f"Terraform still invalid after {MAX_HEALING_ATTEMPTS} healing attempts")
    return {
        "content": current_content,
        "valid": False,
        "healing_count": MAX_HEALING_ATTEMPTS,
        "tool_available": True,
    }
