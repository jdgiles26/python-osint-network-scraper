"""Install the known model libraries into the Python that is running the app."""
import subprocess
import sys
import threading

from src.application.packages import NO_LIBRARY, PACKAGES


ALLOWED = frozenset(name for names in PACKAGES.values() for name in names)
_LOCK = threading.Lock()


def install_packages(packages) -> tuple:
    """Run pip for an allowlisted set of packages. Returns (ok, message)."""
    names = tuple(str(name) for name in (packages or ()))
    if not names:
        return False, NO_LIBRARY
    if any(name not in ALLOWED for name in names):
        return False, "Refusing to install an unknown package."
    if not _LOCK.acquire(blocking=False):
        return False, "An install is already running."
    try:
        return _pip(names)
    finally:
        _LOCK.release()


def _pip(names: tuple) -> tuple:
    command = [sys.executable, "-m", "pip", "install", *names]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1800,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, "The install timed out after 30 minutes."
    except OSError as exc:
        return False, f"Could not start pip: {exc}"
    if completed.returncode != 0:
        detail = _tail(completed.stdout, completed.stderr)
        return False, detail or "pip install failed."
    return True, f"Installed {' and '.join(names)}. Press Test in Model setup."


def _tail(stdout: str, stderr: str) -> str:
    text = "\n".join(part.strip() for part in (stdout or "", stderr or "") if part and part.strip())
    if len(text) <= 700:
        return text
    return text[-700:]
