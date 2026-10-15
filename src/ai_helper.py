"""
AI helper utilities for Gemini-powered selector generation.
Imports are guarded so the app can still launch when google-generativeai
is missing or incompatible; callers can inspect get_last_error() for details.
"""
import os
import typing as _typing

try:
    import google.generativeai as genai
except Exception as exc:  # Broad to catch runtime import errors from the package
    genai = None
    _import_error = exc
else:
    _import_error = None

try:
    from PIL import Image
except Exception as exc:
    Image = None
    _image_error = exc
else:
    _image_error = None

_last_error: _typing.Optional[str] = None


def _set_error(message: _typing.Optional[str]):
    global _last_error
    _last_error = message

def _resolve_api_key(api_key: _typing.Optional[str]) -> str:
    """
    Prefer an explicit key, otherwise fall back to common env vars so the app
    can auto-configure when the user has GEMINI_API_KEY/GOOGLE_API_KEY set.
    """
    return (
        api_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_AI_API_KEY")
        or os.getenv("GENAI_API_KEY")
        or ""
    )


def get_last_error() -> _typing.Optional[str]:
    """Return the most recent AI configuration/runtime error, if any."""
    return _last_error


def _require_client(capability: str) -> bool:
    if genai is None:
        _set_error(
            "Gemini client unavailable: google-generativeai import failed "
            f"({_import_error}). Try reinstalling/upgrading google-generativeai and google-ai-generativelanguage."
        )
        return False
    if capability == "image" and Image is None:
        _set_error(f"Pillow import failed; Vision AI disabled ({_image_error}).")
        return False
    return True

# gemini-pro and gemini-pro-vision no longer answer. These ids still do.
GEMINI_TEXT_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
)


def _generate_with_models(content):
    """Try each current Gemini model. The first text answer wins."""
    if genai is None:
        return None, get_last_error() or "Gemini client unavailable."
    last_error = "No Gemini model answered."
    for name in GEMINI_TEXT_MODELS:
        try:
            model = genai.GenerativeModel(name)
            response = model.generate_content(content)
            text = getattr(response, "text", "") or ""
            if str(text).strip():
                return str(text), None
            last_error = f"{name} returned an empty answer."
        except Exception as exc:
            last_error = f"{name}: {exc}"
    return None, last_error


def generate_text(prompt, api_key=None):
    """Free-form answer for the results chat. Selector helpers stay separate."""
    if not prompt or not str(prompt).strip():
        return None, "A prompt is required."
    if not configure_api(api_key):
        return None, get_last_error()
    if not _require_client("text"):
        return None, get_last_error()
    return _generate_with_models(prompt)


def _clean_selector(raw):
    """Normalize LLM output to a single CSS selector line."""
    if not raw:
        return ""
    selector = raw.strip().replace("`", "")
    selector = selector.replace("CSS selector:", "").replace("Selector:", "")
    selector = selector.strip().strip('"').strip("'")
    selector = selector.splitlines()[0].strip()
    return selector

def _is_valid_selector(selector):
    if not selector:
        return False
    descriptive = any(phrase in selector.lower() for phrase in ["css selector", "select the", "this selector", "element that"])
    if descriptive:
        return False
    if len(selector.split()) > 4 and not any(c in selector for c in ['>', '+', '~', '[', '.', '#', ':']):
        return False
    return True

def configure_api(api_key=None):
    """Configures the Google Generative AI API."""
    api_key = _resolve_api_key(api_key)
    if not api_key:
        _set_error("Gemini API key is missing. Set GEMINI_API_KEY or provide it in Settings.")
        return False
    if not _require_client("text"):
        return False
    try:
        genai.configure(api_key=api_key)
        _set_error(None)
        return True
    except Exception as exc:
        _set_error(f"Failed to configure Gemini client: {exc}")
        return False

def generate_selector_from_image(html_content, image_path, description):
    """
    Uses a current Gemini model to generate a CSS selector from a screenshot.
    """
    if not html_content or not image_path:
        return None, "HTML content or image path is missing."
    if not _require_client("image"):
        return None, get_last_error()

    try:
        image = Image.open(image_path)
    except Exception as e:
        return None, f"Failed to open image: {e}"

    # Truncate HTML to stay within token limits
    if len(html_content) > 250000:
        html_content = html_content[:250000]

    prompt = [
        f"""Analyze the attached screenshot of a webpage and the provided HTML source.
        Your task is to identify the single best CSS selector that would extract all elements similar to the main item shown in the image.
        The user has described the target as: "{description}".

        RULES:
        1.  Your answer MUST be only the CSS selector.
        2.  Do NOT include any explanation, markdown, or any text other than the selector itself.
        3.  Choose a selector that is robust enough to apply to all similar items on the page.

        HTML Source:
        {html_content}
        """,
        image
    ]

    raw, err = _generate_with_models(prompt)
    if err or not raw:
        return None, err or "An error occurred with the Vision API."
    selector = _clean_selector(raw)
    if not _is_valid_selector(selector):
        return None, f"AI failed to produce a valid selector. Response: {selector}"
    return selector, None

def generate_css_selector(html_content, description):
    """
    Uses a current Gemini model to generate a CSS selector.
    """
    # This is the text-only fallback
    if not html_content or not description:
        return None, "HTML content or description is missing."
    if not _require_client("text"):
        return None, get_last_error()

    if len(html_content) > 150000:
        html_content = html_content[:150000]
    
    prompt = f"""
    Based on the following HTML snippet, identify the best single CSS selector to extract all elements described as: "{description}".
    Your answer must be only the CSS selector itself, with absolutely no other text, explanation, or markdown.
    HTML:
    {html_content}
    """
    raw, err = _generate_with_models(prompt)
    if err or not raw:
        return None, err or "An error occurred with the AI API."
    selector = _clean_selector(raw)
    if not _is_valid_selector(selector):
        return None, f"AI returned an invalid or descriptive response: '{selector}'"
    return selector, None
