from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field, fields
import re
import time
from typing import Any

try:
    from ocr.paddle_ocr import PaddleOCRAdapter
    OCR_IMPORT_ERROR = None
except ImportError as exc:
    PaddleOCRAdapter = None
    OCR_IMPORT_ERROR = exc

from ai.groq_vision import GroqVisionService, classify_ocr_evidence
from extraction.merger import EvidenceMerger
from extraction.extractor import ProductExtractor
from compliance.fssai_verification import FSSAIVerificationService
from compliance.typography import TypographyAnalyzer
from compliance.engine import ComplianceEngine
from compliance.context import ComplianceContext
from extraction.schemas import ProductData


@dataclass
class ProductAnalysis:
    """
    Complete backend result for one product image.
    """

    image_path: str

    product_data: Any

    fssai_verification: Any

    typography: list = field(
        default_factory=list
    )

    compliance: Any = None

    timings: dict = field(
        default_factory=dict
    )

    reconciliations: dict = field(
        default_factory=dict
    )


class ProductAnalysisBackend:
    """
    Dual-inspection backend orchestrator.

    Flow:
        Image
          ├── PaddleOCR ──────────┐
          │                       ▼
          └── Groq Vision ──▶ EvidenceMerger ──▶ ProductExtractor ──▶ FSSAI / Typography / Compliance
    """

    def __init__(self):
        print("Initializing dual-inspection backend...")

        if PaddleOCRAdapter is None:
            raise RuntimeError(
                "PaddleOCR is unavailable. Install the project dependencies with a Python version supported by PaddlePaddle (currently Python 3.10-3.13)."
            ) from OCR_IMPORT_ERROR

        self.ocr = PaddleOCRAdapter()
        self.groq_vision = GroqVisionService()
        self.merger = EvidenceMerger()
        self.extractor = ProductExtractor()
        self.fssai = FSSAIVerificationService()
        self.typography = TypographyAnalyzer()
        self.compliance = ComplianceEngine()

        print("Backend ready.")

    def analyze_product(
        self,
        image_path: str,
        label_type: str = "food",
    ) -> ProductAnalysis:
        print("\n===== PRODUCT ANALYSIS (DUAL INSPECTION) =====\n")
        total_start = time.perf_counter()

        # --------------------------------------------------
        # STEP 1 & 2: CONCURRENT PADDLEOCR & GROQ VISION
        # --------------------------------------------------
        ocr_start = 0.0
        ocr_duration_ms = 0.0
        vision_start = 0.0
        vision_duration_ms = 0.0

        def _run_ocr():
            nonlocal ocr_start, ocr_duration_ms
            ocr_start = time.perf_counter()
            print("[1/2] Running PaddleOCR...")
            raw_ocr = self.ocr.extract(image_path)
            classified = classify_ocr_evidence(raw_ocr, image_path=image_path)
            ocr_duration_ms = (time.perf_counter() - ocr_start) * 1000
            print(f"[OCR Done] Extracted {len(classified)} OCR evidence items in {ocr_duration_ms:.1f}ms")
            return classified

        def _run_vision():
            nonlocal vision_start, vision_duration_ms
            vision_start = time.perf_counter()
            print("[1/2] Running Groq Vision...")
            vis = self.groq_vision.extract(image_path)
            vision_duration_ms = (time.perf_counter() - vision_start) * 1000
            print(f"[Vision Done] Extracted {len(vis)} visual declaration items in {vision_duration_ms:.1f}ms")
            return vis

        parallel_start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            ocr_future = executor.submit(_run_ocr)
            vision_future = executor.submit(_run_vision)

            ocr_evidence = ocr_future.result()
            vision_evidence = vision_future.result()

        parallel_inspection_ms = (time.perf_counter() - parallel_start) * 1000

        # --------------------------------------------------
        # STEP 3: FIELD-BY-FIELD EVIDENCE RECONCILIATION
        # --------------------------------------------------
        print("\n3. Reconciling OCR and Groq Vision evidence...")
        merge_start = time.perf_counter()
        merge_result = self.merger.merge(
            ocr_evidence=ocr_evidence,
            vision_evidence=vision_evidence,
            image_path=image_path,
        )
        evidence_merge_ms = (time.perf_counter() - merge_start) * 1000
        merged_evidence = merge_result.evidence
        print(f"Reconciliation complete: {len(merged_evidence)} merged evidence items in {evidence_merge_ms:.1f}ms")
        for f_name, rec in merge_result.reconciliations.items():
            if rec.status != "MISSING":
                try:
                    print(f"  • {f_name:20}: [{rec.status}] '{rec.final_value}' (conf: {rec.confidence})")
                except UnicodeEncodeError:
                    safe_v = str(rec.final_value).encode("ascii", "replace").decode("ascii")
                    print(f"  • {f_name:20}: [{rec.status}] '{safe_v}' (conf: {rec.confidence})")

        # --------------------------------------------------
        # STEP 4: PRODUCT DATA EXTRACTION
        # --------------------------------------------------
        print("\n4. Extracting ProductData from merged evidence...")
        ext_start = time.perf_counter()
        product_data = self.extractor.extract(merged_evidence)
        product_extractor_ms = (time.perf_counter() - ext_start) * 1000
        print(f"Product extraction completed in {product_extractor_ms:.1f}ms")

        # --------------------------------------------------
        # STEP 5: FSSAI VERIFICATION
        # --------------------------------------------------
        print("\n5. Running FSSAI verification...")
        fssai_result = self.fssai.verify(product_data)

        # --------------------------------------------------
        # STEP 6: TYPOGRAPHY ANALYSIS
        # --------------------------------------------------
        context = ComplianceContext(product_type=label_type)
        print("\n6. Running typography analysis...")
        typography_result = self.typography.analyze(
            merged_evidence,
            context=context,
        )

        # --------------------------------------------------
        # STEP 7: COMPLIANCE ENGINE
        # --------------------------------------------------
        print("\n7. Running compliance engine...")
        compliance_result = self.compliance.evaluate(
            product_data,
            context=context,
        )

        total_analysis_ms = (time.perf_counter() - total_start) * 1000

        timings = {
            "paddle_ocr_ms": round(ocr_duration_ms, 2),
            "groq_vision_ms": round(vision_duration_ms, 2),
            "parallel_inspection_ms": round(parallel_inspection_ms, 2),
            "evidence_merge_ms": round(evidence_merge_ms, 2),
            "product_extractor_ms": round(product_extractor_ms, 2),
            "total_analysis_ms": round(total_analysis_ms, 2),
        }

        print("\n==================================================")
        print("          PERFORMANCE BENCHMARK TIMINGS           ")
        print("==================================================")
        print(f"  • paddle_ocr_ms:          {timings['paddle_ocr_ms']:>8.2f} ms")
        print(f"  • groq_vision_ms:         {timings['groq_vision_ms']:>8.2f} ms")
        print(f"  • parallel_inspection_ms: {timings['parallel_inspection_ms']:>8.2f} ms (wall-clock)")
        print(f"  • evidence_merge_ms:      {timings['evidence_merge_ms']:>8.2f} ms")
        print(f"  • product_extractor_ms:   {timings['product_extractor_ms']:>8.2f} ms")
        print(f"  • total_analysis_ms:      {timings['total_analysis_ms']:>8.2f} ms")
        print("==================================================\n")

        return ProductAnalysis(
            image_path=image_path,
            product_data=product_data,
            fssai_verification=fssai_result,
            typography=typography_result,
            compliance=compliance_result,
            timings=timings,
            reconciliations={k: v.status for k, v in merge_result.reconciliations.items()},
        )

    def finalize_product(self, original_product: dict, officer_values: dict, label_type: str = "food"):
        """Apply officer declarations then rerun deterministic backend checks."""
        allowed = {item.name for item in fields(ProductData)}
        product = ProductData(**{key: value for key, value in original_product.items() if key in allowed})
        for key, value in officer_values.items():
            if key not in allowed or value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
            if key == "mrp" and value != "":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError("MRP must be a number.")
            if key == "fssai_licenses" and isinstance(value, str):
                value = [part.strip() for part in value.split(",") if part.strip()]
            setattr(product, key, value)
        if product.net_quantity:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg|ml|mL|l|L|m|cm|mm|N|U)\b", str(product.net_quantity))
            if match:
                product.net_quantity_value = float(match.group(1))
                product.net_quantity_unit = match.group(2)
                product.quantity_format_valid = bool(re.search(r"\d+(?:\.\d+)?\s+" + re.escape(match.group(2)) + r"\b", str(product.net_quantity)))
                product.quantity_unit_valid = True
        context = ComplianceContext(product_type=label_type)
        return product, self.compliance.evaluate(product, context=context)
