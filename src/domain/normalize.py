"""Typed cleanup for scraped attributes.

Historical rows and new scrapes share this function. It drops challenge pages,
authwalls, SEO directives, and digit strings that are not phone numbers.
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser


class EntityType:
    PERSON = "PERSON"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    ADDRESS = "ADDRESS"
    ORGANIZATION = "ORGANIZATION"
    PROVENANCE = "PROVENANCE"


_NOISE_PATTERNS = (
    re.compile(r"cloudflare", re.IGNORECASE),
    re.compile(r"attention required", re.IGNORECASE),
    re.compile(r"sign up \| linkedin", re.IGNORECASE),
    re.compile(r"noodp", re.IGNORECASE),
    re.compile(r"noindex", re.IGNORECASE),
)

# Practical RFC 5322 check from the review, not the full ABNF.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$"
)
_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_EXT_RE = re.compile(r"(?:ext\.?|extension|x)\s*\d+\s*$", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


@dataclass(frozen=True)
class NormalizedNode:
    id: str
    type: str
    value: str
    source_domain: str
    confidence: float
    raw_metadata_key: str


def sanitize_string(value: str) -> str:
    """Drop tags and scriptable markup. The text that remains is inert."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    if not text:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        extracted = "".join(parser.parts)
    except Exception:
        extracted = _TAG_RE.sub(" ", text)
    extracted = _TAG_RE.sub(" ", extracted)
    return _WS_RE.sub(" ", extracted).strip()


def is_garbage_record(value: str) -> bool:
    if not value:
        return False
    return any(pattern.search(value) for pattern in _NOISE_PATTERNS)


def normalize_phone(raw_phone: str):
    """Return E.164 or None.

    Ten-digit US numbers gain +1. Digit strings shorter than 10 or longer than
    15 are rejected. A bare digit string is kept only when it is 10 digits or
    an 11-digit NANP number already prefixed with 1. That second gate drops
    database ids such as the 13-digit FindAGrave memorial 1173320481173, which
    still sits inside the 10-15 window.
    """
    if raw_phone is None:
        return None
    without_ext = _EXT_RE.sub("", str(raw_phone).strip())
    cleaned = re.sub(r"[^\d+]", "", without_ext)
    if not cleaned or cleaned.count("+") > 1 or "+" in cleaned[1:]:
        return None
    digits = cleaned[1:] if cleaned.startswith("+") else cleaned
    if not digits.isdigit() or len(digits) < 10 or len(digits) > 15:
        return None
    if cleaned.startswith("+"):
        candidate = "+" + digits
    elif len(digits) == 10:
        candidate = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        candidate = "+" + digits
    else:
        return None
    if not _E164_RE.fullmatch(candidate):
        return None
    national = candidate[1:]
    if len(national) < 10 or len(national) > 15:
        return None
    return candidate


def normalize_email(raw_email: str):
    if raw_email is None:
        return None
    cleaned = str(raw_email).strip().lower()
    if not cleaned or not _EMAIL_RE.fullmatch(cleaned):
        return None
    return cleaned


def _classify(key: str):
    lowered = (key or "").lower()
    if "phone" in lowered or "telephone" in lowered or lowered in {"tel", "mobile"}:
        return EntityType.PHONE, 0.95
    if "email" in lowered or "e-mail" in lowered:
        return EntityType.EMAIL, 0.98
    if "person" in lowered or "names" in lowered or lowered == "name" or lowered.endswith(".name"):
        return EntityType.PERSON, 0.85
    if any(token in lowered for token in ("address", "postaladdress", "street", "locality")):
        return EntityType.ADDRESS, 0.90
    if any(token in lowered for token in ("organization", "organisation", "school", "company", "employer")):
        return EntityType.ORGANIZATION, 0.80
    return EntityType.PROVENANCE, 0.5


def _canonical_value(entity_type: str, value: str) -> str:
    folded = _WS_RE.sub(" ", value).strip()
    if entity_type in {EntityType.PERSON, EntityType.ORGANIZATION, EntityType.ADDRESS, EntityType.PROVENANCE}:
        return folded.casefold()
    return folded


def process_record(domain: str, key: str, raw_value: str):
    original = "" if raw_value is None else str(raw_value)
    if is_garbage_record(original):
        return None
    safe_value = sanitize_string(original)
    if not safe_value or is_garbage_record(safe_value):
        return None

    entity_type, confidence = _classify(key)
    normalized = safe_value
    if entity_type == EntityType.PHONE:
        normalized = normalize_phone(safe_value)
        if not normalized:
            return None
    elif entity_type == EntityType.EMAIL:
        normalized = normalize_email(safe_value)
        if not normalized:
            return None

    identity = _canonical_value(entity_type, normalized)
    return NormalizedNode(
        id=f"{entity_type}:{identity}",
        type=entity_type,
        value=normalized,
        source_domain=domain or "",
        confidence=confidence,
        raw_metadata_key=key or "",
    )
