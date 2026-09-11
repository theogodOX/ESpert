import re
from datetime import datetime
from typing import Iterable, Optional

from extraction.schemas import OCREvidence, ProductData
from extraction.evidence import ClassifiedEvidence


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    text = text.strip(" ,;:|")

    return text or None


def evidence_text(item: ClassifiedEvidence) -> str:
    return clean_text(
        getattr(item, "normalized_text", None)
        or getattr(item, "raw_text", None)
    ) or ""


def label_of(item: ClassifiedEvidence) -> str:
    return (
        getattr(item, "label", None)
        or ""
    ).upper().strip()


def group_of(item: ClassifiedEvidence) -> Optional[int]:
    return getattr(item, "group_id", None)


def find_by_label(
    evidence: Iterable[ClassifiedEvidence],
    label: str,
) -> list[str]:

    values = []

    for item in evidence:
        if label_of(item) != label.upper():
            continue

        text = evidence_text(item)

        if text:
            values.append(text)

    return values


def is_label_only_text(text: str) -> bool:

    normalized = text.lower().strip()
    normalized = normalized.rstrip(":")

    return normalized in {
        "mfg",
        "mfg.",
        "mfg date",
        "mfg. date",
        "manufacturing date",
        "manufactured by",
        "manufactured & packed by",
        "packed by",
        "pkd",
        "pkd.",
        "pkd on",
        "pkd. on",
        "packed on",
        "packing date",
        "batch",
        "batch no",
        "batch no.",
        "batch number",
        "lot",
        "lot no",
        "lot no.",
        "mrp",
        "m.r.p",
        "m.r.p.",
        "exp",
        "exp.",
        "expiry",
        "expiry date",
        "exp. date",
        "use by",
        "use before",
        "best before",
        "net quantity",
        "net qty",
        "net wt",
        "net weight",
    }


def normalize_quantity_unit(unit: str) -> str:
    unit = unit.strip()

    mapping = {
        "gm": "g",
        "gms": "g",
        "gram": "g",
        "grams": "g",
        "kgs": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "millilitre": "ml",
        "millilitres": "ml",
        "milliliter": "ml",
        "milliliters": "ml",
        "ltr": "L",
        "litre": "L",
        "litres": "L",
        "liter": "L",
        "liters": "L",
    }

    lower = unit.lower()

    if lower in mapping:
        return mapping[lower]

    if lower == "ml":
        return "ml"

    if lower == "l":
        return "L"

    return unit


def is_date_text(text: str) -> bool:
    return extract_date_from_text(text) is not None


# ============================================================
# DATES
# ============================================================

DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{1,2}[.-]\d{1,2}[.-]\d{2,4}\b",
    r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
    r"[/-]\d{2,4}\b",
    r"\b(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
    r"SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{2,4}\b",
]


def extract_date_from_text(text: str) -> Optional[str]:

    for pattern in DATE_PATTERNS:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0)

    return None


def _date_keyword_matches(
    text: str,
    target_label: str,
) -> bool:

    lower = text.lower()

    if target_label == "MANUFACTURING_DATE":
        return any(
            keyword in lower
            for keyword in [
                "mfg",
                "mfd",
                "manufact",
                "pkd",
                "packed",
                "packing date",
                "packed on",
            ]
        )

    if target_label == "EXPIRY_DATE":
        return any(
            keyword in lower
            for keyword in [
                "exp",
                "expiry",
                "expires",
                "use by",
                "use before",
                "valid till",
                "valid upto",
            ]
        )

    return False


def extract_date(
    evidence: Iterable[ClassifiedEvidence],
    label: str,
) -> Optional[str]:

    items = list(evidence)

    # Priority 1: Classification label match

    for item in sorted(
        items,
        key=lambda x: getattr(x, "confidence", 0.0) or 0.0,
        reverse=True,
    ):

        if label_of(item) != label.upper():
            continue

        text = evidence_text(item)

        if not text:
            continue

        value = extract_date_from_text(text)

        if value:
            return value

    # --------------------------------------------------------
    # PRIORITY 2:
    # Label/value split across neighbouring OCR lines.
    #
    # Example:
    #
    # Pkd. On
    # 01/07/2025
    # --------------------------------------------------------

    for index, item in enumerate(items):

        text = evidence_text(item)

        if not text:
            continue

        if not _date_keyword_matches(text, label):
            continue

        # Date in the same line.
        value = extract_date_from_text(text)

        if value:
            return value

        # Look ahead a few OCR lines.
        for offset in range(1, 4):

            candidate_index = index + offset

            if candidate_index >= len(items):
                break

            candidate_text = evidence_text(
                items[candidate_index]
            )

            if not candidate_text:
                continue

            value = extract_date_from_text(
                candidate_text
            )

            if value:
                return value

            # Do not wander too far into another declaration.
            if any(
                keyword in candidate_text.lower()
                for keyword in [
                    "batch",
                    "mrp",
                    "net weight",
                    "net quantity",
                    "manufactured by",
                    "marketed by",
                ]
            ):
                break

    # --------------------------------------------------------
    # PRIORITY 3:
    # Fallback if the classifier attached the date label
    # incorrectly but the same OCR line contains both.
    # --------------------------------------------------------

    for item in items:

        text = evidence_text(item)

        if not text:
            continue

        value = extract_date_from_text(text)

        if not value:
            continue

        if _date_keyword_matches(
            text,
            label,
        ):
            return value

    return None


# ============================================================
# DERIVED SHELF LIFE
# ============================================================

def calculate_derived_shelf_life(
    mfg_date_str: Optional[str],
    exp_date_str: Optional[str],
) -> Optional[str]:
    """
    Generic date-interval calculation between manufacturing date and expiry date.
    Returns formatted derived shelf life, e.g. '16 months (DERIVED)'.
    """
    if not mfg_date_str or not exp_date_str:
        return None

    def _parse(d_str: str) -> Optional[tuple[int, int, int, bool]]:
        raw = extract_date_from_text(d_str) or str(d_str).strip()
        raw = raw.strip(" ,;:|()[]")

        day_formats = [
            "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
            "%d %b %Y", "%d-%b-%Y", "%d %B %Y",
            "%Y-%m-%d", "%Y/%m/%d",
        ]
        for fmt in day_formats:
            try:
                dt = datetime.strptime(raw, fmt)
                return (dt.year, dt.month, dt.day, True)
            except ValueError:
                pass

        month_formats = [
            "%b/%Y", "%b-%Y", "%b %Y",
            "%B/%Y", "%B-%Y", "%B %Y",
            "%m/%Y", "%m-%Y",
            "%b/%y", "%b-%y", "%b %y",
            "%m/%y", "%m-%y",
        ]
        for fmt in month_formats:
            try:
                dt = datetime.strptime(raw, fmt)
                return (dt.year, dt.month, 1, False)
            except ValueError:
                pass
        return None

    mfg = _parse(mfg_date_str)
    exp = _parse(exp_date_str)
    if not mfg or not exp:
        return None

    y1, m1, d1, has_day1 = mfg
    y2, m2, d2, has_day2 = exp

    if (y2, m2, d2) <= (y1, m1, d1):
        return None

    if has_day1 and has_day2:
        dt1 = datetime(y1, m1, d1)
        dt2 = datetime(y2, m2, d2)
        total_days = (dt2 - dt1).days
        if total_days < 30:
            unit = "day" if total_days == 1 else "days"
            return f"{total_days} {unit} (DERIVED)"
        months = round(total_days / 30.4375)
        unit = "month" if months == 1 else "months"
        return f"{months} {unit} (DERIVED)"
    else:
        total_months = (y2 - y1) * 12 + (m2 - m1)
        if total_months <= 0:
            return None
        unit = "month" if total_months == 1 else "months"
        return f"{total_months} {unit} (DERIVED)"


# ============================================================
# BEST BEFORE
# ============================================================

def extract_best_before(
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:

    items = list(evidence)

    for index, item in enumerate(items):

        text = evidence_text(item)

        if not text:
            continue

        lower = text.lower()

        if (
            label_of(item) == "BEST_BEFORE"
            or "best before" in lower
        ):

            if not is_label_only_text(text):
                return text

            # Value may be on next OCR line.
            if index + 1 < len(items):

                next_text = evidence_text(
                    items[index + 1]
                )

                if next_text:
                    return (
                        f"{text} {next_text}"
                    )

    return None


# ============================================================
# MRP
# ============================================================

MRP_KEYWORD_PATTERN = re.compile(
    r"\b(?:mrp|m\.r\.p\.?|maximum\s+retail\s+price)\b",
    flags=re.IGNORECASE,
)


PRICE_PATTERN = re.compile(
    r"(?:₹|rs\.?|inr)?\s*"
    r"(\d+(?:\.\d{1,2})?)",
    flags=re.IGNORECASE,
)


def extract_price_from_text(
    text: str,
) -> Optional[float]:

    if not text:
        return None

    match = PRICE_PATTERN.search(text)

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_mrp(
    evidence: Iterable[ClassifiedEvidence],
):

    items = list(evidence)

    mrp_value = None
    tax_wording = None

    tax_pattern = re.compile(
        r"\b(?:incl\.?|inclusive)\s+"
        r"(?:of\s+)?all\s+tax(?:es)?\b",
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # PRIORITY 1:
    # Correctly classified MRP evidence.
    # --------------------------------------------------------

    for item in items:

        if label_of(item) != "MRP":
            continue

        text = evidence_text(item)

        if not text:
            continue

        value = extract_price_from_text(
            text
        )

        if value is not None and mrp_value is None:
            mrp_value = value

        if tax_pattern.search(text) and tax_wording is None:
            tax_wording = text

        if mrp_value is not None and tax_wording is not None:
            return mrp_value, tax_wording

    if mrp_value is not None:
        return mrp_value, tax_wording

    # --------------------------------------------------------
    # PRIORITY 2:
    # Explicit MRP keyword.
    # --------------------------------------------------------

    for index, item in enumerate(items):

        text = evidence_text(item)

        if not text:
            continue

        if not MRP_KEYWORD_PATTERN.search(text):
            continue

        # Price on same line.
        value = extract_price_from_text(
            text
        )

        if value is not None:
            mrp_value = value

        if tax_pattern.search(text):
            tax_wording = text

        # Price may be on next few lines.
        if mrp_value is None:

            for offset in range(1, 4):

                candidate_index = index + offset

                if candidate_index >= len(items):
                    break

                candidate_text = evidence_text(
                    items[candidate_index]
                )

                if not candidate_text:
                    continue

                value = extract_price_from_text(
                    candidate_text
                )

                if value is not None:
                    mrp_value = value
                    break

        if mrp_value is not None:
            return mrp_value, tax_wording

    # --------------------------------------------------------
    # PRIORITY 3:
    # Price line containing ₹ / Rs plus tax wording.
    # --------------------------------------------------------

    for item in items:

        text = evidence_text(item)

        if not text:
            continue

        if tax_pattern.search(text):

            tax_wording = text

            value = extract_price_from_text(
                text
            )

            if value is not None:
                return value, tax_wording

    return None, tax_wording


# ============================================================
# NET QUANTITY
# ============================================================

QUANTITY_VALUE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*"
    r"(kg|kgs?|g|gm|gms?|gram|grams|"
    r"ml|mL|millilitre|millilitres|"
    r"milliliter|milliliters|"
    r"l|L|ltr|litre|litres|liter|liters|"
    r"m|cm|mm|N|U)\b",
    flags=re.IGNORECASE,
)


NET_QUANTITY_KEYWORDS = [
    "net weight",
    "net wt",
    "net quantity",
    "net qty",
]


def extract_quantity_match(
    text: str,
):

    match = QUANTITY_VALUE_PATTERN.search(
        text
    )

    if not match:
        return None

    number_text = match.group(1)
    raw_unit = match.group(2)

    try:
        number = float(number_text)
    except ValueError:
        return None

    unit = normalize_quantity_unit(
        raw_unit
    )

    exact_format = bool(
        re.search(
            rf"\b{re.escape(number_text)} "
            rf"{re.escape(raw_unit)}\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    return (
        number_text,
        number,
        unit,
        exact_format,
    )


def extract_quantity(
    evidence: Iterable[ClassifiedEvidence],
):

    items = list(evidence)

    # --------------------------------------------------------
    # PRIORITY 1:
    # Evidence classified as NET_QUANTITY.
    # --------------------------------------------------------

    for item in items:

        if label_of(item) != "NET_QUANTITY":
            continue

        text = evidence_text(item)

        if not text:
            continue

        result = extract_quantity_match(
            text
        )

        if result:

            (
                number_text,
                number,
                unit,
                exact_format,
            ) = result

            return (
                text,
                number,
                unit,
                exact_format,
                True,
            )

    # --------------------------------------------------------
    # PRIORITY 2:
    # Explicit "Net Weight / Net Quantity" declaration.
    #
    # This is the key fix for your "Per 100g" problem.
    # --------------------------------------------------------

    for index, item in enumerate(items):

        text = evidence_text(item)

        if not text:
            continue

        lower = text.lower()

        if not any(
            keyword in lower
            for keyword in NET_QUANTITY_KEYWORDS
        ):
            continue

        # Quantity on same line.
        result = extract_quantity_match(
            text
        )

        if result:

            (
                number_text,
                number,
                unit,
                exact_format,
            ) = result

            return (
                text,
                number,
                unit,
                exact_format,
                True,
            )

        # Quantity on the next few lines.
        for offset in range(1, 4):

            candidate_index = index + offset

            if candidate_index >= len(items):
                break

            candidate_text = evidence_text(
                items[candidate_index]
            )

            if not candidate_text:
                continue

            result = extract_quantity_match(
                candidate_text
            )

            if result:

                (
                    number_text,
                    number,
                    unit,
                    exact_format,
                ) = result

                declaration = (
                    f"{text} {candidate_text}"
                )

                return (
                    declaration,
                    number,
                    unit,
                    exact_format,
                    True,
                )

    # --------------------------------------------------------
    # PRIORITY 3:
    # Any quantity that is NOT obviously nutritional
    # "Per 100g" information.
    # --------------------------------------------------------

    for item in items:

        text = evidence_text(item)

        if not text:
            continue

        lower = text.lower()

        # Skip nutritional reference quantities.
        if (
            "per 100g" in lower
            or "per 100 g" in lower
            or "per 100ml" in lower
            or "per 100 ml" in lower
        ):
            continue

        result = extract_quantity_match(
            text
        )

        if result:

            (
                number_text,
                number,
                unit,
                exact_format,
            ) = result

            return (
                text,
                number,
                unit,
                exact_format,
                True,
            )

    return (
        None,
        None,
        None,
        None,
        None,
    )


# ============================================================
# FSSAI
# ============================================================

FSSAI_PATTERN = re.compile(
    r"(?<!\d)(\d{14})(?!\d)"
)


def extract_fssai(
    evidence: Iterable[ClassifiedEvidence],
) -> list[str]:

    licenses: list[str] = []
    seen: set[str] = set()

    for item in evidence:

        text = evidence_text(item)

        if not text:
            continue

        for match in FSSAI_PATTERN.findall(
            text
        ):

            if match not in seen:
                seen.add(match)
                licenses.append(match)

        # Also capture 14 digits with occasional space or hyphen separators
        for match in re.findall(r"\b(?:\d[\s-]?){14}\b", text):
            cleaned = re.sub(r"\D", "", match)
            if len(cleaned) == 14 and cleaned not in seen:
                seen.add(cleaned)
                licenses.append(cleaned)

    return licenses


# ============================================================
# BATCH
# ============================================================

BATCH_KEYWORD_PATTERN = re.compile(
    r"\b(?:batch|lot)\s*"
    r"(?:no\.?|number)?\b",
    flags=re.IGNORECASE,
)


def looks_like_batch_value(
    text: str,
) -> bool:

    if not text:
        return False

    text = text.strip()

    if is_label_only_text(text):
        return False

    # FSSAI licence number should never become batch.
    if re.fullmatch(
        r"\d{10,14}",
        text.replace(" ", ""),
    ):
        return False

    # Dates should not become batch numbers.
    if is_date_text(text):
        return False

    # Batch may be alphanumeric.
    if re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9\-\/_ ]{1,40}",
        text,
    ):
        return True

    return False


def clean_batch_text(
    text: str,
) -> str:

    cleaned = re.sub(
        r"^\s*(?:batch|lot)\s*"
        r"(?:no\.?|number)?\s*:?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return cleaned.strip()


def extract_batch(
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:

    items = list(evidence)

    # --------------------------------------------------------
    # PRIORITY 1:
    # Correct BATCH label.
    # --------------------------------------------------------

    for index, item in enumerate(items):

        if label_of(item) != "BATCH":
            continue

        text = evidence_text(item)

        if not text:
            continue

        cleaned = clean_batch_text(
            text
        )

        if looks_like_batch_value(
            cleaned
        ):
            return cleaned

        # Value may be on following line.
        for offset in range(1, 3):

            candidate_index = index + offset

            if candidate_index >= len(items):
                break

            candidate_text = evidence_text(
                items[candidate_index]
            )

            if looks_like_batch_value(
                candidate_text
            ):
                return candidate_text.strip()

    # --------------------------------------------------------
    # PRIORITY 2:
    # Explicit Batch / Lot keyword.
    # --------------------------------------------------------

    for index, item in enumerate(items):

        text = evidence_text(item)

        if not text:
            continue

        if not BATCH_KEYWORD_PATTERN.search(
            text
        ):
            continue

        cleaned = clean_batch_text(
            text
        )

        if looks_like_batch_value(
            cleaned
        ):
            return cleaned

        for offset in range(1, 3):

            candidate_index = index + offset

            if candidate_index >= len(items):
                break

            candidate_text = evidence_text(
                items[candidate_index]
            )

            if looks_like_batch_value(
                candidate_text
            ):
                return candidate_text.strip()

    return None


# ============================================================
# MANUFACTURER / MARKETER
# ============================================================

def extract_label_value(
    evidence: Iterable[ClassifiedEvidence],
    patterns: list[str],
) -> tuple[Optional[str], Optional[int]]:

    for item in evidence:

        text = evidence_text(item)

        if not text:
            continue

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:

                value = clean_text(
                    match.group(1)
                )

                if (
                    value
                    and not is_label_only_text(
                        value
                    )
                ):
                    return (
                        value,
                        group_of(item),
                    )

    return None, None


def extract_addresses_by_group(
    evidence: Iterable[ClassifiedEvidence],
) -> dict[Optional[int], list[str]]:

    grouped = {}

    for item in evidence:

        if label_of(item) != "ADDRESS":
            continue

        text = evidence_text(item)

        if not text:
            continue

        group_id = group_of(item)

        grouped.setdefault(
            group_id,
            [],
        ).append(text)

    return grouped


def joined_address_for_group(
    addresses_by_group: dict,
    group_id: Optional[int],
) -> Optional[str]:

    values = addresses_by_group.get(
        group_id,
        [],
    )

    if not values:
        return None

    return " ".join(values)


ADDRESS_INDICATOR_PATTERN = re.compile(
    r"(?:"
    r"\b\d{6}\b"
    r"|\b(?:road|street|lane|gali|bazar|bazaar|market|mkt|nagar|colony|sector|plot|phase|block|industrial|estate|park|complex|building|bldg|tower|floor|p\.?o\.?|post\s*office|distt?\.?|district|tehsil|taluk|village|vill)\b"
    r"|\b(?:india|haryana|punjab|delhi|gujarat|maharashtra|rajasthan|uttar\s*pradesh|madhya\s*pradesh|karnataka|tamil\s*nadu|kerala|andhra|telangana|west\s*bengal|bihar|odisha|assam)\b"
    r"|\b(?:jind|surat|ahmedabad|mumbai|chennai|kolkata|bangalore|bengaluru|hyderabad|pune|gurgaon|gurugram|faridabad|noida|rohtak|hisar|karnal|panipat|ambala)\b"
    r"|\((?:hry|pb|dl|up|mp|guj|mh|rj|ka|tn|wb|ch)\.?\)"
    r"|\b(?:hry|pb)\b"
    r")",
    flags=re.IGNORECASE,
)


def extract_manufacturer_and_address(
    evidence: list[ClassifiedEvidence],
) -> tuple[
    Optional[str],
    Optional[str],
]:

    # Manufacturer patterns should not match marketer declarations
    filtered_evidence = [
        ev for ev in evidence if "marketed" not in evidence_text(ev).lower()
    ]

    name, group_id = extract_label_value(
        filtered_evidence,
        [
            r"manufactured\s*(?:&|and)\s*marketed\s+by\s*:?\s*(.+)",
            r"manufactured\s*(?:&|and)\s*packed\s+by\s*:?\s*(.+)",
            r"manufactured\s+by\s*:?\s*(.+)",
            r"mfg\.?\s+by\s*:?\s*(.+)",
            r"mfd\.?\s+by\s*:?\s*(.+)",
            r"packed\s+by\s*:?\s*(.+)",
        ],
    )

    addresses = extract_addresses_by_group(
        evidence
    )

    address = joined_address_for_group(
        addresses,
        group_id,
    )

    # --------------------------------------------------------
    # If name is on the line after "Manufactured By".
    # --------------------------------------------------------

    if not name:

        for index, item in enumerate(
            evidence
        ):

            text = evidence_text(item)

            if not text:
                continue

            lower = text.lower()

            # Disqualify "marketed & packed by" from being treated as manufacturer
            if "marketed" in lower:
                continue

            if not any(
                phrase in lower
                for phrase in [
                    "manufactured by",
                    "manufactured & packed by",
                    "manufactured and packed by",
                    "mfg by",
                    "mfg. by",
                    "mfd by",
                    "packed by",
                ]
            ):
                continue

            if index + 1 < len(evidence):

                candidate = evidence_text(
                    evidence[index + 1]
                )

                if (
                    candidate
                    and not is_label_only_text(
                        candidate
                    )
                    and not is_date_text(
                        candidate
                    )
                    and not ADDRESS_INDICATOR_PATTERN.search(
                        candidate
                    )
                    and not re.search(r"\b(?:mrp|rs\.?|batch|lot|net\s*wt|net\s*qty|exp)\b", candidate, flags=re.IGNORECASE)
                    and "₹" not in candidate
                ):
                    name = candidate
                    group_id = group_of(
                        evidence[index]
                    ) or 10
                    break

    # --------------------------------------------------------
    # Find nearby address.
    # --------------------------------------------------------

    if name and not address:

        manufacturer_positions = [
            index
            for index, item
            in enumerate(evidence)
            if ("marketed" not in evidence_text(item).lower())
            and any(
                phrase
                in evidence_text(item).lower()
                for phrase in [
                    "manufactured by",
                    "manufactured & packed by",
                    "manufactured and packed by",
                    "mfg by",
                    "mfg. by",
                    "mfd by",
                    "packed by",
                ]
            )
        ]

        if manufacturer_positions:

            position = manufacturer_positions[0]

            address_parts = []

            for offset in range(
                1,
                min(8, len(evidence)),
            ):

                candidate_index = (
                    position + offset
                )

                if (
                    candidate_index
                    >= len(evidence)
                ):
                    break

                candidate = evidence[
                    candidate_index
                ]

                candidate_text = evidence_text(
                    candidate
                )

                if not candidate_text:
                    continue

                candidate_lower = (
                    candidate_text.lower()
                )

                # Stop at another major declaration.
                if any(
                    marker in candidate_lower
                    for marker in [
                        "marketed by",
                        "batch",
                        "mrp",
                        "net weight",
                        "net quantity",
                        "customer care",
                    ]
                ):
                    break

                if (
                    label_of(candidate) == "ADDRESS"
                    or ADDRESS_INDICATOR_PATTERN.search(
                        candidate_text
                    )
                ):
                    address_parts.append(
                        candidate_text
                    )

            if address_parts:
                address = " ".join(
                    address_parts
                )

    return name, address


def extract_marketer_and_address(
    evidence: list[ClassifiedEvidence],
) -> tuple[
    Optional[str],
    Optional[str],
]:

    name, group_id = extract_label_value(
        evidence,
        [
            r"marketed\s*(?:&|and)\s*packed\s+by\s*:?\s*(.+)",
            r"marketed\s*(?:&|and)\s*distributed\s+by\s*:?\s*(.+)",
            r"marketed\s+by\s*:?\s*(.+)",
            r"mkt\.?\s+by\s*:?\s*(.+)",
            r"distributed\s+by\s*:?\s*(.+)",
        ],
    )

    addresses = extract_addresses_by_group(
        evidence
    )

    address = joined_address_for_group(
        addresses,
        group_id,
    )

    # --------------------------------------------------------
    # If name is on the line after "Marketed By" / "Marketed & Packed By".
    # --------------------------------------------------------

    if not name:

        for index, item in enumerate(
            evidence
        ):

            text = evidence_text(item)

            if not text:
                continue

            lower = text.lower()

            if not any(
                phrase in lower
                for phrase in [
                    "marketed & packed by",
                    "marketed and packed by",
                    "marketed by",
                    "mkt by",
                    "mkt. by",
                    "distributed by",
                ]
            ):
                continue

            if index + 1 < len(evidence):

                candidate = evidence_text(
                    evidence[index + 1]
                )

                if (
                    candidate
                    and not is_label_only_text(
                        candidate
                    )
                    and not is_date_text(
                        candidate
                    )
                    and not ADDRESS_INDICATOR_PATTERN.search(
                        candidate
                    )
                    and not re.search(r"\b(?:mrp|rs\.?|batch|lot|net\s*wt|net\s*qty|exp)\b", candidate, flags=re.IGNORECASE)
                    and "₹" not in candidate
                ):
                    name = candidate
                    group_id = (
                        group_of(evidence[index])
                        or group_of(evidence[index + 1])
                        or 20
                    )
                    break

    # --------------------------------------------------------
    # Find nearby address following Marketer / Packer declaration.
    # --------------------------------------------------------

    if name and not address:

        marketer_positions = [
            index
            for index, item
            in enumerate(evidence)
            if any(
                phrase
                in evidence_text(item).lower()
                for phrase in [
                    "marketed & packed by",
                    "marketed and packed by",
                    "marketed by",
                    "mkt by",
                    "mkt. by",
                    "distributed by",
                ]
            ) or (
                evidence_text(item).strip() == name.strip()
            )
        ]

        if marketer_positions:

            position = marketer_positions[0]

            address_parts = []

            for offset in range(
                1,
                min(8, len(evidence)),
            ):

                candidate_index = (
                    position + offset
                )

                if (
                    candidate_index
                    >= len(evidence)
                ):
                    break

                candidate = evidence[
                    candidate_index
                ]

                candidate_text = evidence_text(
                    candidate
                )

                if not candidate_text or candidate_text.strip() == name.strip():
                    continue

                candidate_lower = (
                    candidate_text.lower()
                )

                # Stop at another major declaration.
                if any(
                    marker in candidate_lower
                    for marker in [
                        "manufactured by",
                        "batch",
                        "mrp",
                        "net weight",
                        "net quantity",
                        "customer care",
                        "fssai",
                    ]
                ):
                    break

                if (
                    label_of(candidate) == "ADDRESS"
                    or ADDRESS_INDICATOR_PATTERN.search(
                        candidate_text
                    )
                ):
                    address_parts.append(
                        candidate_text
                    )

            if address_parts:
                address = " ".join(
                    address_parts
                )

    return name, address


# ============================================================
# PRODUCT NAME
# ============================================================

PRODUCT_NAME_BAD_KEYWORDS = [
    "iso",
    "certified",
    "erfied",
    "certificate",
    "nutrition",
    "nutritional",
    "customer care",
    "consumer care",
    "fssai",
    "batch",
    "mrp",
    "net weight",
    "net quantity",
    "manufactured by",
    "marketed by",
    "company",
]


def looks_like_product_name(
    text: str,
) -> bool:

    if not text:
        return False

    lower = text.lower()

    if is_label_only_text(text):
        return False

    if any(
        keyword in lower
        for keyword
        in PRODUCT_NAME_BAD_KEYWORDS
    ):
        return False

    if re.search(
        r"\b\d{10,14}\b",
        text,
    ):
        return False

    if len(text.strip()) < 3:
        return False

    return True


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def corroborate_product_name_against_ocr(
    candidate: Optional[str],
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:
    """
    Ensure that a less-supported spelling variation does not override
    stronger corroborated package evidence.
    """
    if not candidate or len(candidate.strip()) < 3:
        return candidate

    cand_tokens = [t for t in re.findall(r"\b[A-Za-z0-9]+\b", candidate) if len(t) >= 2]
    if not cand_tokens:
        return candidate

    statutory_stops = {
        "mrp", "mfg", "exp", "batch", "lot", "fssai", "customer care", "consumer care",
        "marketed by", "manufactured by", "net wt", "net weight", "net qty", "net quantity",
        "ingredients", "nutrition", "protein", "carbohydrate", "fat", "energy"
    }

    ocr_snippets = []
    ocr_words_map = {}

    for item in evidence:
        txt = clean_text(getattr(item, "raw_text", str(item)))
        if not txt:
            continue
        lower_txt = txt.lower()
        if any(s in lower_txt for s in statutory_stops):
            continue
        ocr_snippets.append(txt)
        for w in re.findall(r"\b[A-Za-z0-9]+\b", txt):
            if len(w) >= 2 and w.lower() not in ocr_words_map:
                ocr_words_map[w.lower()] = w

    # 1. Exact phrase match in an OCR snippet
    for snip in ocr_snippets:
        if snip.strip().lower() == candidate.strip().lower():
            return snip.strip()

    # 2. Check if an OCR snippet contains a near-identical sequence of tokens
    for snip in ocr_snippets:
        snip_tokens = [t for t in re.findall(r"\b[A-Za-z0-9]+\b", snip) if len(t) >= 2]
        if len(snip_tokens) == len(cand_tokens):
            match_count = 0
            for c_t, s_t in zip(cand_tokens, snip_tokens):
                c_low = c_t.lower()
                s_low = s_t.lower()
                if c_low == s_low:
                    match_count += 1
                elif (
                    (c_low.startswith(s_low) or s_low.startswith(c_low))
                    and min(len(c_low), len(s_low)) >= 4
                    and abs(len(c_low) - len(s_low)) <= 2
                ) or (
                    min(len(c_low), len(s_low)) >= 4
                    and _levenshtein_distance(c_low, s_low) <= 1
                ):
                    match_count += 1
            if match_count == len(cand_tokens):
                return snip.strip()

    # 3. Token-by-token corroboration against package OCR words
    reconciled_tokens = []
    replaced_any = False

    for c_t in cand_tokens:
        c_low = c_t.lower()
        if c_low in ocr_words_map:
            reconciled_tokens.append(c_t)
            continue

        best_match = None
        for ocr_low, ocr_orig in ocr_words_map.items():
            if min(len(c_low), len(ocr_low)) < 4:
                continue
            if (c_low.startswith(ocr_low) or ocr_low.startswith(c_low)) and abs(len(c_low) - len(ocr_low)) <= 2:
                best_match = ocr_orig
                break
            if _levenshtein_distance(c_low, ocr_low) <= 1:
                best_match = ocr_orig
                break

        if best_match:
            if c_t.isupper():
                reconciled_tokens.append(best_match.upper())
            elif c_t.istitle():
                reconciled_tokens.append(best_match.capitalize())
            else:
                reconciled_tokens.append(best_match)
            replaced_any = True
        else:
            reconciled_tokens.append(c_t)

    if replaced_any:
        return " ".join(reconciled_tokens)

    return candidate


def extract_product_name(
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:

    items = list(evidence)

    # --------------------------------------------------------
    # Priority 1:
    # High-confidence reconciled PRODUCT_NAME / GENERIC_NAME
    # --------------------------------------------------------

    for label in [
        "PRODUCT_NAME",
        "GENERIC_NAME",
    ]:

        for item in sorted(
            items,
            key=lambda x: getattr(x, "confidence", 0.0) or 0.0,
            reverse=True,
        ):

            if label_of(item) != label:
                continue

            text = evidence_text(item)

            if looks_like_product_name(
                text
            ):
                corroborated = corroborate_product_name_against_ocr(text, items)
                return corroborated or text

    # --------------------------------------------------------
    # Priority 2:
    # Look near beginning of OCR for a plausible
    # product-name line.
    # --------------------------------------------------------

    for item in items[:15]:

        text = evidence_text(item)

        if not looks_like_product_name(
            text
        ):
            continue

        # Avoid pure random OCR fragments.
        if (
            len(text.split()) >= 1
            and len(text) >= 4
        ):
            corroborated = corroborate_product_name_against_ocr(text, items)
            return corroborated or text

    return None


# ============================================================
# CONSUMER CARE
# ============================================================

def extract_consumer_care(
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:

    candidates = find_by_label(
        evidence,
        "CONSUMER_CARE",
    )

    if candidates:
        return " ".join(candidates)

    useful = []

    for item in evidence:

        text = evidence_text(item)

        if not text:
            continue

        lower = text.lower()

        if any(
            term in lower
            for term in [
                "customer care",
                "consumer care",
                "feedback",
                "complaints",
                "helpline",
                "support",
                "contact",
            ]
        ):
            useful.append(text)

    if useful:
        return " ".join(useful)

    return None


# ============================================================
# COUNTRY OF ORIGIN
# ============================================================

def extract_origin(
    evidence: Iterable[ClassifiedEvidence],
) -> Optional[str]:

    candidates = find_by_label(
        evidence,
        "COUNTRY_OF_ORIGIN",
    )

    if candidates:
        return candidates[0]

    for item in evidence:

        text = evidence_text(item)

        if re.search(
            r"\b(?:product\s+of|country\s+of\s+origin|made\s+in)"
            r"\s+[A-Za-z ]+",
            text,
            flags=re.IGNORECASE,
        ):
            return text

    return None


# ============================================================
# UNIT SALE PRICE (USP)
# ============================================================

USP_REGEX_PATTERNS = [
    # 1) Explicit USP keyword: e.g. "USP: ₹ 0.15 / g", "Unit Sale Price: 0.15 Per gram"
    re.compile(
        r"(?:unit\s*sale\s*price|usp)\s*:?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"\(?\s*(?:₹|rs\.?|inr)?\s*"
        r"(\d+(?:\.\d+)?)\s*"
        r"(?:/|\bper\b)\s*"
        r"(?:(\d+)\s*)?"
        r"(kg|kilograms?|gms?|grams?|g|litres?|liters?|ltr|l|ml|cm|mm|metres?|meters?|m|pieces?|units?|n|u)\b"
        r"\)?",
        flags=re.IGNORECASE,
    ),
    # 2) Generic price-per-unit or bracketed rate:
    # "(0.15 Per gram)", "0.15 Per gram", "₹ 0.15 / g", "Rs. 15.80 / 100 g", "₹0.447/g"
    re.compile(
        r"(?:(?:₹|rs\.?|inr)\s*)?"
        r"\(?\s*(?:(?:₹|rs\.?|inr)\s*)?"
        r"(\d+(?:\.\d+)?)\s*"
        r"(?:/|\bper\b)\s*"
        r"(?:(\d+)\s*)?"
        r"(kg|kilograms?|gms?|grams?|g|litres?|liters?|ltr|l|ml|cm|mm|metres?|meters?|m|pieces?|units?|n|u)\b"
        r"\)?",
        flags=re.IGNORECASE,
    ),
]


def normalize_usp_unit(unit_str: str) -> str:
    u = unit_str.lower().strip()
    if u in {"g", "gm", "gms", "gram", "grams"}:
        return "g"
    if u in {"kg", "kilogram", "kilograms"}:
        return "kg"
    if u in {"ml"}:
        return "ml"
    if u in {"l", "ltr", "litre", "litres", "liter", "liters"}:
        return "l"
    if u in {"m", "metre", "meter", "metres", "meters"}:
        return "m"
    if u in {"cm"}:
        return "cm"
    if u in {"piece", "pieces", "unit", "units", "u", "n"}:
        return "piece"
    return u


def extract_usp(
    evidence: Iterable[ClassifiedEvidence],
) -> tuple[Optional[str], Optional[float], Optional[str]]:

    for item in evidence:

        text = evidence_text(item)

        if not text:
            continue

        lower = text.lower()

        # Skip nutritional table entries (e.g. "protein 8g per 100g")
        if any(
            k in lower
            for k in [
                "protein",
                "energy",
                "carbohydrate",
                "fat",
                "cholesterol",
                "sodium",
                "nutrition",
                "nutritional",
            ]
        ):
            continue

        for pat in USP_REGEX_PATTERNS:
            match = pat.search(text)
            if not match:
                continue

            try:
                val = float(match.group(1))
            except (ValueError, TypeError):
                continue

            count_str = match.group(2)
            count_int = int(count_str) if count_str and count_str.isdigit() else 1
            unit_norm = normalize_usp_unit(match.group(3))

            count_label = f"{count_int} " if count_int > 1 else ""
            display_str = f"₹ {val:g} / {count_label}{unit_norm}".strip()
            unit_base_str = f"per {count_int} {unit_norm}" if count_int > 1 else f"per 1 {unit_norm}"

            return (
                display_str,
                val,
                unit_base_str,
            )

    return None, None, None


# ============================================================
# DATE FUTURE CHECK
# ============================================================

def parse_date_for_future_check(
    value: Optional[str],
):

    if not value:
        return None

    text = value.strip()

    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%b/%Y",
        "%b-%Y",
        "%b %Y",
        "%B %Y",
    ]

    for fmt in formats:

        try:
            return datetime.strptime(
                text,
                fmt,
            )
        except ValueError:
            continue

    return None


# ============================================================
# EVIDENCE CONVERSION
# ============================================================

def build_evidence(
    classified: list[ClassifiedEvidence],
) -> list[OCREvidence]:

    return [
        OCREvidence(
            text=item.raw_text,
            confidence=item.confidence,
            source_image=item.source_image,
            capture_type=item.capture_type,
            bbox=item.bbox,
        )
        for item in classified
    ]


# ============================================================
# PRODUCT EXTRACTION
# ============================================================

def extract_product_data(
    classified: list[ClassifiedEvidence],
) -> ProductData:

    product = ProductData()

    product.evidence = build_evidence(
        classified
    )

    # --------------------------------------------------------
    # PRODUCT NAME
    # --------------------------------------------------------

    product.product_name = extract_product_name(
        classified
    )

    # --------------------------------------------------------
    # MRP
    # --------------------------------------------------------

    (
        product.mrp,
        product.mrp_tax_inclusive_wording,
    ) = extract_mrp(
        classified
    )

    # --------------------------------------------------------
    # NET QUANTITY
    # --------------------------------------------------------

    (
        product.net_quantity,
        product.net_quantity_value,
        product.net_quantity_unit,
        product.quantity_format_valid,
        product.quantity_unit_valid,
    ) = extract_quantity(
        classified
    )

    # --------------------------------------------------------
    # DATES
    # --------------------------------------------------------

    product.manufacturing_date = extract_date(
        classified,
        "MANUFACTURING_DATE",
    )

    product.expiry_date = extract_date(
        classified,
        "EXPIRY_DATE",
    )

    product.best_before = extract_best_before(
        classified
    )

    product.derived_shelf_life = calculate_derived_shelf_life(
        product.manufacturing_date,
        product.expiry_date,
    )

    # --------------------------------------------------------
    # MANUFACTURING DATE FUTURE CHECK
    # --------------------------------------------------------

    parsed_manufacturing_date = (
        parse_date_for_future_check(
            product.manufacturing_date
        )
    )

    if parsed_manufacturing_date is not None:

        product.manufacturing_date_is_future = (
            parsed_manufacturing_date.date()
            > datetime.now().date()
        )

    # --------------------------------------------------------
    # UNIT SALE PRICE
    # --------------------------------------------------------

    (
        product.unit_sale_price,
        product.unit_sale_price_value,
        product.unit_sale_price_unit,
    ) = extract_usp(
        classified
    )

    # --------------------------------------------------------
    # MANUFACTURER
    # --------------------------------------------------------

    (
        product.manufacturer_name,
        product.manufacturer_address,
    ) = extract_manufacturer_and_address(
        classified
    )

    # --------------------------------------------------------
    # MARKETER
    # --------------------------------------------------------

    (
        product.marketer_name,
        product.marketer_address,
    ) = extract_marketer_and_address(
        classified
    )

    # --------------------------------------------------------
    # BATCH
    # --------------------------------------------------------

    product.batch_number = extract_batch(
        classified
    )

    # --------------------------------------------------------
    # FSSAI
    # --------------------------------------------------------

    product.fssai_licenses = extract_fssai(
        classified
    )

    # --------------------------------------------------------
    # CONSUMER CARE
    # --------------------------------------------------------

    product.consumer_care = (
        extract_consumer_care(
            classified
        )
    )

    # --------------------------------------------------------
    # COUNTRY OF ORIGIN
    # --------------------------------------------------------

    product.country_of_origin = extract_origin(
        classified
    )

    return product


# ============================================================
# BACKWARD-COMPATIBLE CLASS
# ============================================================

class ProductExtractor:

    def extract(
        self,
        classified_evidence,
    ) -> ProductData:

        return extract_product_data(
            classified_evidence
        )