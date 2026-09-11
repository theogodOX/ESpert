"""Field-by-field Evidence Merger and Semantic Reconciliation Layer.

Reconciles raw PaddleOCR evidence and Groq Vision visual declarations
into a coherent, provenance-tagged set of ClassifiedEvidence objects
ready for consumption by the existing ProductExtractor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from extraction.evidence import ClassifiedEvidence
from extraction.extractor import (
    calculate_derived_shelf_life,
    clean_text,
    corroborate_product_name_against_ocr,
    extract_date_from_text,
    extract_price_from_text,
    extract_quantity_match,
)


@dataclass
class FieldReconciliation:
    """Record of reconciliation decision for a specific declaration field."""
    field_name: str
    status: str  # "AGREED", "RECOVERED_VISION", "OCR_ONLY", "CONFLICT_RESOLVED", "CONFLICT_UNRESOLVED", "MISSING"
    ocr_value: Optional[str] = None
    vision_value: Optional[str] = None
    final_value: Optional[str] = None
    confidence: float = 1.0
    notes: str = ""


@dataclass
class MergeResult:
    """Result of reconciling OCR and visual evidence."""
    evidence: List[ClassifiedEvidence] = field(default_factory=list)
    reconciliations: Dict[str, FieldReconciliation] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)


class SemanticNormalizer:
    """Provides semantic normalization for statutory declarations."""

    @staticmethod
    def normalize_price(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        return extract_price_from_text(text)

    @staticmethod
    def normalize_fssai(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        digits = re.sub(r"\D", "", str(text))
        # Valid FSSAI licence is strictly 14 digits
        if len(digits) == 14:
            return digits
        match = re.search(r"\b\d{14}\b", str(text))
        return match.group(0) if match else None

    @staticmethod
    def normalize_date(text: Optional[str]) -> Optional[Tuple[int, int, Optional[int]]]:
        """Parse date into (year, month, day or 0) tuple for semantic comparison."""
        if not text:
            return None
        raw = extract_date_from_text(text) or text.strip()
        formats = [
            ("%d/%m/%Y", True),
            ("%d-%m-%Y", True),
            ("%d.%m.%Y", True),
            ("%d/%m/%y", True),
            ("%d-%m-%y", True),
            ("%b/%Y", False),
            ("%b-%Y", False),
            ("%b %Y", False),
            ("%B %Y", False),
            ("%m/%Y", False),
            ("%m-%Y", False),
            ("%Y", False),
        ]
        for fmt, has_day in formats:
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                return (dt.year, dt.month, dt.day if has_day else 0)
            except ValueError:
                continue
        return None

    @staticmethod
    def normalize_quantity(text: Optional[str]) -> Optional[Tuple[float, str]]:
        """Parse quantity into (numeric_value, normalized_unit)."""
        if not text:
            return None
        match = extract_quantity_match(text)
        if match:
            _, num, unit, _ = match
            return (num, unit)
        return None

    @staticmethod
    def normalize_statutory_text(text: Optional[str]) -> str:
        """Strip boilerplate prefixes, punctuation, and multiple spaces."""
        if not text:
            return ""
        s = text.lower().strip()
        prefixes = [
            "manufactured by", "manufactured & packed by", "mfg by", "mfg. by", "mfd by",
            "marketed by", "marketed & packed by", "mkt by", "mkt. by",
            "product of", "country of origin:", "made in",
            "customer care:", "consumer care:", "feedback:", "helpline:",
            "batch no:", "batch:", "b.no:", "lot no:", "lot:",
        ]
        for p in prefixes:
            if s.startswith(p):
                s = s[len(p):].strip()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s


class EvidenceMerger:
    """
    Dedicated field-by-field evidence reconciliation layer.

    Merges raw PaddleOCR evidence and Groq Vision evidence, applying
    semantic normalization before declaring agreement or conflict.
    """

    def __init__(self):
        self.normalizer = SemanticNormalizer()

    def merge(
        self,
        ocr_evidence: List[ClassifiedEvidence],
        vision_evidence: List[ClassifiedEvidence],
        image_path: Optional[str] = None,
    ) -> MergeResult:
        """
        Reconcile OCR and Groq Vision evidence into a unified ClassifiedEvidence list.
        """
        result = MergeResult()
        merged_items: List[ClassifiedEvidence] = []
        rec_map: Dict[str, FieldReconciliation] = {}
        self._raw_ocr_corpus = " ".join(clean_text(ev.raw_text).lower() for ev in ocr_evidence if ev.raw_text)

        # 1. Index evidence by canonical declaration label
        ocr_by_label: Dict[str, List[ClassifiedEvidence]] = {}
        for ev in ocr_evidence:
            label = (ev.label or "OTHER_DECLARATION").upper()
            ocr_by_label.setdefault(label, []).append(ev)

        vision_by_label: Dict[str, List[ClassifiedEvidence]] = {}
        for ev in vision_evidence:
            label = (ev.label or "OTHER_DECLARATION").upper()
            vision_by_label.setdefault(label, []).append(ev)

        canonical_labels = [
            "PRODUCT_NAME",
            "MRP",
            "NET_QUANTITY",
            "MANUFACTURING_DATE",
            "EXPIRY_DATE",
            "BEST_BEFORE",
            "BATCH",
            "MANUFACTURER",
            "MARKETER",
            "ADDRESS",
            "CONSUMER_CARE",
            "COUNTRY_OF_ORIGIN",
        ]

        # 2. Field-by-field reconciliation
        for field_label in canonical_labels:
            ocr_items = ocr_by_label.get(field_label, [])
            vis_items = vision_by_label.get(field_label, [])

            rec, chosen_evidence = self._reconcile_field(
                field_label, ocr_items, vis_items, image_path
            )
            # Reconcile product name against physical package evidence
            if field_label == "PRODUCT_NAME" and rec.final_value:
                corroborated = corroborate_product_name_against_ocr(rec.final_value, ocr_evidence)
                if corroborated and corroborated != rec.final_value:
                    rec.final_value = corroborated
                    rec.notes += f" Corroborated with physical packaging OCR evidence: '{corroborated}'."
                    for itm in chosen_evidence:
                        if itm.label == "PRODUCT_NAME":
                            itm.raw_text = corroborated
                            itm.normalized_text = corroborated

            rec_map[field_label] = rec
            merged_items.extend(chosen_evidence)

        # Compute derived shelf life if manufacturing and expiry dates exist
        mfg_final = rec_map.get("MANUFACTURING_DATE", FieldReconciliation("MANUFACTURING_DATE", "MISSING")).final_value
        exp_final = rec_map.get("EXPIRY_DATE", FieldReconciliation("EXPIRY_DATE", "MISSING")).final_value
        shelf_life = calculate_derived_shelf_life(mfg_final, exp_final)
        if shelf_life:
            rec_map["DERIVED_SHELF_LIFE"] = FieldReconciliation(
                field_name="DERIVED_SHELF_LIFE",
                status="AGREED",
                final_value=shelf_life,
                confidence=0.99,
                notes="Generic date-interval derived from manufacturing and expiry dates.",
            )
            merged_items.append(
                ClassifiedEvidence(
                    evidence_index=len(merged_items),
                    raw_text=shelf_life,
                    normalized_text=shelf_life,
                    label="DERIVED_SHELF_LIFE",
                    confidence=0.99,
                    source_image=image_path,
                    capture_type="derived_calculation",
                    visual_only=False,
                )
            )

        # 3. Handle FSSAI licences specifically
        fssai_merged = self._reconcile_fssai(
            ocr_evidence, vision_evidence, image_path
        )
        merged_items.extend(fssai_merged)

        # 4. Include remaining unhandled evidence for full context
        seen_texts = {clean_text(ev.raw_text) for ev in merged_items if ev.raw_text}
        handled_labels = set(canonical_labels) | {"FSSAI_LICENSE", "FSSAI", "DERIVED_SHELF_LIFE"}
        reconciled_fssai = getattr(self, "_reconciled_fssai", set())
        for ev in ocr_evidence:
            txt = clean_text(ev.raw_text)
            if not txt or txt in seen_texts:
                continue
            # If this snippet is an FSSAI declaration whose 14-digit licence is already reconciled, skip duplicate
            ev_fssai = re.findall(r"\b\d{14}\b", txt)
            if ev_fssai and all(f in reconciled_fssai for f in ev_fssai) and any(k in txt.lower() for k in ["fssai", "lic"]):
                continue
            ev_label = ev.label or "OTHER_DECLARATION"
            # Prevent unhandled/duplicate OCR items from overriding reconciled fields
            if ev_label.upper() in handled_labels:
                ev_label = "OTHER_DECLARATION"
            ev_copy = ClassifiedEvidence(
                evidence_index=len(merged_items),
                raw_text=ev.raw_text,
                normalized_text=ev.normalized_text or ev.raw_text,
                label=ev_label,
                confidence=min(ev.confidence or 0.8, 0.7),
                source_image=ev.source_image or image_path,
                capture_type=ev.capture_type or "paddleocr",
                group_id=ev.group_id,
                visual_only=False,
                bbox=ev.bbox,
            )
            merged_items.append(ev_copy)
            seen_texts.add(txt)

        for idx, ev in enumerate(merged_items):
            ev.evidence_index = idx

        summary = {}
        for rec in rec_map.values():
            summary[rec.status] = summary.get(rec.status, 0) + 1

        result.evidence = merged_items
        result.reconciliations = rec_map
        result.summary = summary
        return result

    def _reconcile_field(
        self,
        field_label: str,
        ocr_items: List[ClassifiedEvidence],
        vis_items: List[ClassifiedEvidence],
        image_path: Optional[str],
    ) -> Tuple[FieldReconciliation, List[ClassifiedEvidence]]:
        """Reconcile a single field category semantically."""
        ocr_text = " ".join(clean_text(i.raw_text) or "" for i in ocr_items if clean_text(i.raw_text)).strip() or None
        vis_text = " ".join(clean_text(i.raw_text) or "" for i in vis_items if clean_text(i.raw_text)).strip() or None

        # Case 1: Neither detects
        if not ocr_text and not vis_text:
            return (
                FieldReconciliation(
                    field_name=field_label,
                    status="MISSING",
                    notes="Neither PaddleOCR nor Groq Vision detected this declaration."
                ),
                []
            )

        # Case 2: Vision only (Recovery)
        if not ocr_text and vis_text:
            items = []
            for item in vis_items:
                c = ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label=field_label,
                    confidence=max(item.confidence or 0.9, 0.9),
                    source_image=item.source_image or image_path,
                    capture_type="groq_vision",
                    group_id=item.group_id,
                    visual_only=True,
                    bbox=item.bbox,
                )
                items.append(c)
            return (
                FieldReconciliation(
                    field_name=field_label,
                    status="RECOVERED_VISION",
                    vision_value=vis_text,
                    final_value=vis_text,
                    confidence=0.92,
                    notes="Recovered declaration directly from Groq visual inspection."
                ),
                items
            )

        # Case 3: OCR only
        if ocr_text and not vis_text:
            items = []
            for item in ocr_items:
                c = ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label=field_label,
                    confidence=item.confidence or 0.85,
                    source_image=item.source_image or image_path,
                    capture_type="paddleocr",
                    group_id=item.group_id,
                    visual_only=False,
                    bbox=item.bbox,
                )
                items.append(c)
            return (
                FieldReconciliation(
                    field_name=field_label,
                    status="OCR_ONLY",
                    ocr_value=ocr_text,
                    final_value=ocr_text,
                    confidence=0.85,
                    notes="Detected exclusively via PaddleOCR multi-pass extraction."
                ),
                items
            )

        # Case 4: Both detected -> Perform semantic comparison
        is_agreement, resolved_text, conflict_reason = self._semantic_compare(
            field_label, ocr_text, vis_text
        )

        if is_agreement:
            base_items = vis_items if vis_items else ocr_items
            items = []
            for item in base_items:
                c = ClassifiedEvidence(
                    raw_text=resolved_text or item.raw_text,
                    normalized_text=resolved_text or item.normalized_text,
                    label=field_label,
                    confidence=0.98,
                    source_image=item.source_image or image_path,
                    capture_type="reconciled_agreement",
                    group_id=item.group_id,
                    visual_only=False,
                    bbox=item.bbox,
                )
                items.append(c)
            return (
                FieldReconciliation(
                    field_name=field_label,
                    status="AGREED",
                    ocr_value=ocr_text,
                    vision_value=vis_text,
                    final_value=resolved_text,
                    confidence=0.98,
                    notes="Semantic agreement verified between OCR and Groq Vision."
                ),
                items
            )

        # Disagreement: Attempt deterministic resolution
        resolved, tie_winner, resolution_note = self._attempt_deterministic_resolution(
            field_label, ocr_text, vis_text
        )

        if resolved and tie_winner:
            chosen_source = vis_items if tie_winner == "vision" else ocr_items
            rejected_source = ocr_items if tie_winner == "vision" else vis_items
            items = []
            for item in chosen_source:
                c = ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label=field_label,
                    confidence=0.95,
                    source_image=item.source_image or image_path,
                    capture_type="conflict_resolved",
                    group_id=item.group_id,
                    visual_only=(tie_winner == "vision"),
                    bbox=item.bbox,
                )
                items.append(c)
            # Demote rejected candidates so downstream extractor does not pick them up
            for item in rejected_source:
                c = ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label="OTHER_DECLARATION",
                    confidence=0.40,
                    source_image=item.source_image or image_path,
                    capture_type="superseded_candidate",
                    group_id=item.group_id,
                    visual_only=(tie_winner != "vision"),
                    bbox=item.bbox,
                )
                items.append(c)
            return (
                FieldReconciliation(
                    field_name=field_label,
                    status="CONFLICT_RESOLVED",
                    ocr_value=ocr_text,
                    vision_value=vis_text,
                    final_value=clean_text(chosen_source[0].raw_text),
                    confidence=0.95,
                    notes=f"Conflict resolved deterministically: {resolution_note}"
                ),
                items
            )

        # Unresolved conflict: Prioritize higher-confidence visual evidence for identity/dates
        pref_winner = "vision" if field_label in {"PRODUCT_NAME", "MANUFACTURING_DATE"} and vis_text else "ocr"
        favored_items = vis_items if pref_winner == "vision" else ocr_items
        other_items = ocr_items if pref_winner == "vision" else vis_items
        items = []
        for item in favored_items:
            items.append(
                ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label=field_label,
                    confidence=item.confidence or 0.80,
                    source_image=item.source_image or image_path,
                    capture_type="conflict_review",
                    group_id=item.group_id,
                    visual_only=(pref_winner == "vision"),
                    bbox=item.bbox,
                )
            )
        for item in other_items:
            items.append(
                ClassifiedEvidence(
                    raw_text=item.raw_text,
                    normalized_text=item.normalized_text or item.raw_text,
                    label="OTHER_DECLARATION",
                    confidence=item.confidence or 0.40,
                    source_image=item.source_image or image_path,
                    capture_type="conflict_review_secondary",
                    group_id=item.group_id,
                    visual_only=(pref_winner != "vision"),
                    bbox=item.bbox,
                )
            )

        final_val = vis_text if pref_winner == "vision" else ocr_text
        return (
            FieldReconciliation(
                field_name=field_label,
                status="CONFLICT_UNRESOLVED",
                ocr_value=ocr_text,
                vision_value=vis_text,
                final_value=final_val,
                confidence=0.60,
                notes=f"Unresolved semantic conflict ({conflict_reason}). Prioritized {pref_winner} for downstream processing."
            ),
            items
        )

    def _semantic_compare(
        self,
        field_label: str,
        ocr_text: str,
        vis_text: str,
    ) -> Tuple[bool, Optional[str], str]:
        """Compare two values semantically based on declaration type."""
        # 1. Price / MRP comparison
        if field_label == "MRP":
            p_ocr = self.normalizer.normalize_price(ocr_text)
            p_vis = self.normalizer.normalize_price(vis_text)
            if p_ocr is not None and p_vis is not None:
                if abs(p_ocr - p_vis) < 0.01:
                    tax_wording = "(incl. of all taxes)" if "tax" in (ocr_text + vis_text).lower() else ""
                    preferred = f"₹{p_ocr:.2f} {tax_wording}".strip()
                    return True, preferred, ""
                return False, None, f"MRP mismatch: OCR={p_ocr} vs Vision={p_vis}"

        # 2. Net Quantity comparison
        elif field_label == "NET_QUANTITY":
            q_ocr = self.normalizer.normalize_quantity(ocr_text)
            q_vis = self.normalizer.normalize_quantity(vis_text)
            if q_ocr and q_vis:
                v_ocr, u_ocr = q_ocr
                v_vis, u_vis = q_vis
                if abs(v_ocr - v_vis) < 0.01 and u_ocr == u_vis:
                    return True, f"{v_ocr:g} {u_ocr}", ""
                return False, None, f"Quantity mismatch: OCR={v_ocr}{u_ocr} vs Vision={v_vis}{u_vis}"

        # 3. Dates
        elif field_label in {"MANUFACTURING_DATE", "EXPIRY_DATE"}:
            d_ocr = self.normalizer.normalize_date(ocr_text)
            d_vis = self.normalizer.normalize_date(vis_text)
            if d_ocr and d_vis:
                if d_ocr == d_vis:
                    return True, ocr_text or vis_text, ""
                return False, None, f"Date mismatch: OCR={d_ocr} vs Vision={d_vis}"

        # 4. Text / Identity fields
        norm_ocr = self.normalizer.normalize_statutory_text(ocr_text)
        norm_vis = self.normalizer.normalize_statutory_text(vis_text)

        if not norm_ocr or not norm_vis:
            return False, None, "Empty text after normalization"

        if norm_ocr == norm_vis:
            return True, vis_text, ""

        if norm_ocr in norm_vis or norm_vis in norm_ocr:
            preferred = vis_text if len(vis_text) >= len(ocr_text) else ocr_text
            return True, preferred, ""

        words_ocr = set(norm_ocr.split())
        words_vis = set(norm_vis.split())
        intersection = words_ocr & words_vis
        union = words_ocr | words_vis
        jaccard = len(intersection) / len(union) if union else 0.0

        if jaccard >= 0.70:
            preferred = vis_text if len(vis_text) >= len(ocr_text) else ocr_text
            return True, preferred, ""

        return False, None, f"Text divergence (Jaccard={jaccard:.2f})"

    def _attempt_deterministic_resolution(
        self,
        field_label: str,
        ocr_text: str,
        vis_text: str,
    ) -> Tuple[bool, Optional[str], str]:
        """Attempt deterministic tie-breaker when OCR and Vision disagree."""
        if field_label == "PRODUCT_NAME":
            bad_kw = {"iso", "certified", "erfied", "certificate", "nutrition", "nutritional", "customer care", "fssai", "batch", "mrp", "net weight", "company"}
            ocr_words = set(re.findall(r"\b[a-zA-Z]+\b", (ocr_text or "").lower()))
            vis_words = set(re.findall(r"\b[a-zA-Z]+\b", (vis_text or "").lower()))
            ocr_bad = bool(ocr_words & bad_kw)
            vis_bad = bool(vis_words & bad_kw)
            if ocr_bad and not vis_bad and len((vis_text or "").strip()) >= 3:
                return True, "vision", "OCR candidate contains non-product keywords/fragments; Vision extracted clean product name"
            if vis_bad and not ocr_bad and len((ocr_text or "").strip()) >= 3:
                return True, "ocr", "Vision candidate contains non-product keywords; OCR extracted clean product name"
            if hasattr(self, "_raw_ocr_corpus") and self._raw_ocr_corpus and vis_text:
                vis_tokens = [w for w in vis_text.lower().split() if len(w) >= 4]
                if vis_tokens and any(w in self._raw_ocr_corpus for w in vis_tokens):
                    return True, "vision", "Vision product name corroborated by raw OCR packaging text"

        if field_label in {"MANUFACTURING_DATE", "EXPIRY_DATE"}:
            d_ocr = self.normalizer.normalize_date(ocr_text)
            d_vis = self.normalizer.normalize_date(vis_text)
            if d_vis and not d_ocr:
                return True, "vision", "Vision yielded a valid parseable date, OCR failed"
            if d_ocr and not d_vis:
                return True, "ocr", "OCR yielded a valid parseable date, Vision failed"
            if d_vis and d_ocr:
                today = datetime.now().date()
                dt_ocr = datetime(d_ocr[0], d_ocr[1], d_ocr[2] or 1).date()
                dt_vis = datetime(d_vis[0], d_vis[1], d_vis[2] or 1).date()
                if field_label == "MANUFACTURING_DATE":
                    if dt_ocr > today and dt_vis <= today:
                        return True, "vision", "OCR date is in future; Vision date is valid calendar date"
                    if dt_vis > today and dt_ocr <= today:
                        return True, "ocr", "Vision date is in future; OCR date is valid calendar date"
                    # Resolve single-year dot-matrix character confusion (e.g. 5 vs 6)
                    if abs(dt_ocr.year - dt_vis.year) == 1 and dt_vis < dt_ocr:
                        return True, "vision", "Resolved dot-matrix year confusion (5/6) in favor of earlier manufacturing date"

        if field_label == "NET_QUANTITY":
            q_ocr = self.normalizer.normalize_quantity(ocr_text)
            q_vis = self.normalizer.normalize_quantity(vis_text)
            if q_vis and not q_ocr:
                return True, "vision", "Vision parsed compliant metric quantity; OCR was invalid"
            if q_ocr and not q_vis:
                return True, "ocr", "OCR parsed compliant metric quantity; Vision was invalid"

        if field_label == "MRP":
            p_ocr = self.normalizer.normalize_price(ocr_text)
            p_vis = self.normalizer.normalize_price(vis_text)
            if p_vis is not None and p_ocr is None:
                return True, "vision", "Vision extracted valid numerical MRP; OCR had no price"
            if p_ocr is not None and p_vis is None:
                return True, "ocr", "OCR extracted valid numerical MRP; Vision had no price"

        if field_label == "BATCH":
            if len((vis_text or "").strip()) >= 3 and len((ocr_text or "").strip()) < 3:
                return True, "vision", "Vision provided full batch string; OCR was fragmented"
            if len((ocr_text or "").strip()) >= 3 and len((vis_text or "").strip()) < 3:
                return True, "ocr", "OCR provided full batch string; Vision was fragmented"

        return False, None, "No deterministic rule resolved the discrepancy"

    def _reconcile_fssai(
        self,
        ocr_evidence: List[ClassifiedEvidence],
        vision_evidence: List[ClassifiedEvidence],
        image_path: Optional[str],
    ) -> List[ClassifiedEvidence]:
        """Reconcile FSSAI numbers ensuring strict 14-digit format validation."""
        fssai_reconciled: List[ClassifiedEvidence] = []
        found_licenses = set()

        for ev in vision_evidence:
            txt = ev.raw_text or ""
            matches = re.findall(r"\b\d{14}\b", txt)
            for m in matches:
                if m not in found_licenses:
                    found_licenses.add(m)
                    fssai_reconciled.append(
                        ClassifiedEvidence(
                            raw_text=f"fssai Lic. No. {m}",
                            normalized_text=f"fssai Lic. No. {m}",
                            label="OTHER_DECLARATION",
                            confidence=0.98,
                            source_image=image_path,
                            capture_type="groq_vision",
                            visual_only=True,
                        )
                    )

        for ev in ocr_evidence:
            txt = ev.raw_text or ""
            matches = re.findall(r"\b\d{14}\b", txt)
            for m in matches:
                if m not in found_licenses:
                    found_licenses.add(m)
                    fssai_reconciled.append(
                        ClassifiedEvidence(
                            raw_text=f"fssai Lic. No. {m}",
                            normalized_text=f"fssai Lic. No. {m}",
                            label="OTHER_DECLARATION",
                            confidence=ev.confidence or 0.95,
                            source_image=image_path,
                            capture_type="paddleocr",
                            visual_only=False,
                            bbox=ev.bbox,
                        )
                    )

        self._reconciled_fssai = found_licenses
        return fssai_reconciled
