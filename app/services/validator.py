# --- validator: runs linters on generated configs before the user sees them ---

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from yamllint import linter as yamllint_linter
from yamllint.config import YamlLintConfig

logger = logging.getLogger(__name__)

# 15-second timeout for all subprocess calls
SUBPROCESS_TIMEOUT = 15

# Dedicated executor prevents validation tasks from exhausting the default
# thread pool used by asyncio.to_thread elsewhere in the app.
VALIDATION_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="voicops_val")

# Project-local bin directory for validator tools (see install_validators.ps1)
BIN_DIR = Path(__file__).resolve().parent.parent.parent / "bin"


def find_tool(name: str) -> str | None:
    """Locates a tool binary — checks system PATH first, then project bin/ directory."""
    path = shutil.which(name)
    if path:
        return path
    local_path = BIN_DIR / (name + ".exe" if os.name == "nt" else name)
    if local_path.is_file():
        return str(local_path)
    return None


async def validate_dockerfile(content: str) -> dict:
    """
    Validates a Dockerfile using hadolint.
    Returns {"valid": bool|None, "errors": [str], "tool_available": bool}.
    valid=None when validation could not complete (tool missing, timeout, crash).
    If hadolint is not installed, returns tool_available=False (graceful degradation).
    """
    hadolint = find_tool("hadolint")
    if not hadolint:
        logger.info("hadolint not installed — skipping Dockerfile validation")
        return {"valid": None, "errors": [], "tool_available": False}

    def _run_hadolint():
        proc = subprocess.run(
            [hadolint, "--format", "json", "-"],
            input=content.encode(),
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        return proc.stdout, proc.stderr, proc.returncode

    try:
        loop = asyncio.get_running_loop()
        stdout, stderr, returncode = await asyncio.wait_for(
            loop.run_in_executor(VALIDATION_EXECUTOR, _run_hadolint),
            timeout=60,  # generous overall ceiling; subprocess itself is capped at 15s
        )

        if stderr:
            stderr_text = stderr.decode(errors="replace").strip()
            if stderr_text:
                logger.warning(f"hadolint stderr: {stderr_text}")

        if returncode != 0 and not stdout:
            # hadolint exited with an error but produced no JSON output
            err_text = stderr.decode(errors="replace").strip() or "hadolint exited with errors"
            return {"valid": None, "errors": [err_text], "tool_available": True}

        if not stdout:
            # hadolint outputs nothing = no errors
            return {"valid": True, "errors": [], "tool_available": True}

        try:
            results = json.loads(stdout.decode())
        except json.JSONDecodeError as e:
            logger.error(f"hadolint returned invalid JSON: {e}")
            return {"valid": None, "errors": ["hadolint returned invalid JSON"], "tool_available": True}

        if not results:
            return {"valid": True, "errors": [], "tool_available": True}

        errors = [
            f"Line {r.get('line', '?')}: {r.get('message', 'unknown issue')} ({r.get('code', '')})"
            for r in results
            if r.get("message") or r.get("code")
        ]
        return {"valid": False, "errors": errors, "tool_available": True}

    except asyncio.TimeoutError:
        logger.warning("hadolint timed out after 15s")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except subprocess.TimeoutExpired:
        logger.warning("hadolint subprocess timed out after 15s")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except Exception as e:
        err_msg = str(e).strip() or f"{type(e).__name__}: {getattr(e, 'args', '')}"
        logger.error(f"hadolint error: {err_msg}")
        return {"valid": None, "errors": [err_msg], "tool_available": True}


async def validate_terraform(content: str) -> dict:
    """
    Validates a Terraform main.tf using terraform validate.
    Returns {"valid": bool|None, "errors": [str], "tool_available": bool}.
    valid=None when validation could not complete (tool missing, timeout, crash).
    If terraform is not installed, returns tool_available=False (graceful degradation).
    """
    terraform = find_tool("terraform")
    if not terraform:
        logger.info("terraform not installed — skipping Terraform validation")
        return {"valid": None, "errors": [], "tool_available": False}

    tmpdir = tempfile.mkdtemp(prefix="voicops_tf_")

    def _run_terraform():
        tf_path = os.path.join(tmpdir, "main.tf")
        with open(tf_path, "w", encoding="utf-8") as f:
            f.write(content)

        # terraform init -backend=false (required before validate)
        init_proc = subprocess.run(
            [terraform, "init", "-backend=false", "-no-color"],
            cwd=tmpdir,
            capture_output=True,
            timeout=60,
        )
        if init_proc.returncode != 0:
            stderr_text = init_proc.stderr.decode(errors="replace").strip()
            logger.warning(f"terraform init failed: {stderr_text}")
            return None, stderr_text or "terraform init failed", init_proc.returncode

        # terraform validate -json
        validate_proc = subprocess.run(
            [terraform, "validate", "-json", "-no-color"],
            cwd=tmpdir,
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        return validate_proc.stdout, validate_proc.stderr, validate_proc.returncode

    try:
        loop = asyncio.get_running_loop()
        stdout, stderr, returncode = await asyncio.wait_for(
            loop.run_in_executor(VALIDATION_EXECUTOR, _run_terraform),
            timeout=120,  # terraform init can be slow; subprocess calls enforce their own shorter timeouts
        )

        if returncode != 0 and not stdout:
            err_text = stderr.decode(errors="replace").strip() or "terraform validate failed"
            return {"valid": None, "errors": [err_text], "tool_available": True}

        try:
            result = json.loads(stdout.decode())
        except json.JSONDecodeError as e:
            logger.error(f"terraform validate returned invalid JSON: {e}")
            return {"valid": None, "errors": ["terraform validate returned invalid JSON"], "tool_available": True}

        if result.get("valid", False):
            return {"valid": True, "errors": [], "tool_available": True}

        errors = []
        for diag in result.get("diagnostics", []):
            summary = diag.get("summary", "unknown error")
            detail = diag.get("detail", "")
            msg = summary
            if detail:
                msg += f": {detail}"
            if msg.strip():
                errors.append(msg)

        return {"valid": False, "errors": errors, "tool_available": True}

    except asyncio.TimeoutError:
        logger.warning("terraform validate timed out")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except subprocess.TimeoutExpired:
        logger.warning("terraform validate subprocess timed out")
        return {"valid": None, "errors": ["Validation timed out"], "tool_available": True}
    except Exception as e:
        err_msg = str(e).strip() or f"{type(e).__name__}: {getattr(e, 'args', '')}"
        logger.error(f"terraform validate error: {err_msg}")
        return {"valid": None, "errors": [err_msg], "tool_available": True}
    finally:
        # Clean up temp directory
        try:
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# yamllint config: checks structural validity without style nitpicks
_YAMLLINT_CONFIG = YamlLintConfig(
    "rules:\n"
    "  key-duplicates: enable\n"
    "  empty-values: enable\n"
    "  indentation: {spaces: 2, indent-sequences: whatever}\n"
    "  new-line-at-end-of-file: disable\n"
    "  trailing-spaces: disable\n"
    "  document-start: disable\n"
    "  line-length: disable\n"
    "  truthy: disable\n"
    "  comments: disable\n"
    "  comments-indentation: disable\n"
    "  brackets: disable\n"
    "  colons: disable\n"
    "  commas: disable\n"
    "  empty-lines: disable\n"
    "  hyphens: disable\n"
    "  anchors: disable\n"
    "  octal-values: disable\n"
)


async def validate_compose(content: str) -> dict:
    """
    Validates a docker-compose.yml using yamllint (Python library).
    Returns {"valid": bool|None, "errors": [str], "tool_available": bool}.
    yamllint is always available (pip-installed), so tool_available is always True.
    """
    try:
        problems = list(yamllint_linter.run(content, _YAMLLINT_CONFIG))
        if not problems:
            return {"valid": True, "errors": [], "tool_available": True}

        errors = []
        for p in problems:
            errors.append(f"Line {p.line}: {p.message} ({p.rule})")

        return {"valid": False, "errors": errors, "tool_available": True}

    except Exception as e:
        logger.error(f"yamllint error: {e}")
        return {"valid": None, "errors": [str(e)], "tool_available": True}
