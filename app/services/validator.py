# --- validator: runs linters on generated configs before the user sees them ---

import asyncio
import json
import logging
import shutil
import tempfile
import os

logger = logging.getLogger(__name__)

# 15-second timeout for all subprocess calls
SUBPROCESS_TIMEOUT = 15


async def validate_dockerfile(content: str) -> dict:
    """
    Validates a Dockerfile using hadolint.
    Returns {"valid": bool|None, "errors": [str], "tool_available": bool}.
    valid=None when validation could not complete (tool missing, timeout, crash).
    If hadolint is not installed, returns tool_available=False (graceful degradation).
    """
    if not shutil.which("hadolint"):
        logger.info("hadolint not installed — skipping Dockerfile validation")
        return {"valid": None, "errors": [], "tool_available": False}

    try:
        proc = await asyncio.create_subprocess_exec(
            "hadolint", "--format", "json", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=content.encode()),
            timeout=SUBPROCESS_TIMEOUT,
        )

        if not stdout:
            # hadolint outputs nothing = no errors
            return {"valid": True, "errors": [], "tool_available": True}

        results = json.loads(stdout.decode())
        if not results:
            return {"valid": True, "errors": [], "tool_available": True}

        errors = [
            f"Line {r.get('line', '?')}: {r.get('message', 'unknown issue')} ({r.get('code', '')})"
            for r in results
        ]
        return {"valid": False, "errors": errors, "tool_available": True}

    except asyncio.TimeoutError:
        logger.warning("hadolint timed out after 15s")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except Exception as e:
        logger.error(f"hadolint error: {e}")
        return {"valid": None, "errors": [str(e)], "tool_available": True}


async def validate_terraform(content: str) -> dict:
    """
    Validates a Terraform main.tf using terraform validate.
    Returns {"valid": bool|None, "errors": [str], "tool_available": bool}.
    valid=None when validation could not complete (tool missing, timeout, crash).
    If terraform is not installed, returns tool_available=False (graceful degradation).
    """
    if not shutil.which("terraform"):
        logger.info("terraform not installed — skipping Terraform validation")
        return {"valid": None, "errors": [], "tool_available": False}

    tmpdir = tempfile.mkdtemp(prefix="voicops_tf_")
    try:
        # Write main.tf to temp directory
        tf_path = os.path.join(tmpdir, "main.tf")
        with open(tf_path, "w", encoding="utf-8") as f:
            f.write(content)

        # terraform init -backend=false (required before validate)
        proc = await asyncio.create_subprocess_exec(
            "terraform", "init", "-backend=false", "-no-color",
            cwd=tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)  # init can take longer (plugin download)

        if proc.returncode != 0:
            logger.warning("terraform init failed — skipping validation")
            return {"valid": None, "errors": ["terraform init failed"], "tool_available": True}

        # terraform validate -json
        proc = await asyncio.create_subprocess_exec(
            "terraform", "validate", "-json", "-no-color",
            cwd=tmpdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=SUBPROCESS_TIMEOUT,
        )

        result = json.loads(stdout.decode())
        if result.get("valid", False):
            return {"valid": True, "errors": [], "tool_available": True}

        errors = []
        for diag in result.get("diagnostics", []):
            summary = diag.get("summary", "unknown error")
            detail = diag.get("detail", "")
            msg = summary
            if detail:
                msg += f": {detail}"
            errors.append(msg)

        return {"valid": False, "errors": errors, "tool_available": True}

    except asyncio.TimeoutError:
        logger.warning("terraform validate timed out after 15s")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except Exception as e:
        logger.error(f"terraform validate error: {e}")
        return {"valid": None, "errors": [str(e)], "tool_available": True}
    finally:
        # Clean up temp directory
        try:
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
