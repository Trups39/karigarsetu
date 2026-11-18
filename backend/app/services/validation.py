"""Field rules shared by every form (contact, supplier sign-up, add a design).

The website applies the same rules in frontend/index.html (RULES), so people see the problem under the field
before sending, and the server applies them again so they can't be skipped.
Each check returns the cleaned value, or raises HTTPException(400, <message to show>).
"""

import re
import unicodedata

from fastapi import HTTPException

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}$"
)


def _fail(message: str):
    raise HTTPException(400, message)


def _squash(value: str | None) -> str:
    return " ".join((value or "").split())


def _letters_ok(text: str, extra: str) -> bool:
    """Only letters (any language, incl. Marathi/Hindi marks) and the extra characters, with at least one letter."""
    return all(ch.isalpha() or unicodedata.category(ch).startswith("M") or ch in extra for ch in text) and any(
        ch.isalpha() for ch in text
    )


def person_name(value: str | None) -> str:
    v = _squash(value)
    if len(v) < 2:
        _fail("Please enter your name.")
    if len(v) > 100:
        _fail("Name is too long (max 100 characters).")
    if not _letters_ok(v, " .'-"):
        _fail("Name can only have letters, spaces, dots, apostrophes and hyphens.")
    return v


def business_name(value: str | None) -> str:
    v = _squash(value)
    if len(v) < 2:
        _fail("Please enter your business name.")
    if len(v) > 100:
        _fail("Business name is too long (max 100 characters).")
    if not _letters_ok(v.replace("&", "").translate(str.maketrans("", "", "0123456789")), " .,'-()/"):
        _fail("Business name can have letters, numbers, spaces and . , & ' - ( ) /")
    return v


def place_or_craft(value: str | None, label: str) -> str:
    v = _squash(value)
    if len(v) < 2:
        _fail(f"Please enter your {label}.")
    if len(v) > 80:
        _fail(f"{label[0].upper() + label[1:]} is too long (max 80 characters).")
    if not _letters_ok(v.replace("&", ""), " .,'-()/"):
        _fail(f"{label[0].upper() + label[1:]} can only have letters, spaces and . , & ' - ( ) /")
    return v


def email(value: str | None) -> str:
    v = (value or "").strip().lower()
    if not v:
        _fail("Please enter your email address.")
    if len(v) > 254 or ".." in v or not EMAIL_RE.match(v):
        _fail("Please enter a valid email address, like name@example.com.")
    return v


def whatsapp(value: str | None) -> str:
    """Digits with country code. A 10-digit Indian mobile (starting 6-9) gets 91 in front."""
    raw = (value or "").strip()
    if not raw:
        _fail("Please enter your WhatsApp number.")
    if not re.fullmatch(r"\+?[\d\s()-]+", raw):
        _fail("WhatsApp number can only have digits, spaces, + and -.")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        if digits[0] not in "6789":
            _fail("Indian mobile numbers start with 6, 7, 8 or 9. Add the country code for other countries.")
        digits = "91" + digits
    if digits.startswith("91") and len(digits) == 12 and digits[2] not in "6789":
        _fail("Indian mobile numbers start with 6, 7, 8 or 9.")
    if not 11 <= len(digits) <= 15:
        _fail("Please enter a valid WhatsApp number: 10 digits, or with the country code.")
    return digits


def optional_phone(value: str | None) -> str:
    v = _squash(value)
    if not v:
        return ""
    if not re.fullmatch(r"\+?[\d\s()-]+", v):
        _fail("Phone number can only have digits, spaces, + and -.")
    if not 10 <= len(re.sub(r"\D", "", v)) <= 15:
        _fail("Please enter a valid phone number (10 to 15 digits), or leave it empty.")
    return v


def new_password(value: str | None, email_address: str = "") -> str:
    p = value or ""
    if len(p) < 8:
        _fail("Password must be at least 8 characters.")
    if len(p.encode()) > 72:
        _fail("Password is too long (max 72 characters).")
    if not re.search(r"[A-Za-zऀ-ॿ]", p) or not re.search(r"\d", p):
        _fail("Password needs at least one letter and one number.")
    if email_address and p.lower() == email_address.lower():
        _fail("Password can't be the same as your email.")
    if p.strip() != p:
        _fail("Password can't start or end with a space.")
    return p


def message(value: str | None, min_len: int = 10, max_len: int = 2000) -> str:
    v = (value or "").strip()
    if len(v) < min_len:
        _fail(f"Please write a message (at least {min_len} characters).")
    if len(v) > max_len:
        _fail(f"Message is too long (max {max_len} characters).")
    return v


def design_name(value: str | None) -> str:
    v = _squash(value)
    if len(v) < 2:
        _fail("Enter the design name.")
    if len(v) > 80:
        _fail("Design name is too long (max 80 characters).")
    if not _letters_ok(v.translate(str.maketrans("", "", "0123456789")), " .,'-()/&"):
        _fail("Design name can have letters, numbers, spaces and . , ' - ( ) / &")
    return v


def whole_number(value, label: str, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        _fail(f"{label} must be a whole number.")
    if float(value) != n:
        _fail(f"{label} must be a whole number.")
    if not low <= n <= high:
        _fail(f"{label} must be between {low:,} and {high:,}.")
    return n


def sizes(value: str | None) -> list[int]:
    parts = [p for p in re.split(r"[,\s]+", (value or "").strip()) if p]
    if not parts:
        _fail("Enter the sizes, e.g. 6,7,8,9,10")
    if not all(p.isdigit() for p in parts):
        _fail("Sizes must be numbers separated by commas, e.g. 6,7,8,9,10")
    nums = [int(p) for p in parts]
    if any(n < 1 or n > 15 for n in nums):
        _fail("Sizes must be between 1 and 15.")
    if len(set(nums)) != len(nums):
        _fail("Each size only once, please.")
    return sorted(nums)
