"""Groq Vision service for direct packaging visual inspection.

Extracts visible statutory declarations directly from packaged commodity images
using Groq's high-speed multimodal vision models.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from extraction.evidence import ClassifiedEvidence

DEFAULT_GROQ_VISION_MODEL = "qwen/qwen3.8-27b"


def _load_env_if_present():
    """Load key-value pairs from .env file or Windows registry into os.environ if not already set."""
    env_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break

    if "GROQ_API_KEY" not in os.environ:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg_key:
                val, _ = winreg.QueryValueEx(reg_key, "GROQ_API_KEY")
                if val:
                    os.environ["GROQ_API_KEY"] = val
        except Exception:
            pass

_load_env_if_present()


class GroqVisionService:
    """
    Multimodal packaging inspector powered by Groq Vision.

    Directly inspects the packaging image artwork to visually detect and
    extract statutory declarations with strict anti-hallucination constraints.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        _load_env_if_present()
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_VISION_MODEL", DEFAULT_GROQ_VISION_MODEL)
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("GROQ_API_KEY environment variable is not configured.")
            from groq import Groq
            self._client = Groq(api_key=self.api_key)
        return self._client

    @staticmethod
    def encode_image(image_path: str) -> Tuple[str, str]:
        """Read image and return (mime_type, base64_string)."""
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")

        return mime_type, encoded

    def extract(
        self,
        image_path: str,
    ) -> List[ClassifiedEvidence]:
        """
        Inspect the packaging image and return detected declarations as ClassifiedEvidence.

        If Groq is unconfigured or unavailable, returns an empty list without raising,
        allowing the pipeline to rely gracefully on PaddleOCR and local heuristics.
        """
        if not self.api_key:
            print("[Groq Vision] GROQ_API_KEY not configured. Skipping visual AI inspection.")
            return []

        try:
            print(f"[Groq Vision] Inspecting image with model '{self.model}'...")
            mime_type, base64_image = self.encode_image(image_path)

            client = self._get_client()

            prompt = """You are an expert Indian Legal Metrology and statutory packaging compliance auditor.
Carefully examine the visible declarations printed on this product packaging.

STRICT ANTI-HALLUCINATION RULES:
1. Extract ONLY declarations that are CLEARLY and VISIBLY printed on the package.
2. If any declaration is NOT visible, absent, or obscured, set its value to null. DO NOT guess, extrapolate, or invent missing statutory details.
3. Distinguish between Manufacturer and Marketer.
4. For MRP, extract the printed price number and indicate whether tax-inclusive wording ('incl. of all taxes') is present.
5. For Net Quantity, extract the complete declared weight/volume with units (e.g. '340 g', '1 L').
6. For Dates, extract exactly as printed (e.g., '01/01/2025' or 'AUG 2025').

Return a single JSON object with EXACTLY this structure:
{
  "product_name": "string or null",
  "mrp": "string or null",
  "mrp_tax_wording": "string or null",
  "net_quantity": "string or null",
  "manufacturing_date": "string or null",
  "expiry_date": "string or null",
  "best_before": "string or null",
  "batch_number": "string or null",
  "manufacturer_name": "string or null",
  "manufacturer_address": "string or null",
  "marketer_name": "string or null",
  "marketer_address": "string or null",
  "fssai_licenses": ["14-digit strings"],
  "consumer_care": "string or null",
  "country_of_origin": "string or null"
}
"""

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_image}"
                                },
                            },
                        ],
                    }
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            parsed = self.parse_response(content)
            evidence = self.to_classified_evidence(parsed, image_path)

            print(f"[Groq Vision] Successfully extracted {len(evidence)} visual declaration evidence items.")
            return evidence

        except Exception as exc:
            print(f"[Groq Vision] Visual inspection failed or unavailable ({exc}). Proceeding with OCR.")
            return []

    @staticmethod
    def parse_response(response_text: str) -> Dict[str, Any]:
        """Parse JSON response from Groq, tolerating markdown code fences."""
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback regex extraction for json block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {}

    @classmethod
    def to_classified_evidence(
        cls,
        data: Dict[str, Any],
        image_path: Optional[str] = None,
    ) -> List[ClassifiedEvidence]:
        """Convert extracted visual dictionary into ClassifiedEvidence items."""
        evidence: List[ClassifiedEvidence] = []
        idx = 0

        def add_item(text: Any, label: str, group_id: Optional[int] = None):
            nonlocal idx
            if text is None:
                return
            s = str(text).strip()
            if not s or s.lower() == "null":
                return
            evidence.append(
                ClassifiedEvidence(
                    evidence_index=idx,
                    raw_text=s,
                    normalized_text=s,
                    label=label,
                    confidence=0.95,
                    source_image=image_path,
                    capture_type="groq_vision",
                    group_id=group_id,
                    visual_only=True,
                )
            )
            idx += 1

        add_item(data.get("product_name"), "PRODUCT_NAME")

        mrp = data.get("mrp")
        mrp_tax = data.get("mrp_tax_wording")
        if mrp:
            mrp_text = f"{mrp} {mrp_tax}".strip() if mrp_tax else str(mrp)
            add_item(mrp_text, "MRP")

        add_item(data.get("net_quantity"), "NET_QUANTITY")
        add_item(data.get("manufacturing_date"), "MANUFACTURING_DATE")
        add_item(data.get("expiry_date"), "EXPIRY_DATE")
        add_item(data.get("best_before"), "BEST_BEFORE")
        add_item(data.get("batch_number"), "BATCH")

        name = data.get("manufacturer_name")
        if name:
            s_name = str(name).strip()
            if not any(k in s_name.lower() for k in ["manufactured by", "mfg by", "mfd by"]):
                s_name = f"Manufactured By: {s_name}"
            add_item(s_name, "MANUFACTURER", group_id=10)
        add_item(data.get("manufacturer_address"), "ADDRESS", group_id=10)

        mkt = data.get("marketer_name")
        if mkt:
            s_mkt = str(mkt).strip()
            if not any(k in s_mkt.lower() for k in ["marketed by", "mkt by"]):
                s_mkt = f"Marketed By: {s_mkt}"
            add_item(s_mkt, "MARKETER", group_id=20)
        add_item(data.get("marketer_address"), "ADDRESS", group_id=20)

        bb = data.get("best_before")
        if bb:
            s_bb = str(bb).strip()
            if "best before" not in s_bb.lower():
                s_bb = f"Best Before {s_bb}"
            add_item(s_bb, "BEST_BEFORE")

        batch = data.get("batch_number")
        if batch:
            s_batch = str(batch).strip()
            if not any(k in s_batch.lower() for k in ["batch", "lot", "b.no"]):
                s_batch = f"Batch No: {s_batch}"
            add_item(s_batch, "BATCH")

        add_item(data.get("consumer_care"), "CONSUMER_CARE")
        add_item(data.get("country_of_origin"), "COUNTRY_OF_ORIGIN")

        lics = data.get("fssai_licenses", [])
        if isinstance(lics, str):
            lics = [l.strip() for l in lics.split(",") if l.strip()]
        for lic in lics or []:
            if lic:
                for m in re.findall(r"\b\d{14}\b", str(lic)):
                    add_item(f"fssai Lic. No. {m}", "OTHER_DECLARATION")

        return evidence


def _looks_like_date(text: str) -> bool:
    patterns = [
        r"\b\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}\b",
        r"\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*[/-]?\s*\d{2,4}\b",
        r"\b\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{2,4}\b",
    ]
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


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


def apply_local_heuristic_classification(items: List[ClassifiedEvidence]) -> None:
    """Apply deterministic regex classification to OCR evidence."""
    for idx, ev in enumerate(items):
        text = str(getattr(ev, "raw_text", "") or "").strip()
        if not text:
            continue
        lower = text.lower()
        existing = (getattr(ev, "label", None) or "OTHER_DECLARATION").upper()

        if any(k in lower for k in ["product of", "made in india", "country of origin", "proudly made in"]):
            ev.label = "COUNTRY_OF_ORIGIN"
            continue

        if any(k in lower for k in ["customer care", "consumer care", "consumer support", "feedback", "complaints", "helpline", "support desk", "phone:", "website:"]):
            ev.label = "CONSUMER_CARE"
            continue

        if "best before" in lower:
            ev.label = "BEST_BEFORE"
            continue

        if any(k in lower for k in ["manufactured & packed by", "manufactured and packed by", "manufactured by", "manufacturedby", "mfg by", "mfg. by", "mfd by"]):
            ev.label = "MANUFACTURER"
            ev.group_id = 10
            continue

        if any(k in lower for k in ["marketed & packed by", "marketed and packed by", "marketed by", "marketedby", "mkt by", "mkt. by", "packed by", "pkd by"]):
            ev.label = "MARKETER"
            ev.group_id = 20
            continue

        if any(k in lower for k in ["mfg", "mfd", "manufacturing", "packed on", "pkd"]):
            ev.label = "MANUFACTURING_DATE"
            continue

        if any(k in lower for k in ["exp", "expiry", "use by", "best by"]):
            ev.label = "EXPIRY_DATE"
            continue

        if _looks_like_date(text):
            if idx > 0:
                prev_label = (getattr(items[idx - 1], "label", "") or "").upper()
                if prev_label in {"MANUFACTURING_DATE", "EXPIRY_DATE"}:
                    ev.label = prev_label
                    continue
            if existing == "OTHER_DECLARATION":
                ev.label = "MANUFACTURING_DATE"
            continue

        if any(k in lower for k in ["batch", "batch no", "batch number", "lot no", "lot number", "b.no", "b. no"]):
            ev.label = "BATCH"
            continue

        if any(k in lower for k in ["mrp", "₹", "rs.", "rs ", "inr", "incl. of all taxes", "incl of all taxes"]):
            ev.label = "MRP"
            continue

        if any(k in lower for k in ["net wt", "net weight", "net quantity", "net qty"]):
            ev.label = "NET_QUANTITY"
            continue

        if ADDRESS_INDICATOR_PATTERN.search(text):
            if existing == "OTHER_DECLARATION":
                ev.label = "ADDRESS"
                if idx > 0 and items[idx - 1].group_id:
                    ev.group_id = items[idx - 1].group_id
                elif idx > 1 and items[idx - 2].group_id:
                    ev.group_id = items[idx - 2].group_id
            continue

        if idx < 8 and len(text) >= 4 and not re.search(r"\d", text) and not any(k in lower for k in ["fssai", "recycle", "nutrition", "energy", "protein", "fat", "ingredients", "marketed", "manufactured"]) and not ADDRESS_INDICATOR_PATTERN.search(text):
            if existing == "OTHER_DECLARATION":
                ev.label = "PRODUCT_NAME"


def classify_ocr_evidence(
    raw_items: list,
    image_path: Optional[str] = None,
) -> List[ClassifiedEvidence]:
    """Convert raw OCREvidence into ClassifiedEvidence with heuristic labels."""
    prepared: List[ClassifiedEvidence] = []
    for idx, item in enumerate(raw_items):
        text_val = str(getattr(item, "text", str(item)) or "").strip()
        src_img = getattr(item, "source_image", None) or image_path
        bbox_val = getattr(item, "bbox", None)
        conf_val = getattr(item, "confidence", 1.0)
        prepared.append(
            ClassifiedEvidence(
                evidence_index=idx,
                raw_text=text_val,
                normalized_text=text_val,
                label="OTHER_DECLARATION",
                confidence=conf_val,
                source_image=src_img,
                capture_type="paddleocr",
                bbox=bbox_val,
            )
        )

    header_patterns = [
        r"^(?:manufactured\s*(?:&|and)?\s*packed\s+by|manufactured\s+by|mfg\.?\s+by|mfd\s+by)\s*:?\s*$",
        r"^(?:marketed\s*(?:&|and)?\s*packed\s+by|marketed\s+by|mkt\.?\s+by|packed\s+by)\s*:?\s*$",
        r"^(?:mfg\.?\s*date|mfd\.?\s*date|manufacturing\s*date)\s*:?\s*$",
        r"^(?:exp\.?\s*date|expiry\s*date|use\s*by)\s*:?\s*$",
        r"^(?:batch\s*(?:no\.?|number)?|lot\s*(?:no\.?|number)?)\s*:?\s*$",
        r"^(?:mrp)\s*:?\s*$",
    ]

    for i in range(len(prepared) - 1):
        curr = prepared[i].raw_text.strip()
        nxt = prepared[i + 1].raw_text.strip()
        if not curr or not nxt:
            continue
        for pat in header_patterns:
            if re.match(pat, curr, flags=re.IGNORECASE):
                merged = f"{curr} {nxt}"
                prepared[i].raw_text = merged
                prepared[i].normalized_text = merged
                break

    apply_local_heuristic_classification(prepared)
    return prepared
