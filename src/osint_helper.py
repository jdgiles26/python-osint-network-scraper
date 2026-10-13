"""
OSINT Helper module for Gemini Scraper.
Contains regex patterns for entity extraction and search dork templates.
"""
import re
from typing import List, Optional, Pattern

try:
    from domain.normalize import normalize_email, normalize_phone
except ImportError:  # imported as src.osint_helper from the repo root
    from src.domain.normalize import normalize_email, normalize_phone

# Bounded patterns: no nested ambiguous quantifiers. Length caps keep a long
# digit/separator dump on a linear scan.
_EMAIL_ATOM = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
_EMAIL_DOMAIN = r"[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+"
PATTERNS = {
    "email": re.compile(rf"(?<![\w.]){_EMAIL_ATOM}@{_EMAIL_DOMAIN}(?![\w-])"),
    "phone": re.compile(
        r"(?<!\d)(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
    ),
    "ipv4": re.compile(r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'),
    "social": {
        "twitter": re.compile(r'(?:twitter\.com|x\.com)/([a-zA-Z0-9_]{1,15})', re.IGNORECASE),
        "linkedin": re.compile(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', re.IGNORECASE),
        "instagram": re.compile(r'instagram\.com/([a-zA-Z0-9_.]+)', re.IGNORECASE),
        "facebook": re.compile(r'facebook\.com/([a-zA-Z0-9_.]+)', re.IGNORECASE)
    },
    "crypto": {
        "btc": re.compile(r'\b(bc1|[13])[a-zA-Z0-9]{25,39}\b'),
        "eth": re.compile(r'\b0x[a-fA-F0-9]{40}\b')
    }
}

# --- Keyword Matching Helpers ---
_KEYWORD_SPLIT_RE = re.compile(r"[|,;\n]+")

def split_keywords(raw: str) -> List[str]:
    """
    Split raw keyword input on common separators while keeping phrases intact.
    """
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    parts = [part.strip() for part in _KEYWORD_SPLIT_RE.split(raw) if part.strip()]
    return parts or [raw]

def _compile_phrase(token: str) -> Optional[Pattern[str]]:
    token = (token or "").strip().strip('"').strip("'")
    if not token:
        return None
    # Allow flexible whitespace between words while keeping literals safe.
    words = token.split()
    if len(words) > 1:
        core = r"\s+".join(re.escape(word) for word in words)
    else:
        core = re.escape(token)
    # Use word boundaries only when the phrase is word-like at both ends.
    if token[0].isalnum() and token[-1].isalnum():
        core = rf"\b{core}\b"
    return re.compile(core, re.IGNORECASE)

def build_keyword_patterns(raw: str) -> List[Pattern[str]]:
    """
    Compile keyword input into a list of case-insensitive regex patterns.
    """
    patterns: List[Pattern[str]] = []
    seen = set()
    for token in split_keywords(raw):
        if pattern := _compile_phrase(token):
            if pattern.pattern not in seen:
                patterns.append(pattern)
                seen.add(pattern.pattern)
        if " " in token:
            for word in token.split():
                if len(word) < 3:
                    continue
                if word_pattern := _compile_phrase(word):
                    if word_pattern.pattern not in seen:
                        patterns.append(word_pattern)
                        seen.add(word_pattern.pattern)
    return patterns

def match_any(text: str, patterns: List[Pattern[str]]) -> bool:
    """
    Returns True if any pattern matches the given text.
    """
    if not text or not patterns:
        return False
    return any(pattern.search(text) for pattern in patterns)

def find_first_match(text: str, patterns: List[Pattern[str]]) -> Optional[re.Match]:
    """
    Returns the first regex match across the provided patterns, if any.
    """
    if not text or not patterns:
        return None
    for pattern in patterns:
        if match := pattern.search(text):
            return match
    return None

# --- Dorking Templates ---
DORKS = {
    "files": "ext:pdf OR ext:docx OR ext:xlsx OR ext:pptx OR ext:txt",
    "configs": "ext:conf OR ext:env OR ext:ini OR ext:yml OR ext:json",
    "social": "site:linkedin.com OR site:twitter.com OR site:facebook.com OR site:instagram.com",
    "login": "inurl:login OR inurl:signin OR inurl:admin",
    "directory": "intitle:\"index of\"",
    "email_lists": "filetype:xls inurl:\"email.xls\" OR filetype:csv inurl:\"contacts.csv\""
}

def extract_entities(text: str) -> dict:
    """
    Scans text for various entities using regex patterns.
    Returns a dictionary of found unique entities.
    """
    if not text:
        return {}
    
    results = {
        "emails": set(),
        "phones": set(),
        "ipv4": set(),
        "socials": set(),
        "crypto": set()
    }

    # Emails are kept only when the practical RFC 5322 check accepts them.
    for match in PATTERNS["email"].finditer(text):
        email = normalize_email(match.group(0))
        if email:
            results["emails"].add(email)

    # Phones are validated to E.164. Long digit runs fail the trailing boundary
    # and never reach the normalizer as a substring of a database id.
    for match in PATTERNS["phone"].finditer(text):
        phone = normalize_phone(match.group(0))
        if phone:
            results["phones"].add(phone)

    # IPv4
    results["ipv4"].update(PATTERNS["ipv4"].findall(text))

    # Socials
    for platform, pattern in PATTERNS["social"].items():
        for handle in pattern.findall(text):
            results["socials"].add(f"{platform}:{handle}")

    # Crypto
    for coin, pattern in PATTERNS["crypto"].items():
        for wallet in pattern.findall(text):
            results["crypto"].add(f"{coin}:{wallet}")

    # Convert sets to sorted lists for reporting
    return {k: sorted(list(v)) for k, v in results.items() if v}

def apply_dork(keyword: str, dork_type: str) -> str:
    """
    Combines a keyword with a dork template.
    """
    if not dork_type or dork_type not in DORKS:
        return keyword
    
    dork = DORKS[dork_type]
    return f"{keyword} ({dork})"
