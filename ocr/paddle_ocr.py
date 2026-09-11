import os
import re
import tempfile
import time
from typing import List, Optional

import cv2
import numpy as np

from paddleocr import PaddleOCR

from extraction.schemas import OCREvidence


class PaddleOCRAdapter:
    """
    Enhanced PaddleOCR adapter for ESPERT.

    The adapter performs multiple OCR passes:

    1. Original full image
    2. Enlarged full image
    3. Bottom portion of the package
    4. Enhanced bottom portion for dot-matrix printing
    5. High-contrast grayscale bottom portion

    This is particularly useful for package declarations such as:

    - Batch Number
    - Mfg. Date
    - Exp. Date
    - MRP

    which are frequently printed using low-contrast dot-matrix ink.
    """

    def __init__(self, lang: str = "en"):

        self.ocr = PaddleOCR(
            lang=lang,
            enable_mkldnn=False,
        )

    # ============================================================
    # OCR RESULT CONVERSION
    # ============================================================

    def _extract_from_result(
        self,
        result,
        image_path: str,
        capture_type: Optional[str] = None,
    ) -> List[OCREvidence]:

        evidence: List[OCREvidence] = []

        for page in result:

            texts = page.get("rec_texts", [])
            scores = page.get("rec_scores", [])
            boxes = page.get("rec_boxes", [])

            for i, text in enumerate(texts):

                if text is None:
                    continue

                text = str(text).strip()

                if not text:
                    continue

                confidence = 0.0

                if i < len(scores):

                    try:
                        confidence = float(scores[i])
                    except (TypeError, ValueError):
                        confidence = 0.0

                bbox = None

                if i < len(boxes):

                    box = boxes[i]

                    if hasattr(box, "tolist"):
                        bbox = box.tolist()
                    else:
                        bbox = box

                evidence.append(
                    OCREvidence(
                        text=text,
                        confidence=confidence,
                        source_image=image_path,
                        capture_type=capture_type,
                        bbox=bbox,
                    )
                )

        return evidence

    # ============================================================
    # OCR ONE IMAGE
    # ============================================================

    def _run_ocr(
        self,
        image_path: str,
        capture_type: Optional[str] = None,
    ) -> List[OCREvidence]:

        try:

            result = self.ocr.predict(image_path)

            return self._extract_from_result(
                result=result,
                image_path=image_path,
                capture_type=capture_type,
            )

        except Exception as exc:

            print(
                f"OCR pass failed "
                f"({capture_type or 'unknown'}): {exc}"
            )

            return []

    # ============================================================
    # SAVE TEMPORARY IMAGE
    # ============================================================

    def _save_temp_image(
        self,
        image: np.ndarray,
        suffix: str,
    ) -> Optional[str]:

        try:

            handle = tempfile.NamedTemporaryFile(
                prefix="espert_ocr_",
                suffix=suffix,
                delete=False,
            )

            path = handle.name

            handle.close()

            success = cv2.imwrite(
                path,
                image,
            )

            if not success:

                try:
                    os.remove(path)
                except OSError:
                    pass

                return None

            return path

        except Exception as exc:

            print(
                f"Unable to create OCR temporary image: {exc}"
            )

            return None

    # ============================================================
    # NORMALIZE TEXT FOR DEDUPLICATION
    # ============================================================

    def _normalize_text(
        self,
        text: str,
    ) -> str:

        return (
            str(text)
            .lower()
            .replace(" ", "")
            .replace(":", "")
            .replace(".", "")
            .replace(",", "")
            .strip()
        )

    # ============================================================
    # DEDUPLICATE OCR RESULTS
    # ============================================================

    def _deduplicate(
        self,
        evidence: List[OCREvidence],
    ) -> List[OCREvidence]:

        unique = []

        seen = {}

        for item in evidence:

            text = str(item.text).strip()

            if not text:
                continue

            normalized = self._normalize_text(
                text
            )

            if not normalized:
                continue

            # If the same text is found multiple times,
            # retain the version with the highest confidence.
            if normalized in seen:

                existing_index = seen[normalized]

                existing = unique[existing_index]

                if item.confidence > existing.confidence:

                    unique[existing_index] = item

                continue

            seen[normalized] = len(unique)

            unique.append(item)

        return unique

    # ============================================================
    # MAIN EXTRACTION
    # ============================================================

    def extract(
        self,
        image_path: str,
        capture_type: Optional[str] = None,
    ) -> List[OCREvidence]:

        print(
            "\n[OCR] Starting enhanced multi-pass OCR..."
        )

        all_evidence: List[OCREvidence] = []

        temp_files = []

        try:

            pass_timings = {}

            # ----------------------------------------------------
            # PASS 1
            # ORIGINAL IMAGE (Always executed)
            # ----------------------------------------------------
            print("[OCR] Pass 1: Original image")
            t0 = time.perf_counter()
            original_evidence = self._run_ocr(
                image_path=image_path,
                capture_type=capture_type or "full_image",
            )
            pass_timings["Pass 1 (Original)"] = (time.perf_counter() - t0) * 1000
            all_evidence.extend(original_evidence)

            # ----------------------------------------------------
            # LOAD IMAGE
            # ----------------------------------------------------
            image = cv2.imread(image_path)
            if image is None:
                print(
                    "[OCR] OpenCV could not load image. "
                    "Returning original OCR results."
                )
                return self._deduplicate(all_evidence)

            height, width = image.shape[:2]
            print(f"[OCR] Image size: {width} x {height}")

            # ----------------------------------------------------
            # PASS 2
            # UPSCALED FULL IMAGE (Conditional Fallback for low-yield images)
            # ----------------------------------------------------
            if len(original_evidence) < 20:
                print("[OCR] Pass 2: Enlarged full image (Low initial yield fallback)")
                t0 = time.perf_counter()
                enlarged = cv2.resize(
                    image,
                    None,
                    fx=1.75,
                    fy=1.75,
                    interpolation=cv2.INTER_CUBIC,
                )
                enlarged_path = self._save_temp_image(enlarged, ".png")
                if enlarged_path:
                    temp_files.append(enlarged_path)
                    p2_evidence = self._run_ocr(enlarged_path, "full_image_enlarged")
                    all_evidence.extend(p2_evidence)
                pass_timings["Pass 2 (Full enlarged)"] = (time.perf_counter() - t0) * 1000
            else:
                print(f"[OCR] Pass 2: Skipped (Pass 1 yielded {len(original_evidence)} detections; full upscale unnecessary)")

            # ----------------------------------------------------
            # BOTTOM PACKAGE REGION (Statutory declaration panel)
            # ----------------------------------------------------
            bottom_start = int(height * 0.50)
            bottom_region = image[bottom_start:height, 0:width]

            if bottom_region.size > 0:
                # ------------------------------------------------
                # PASS 3
                # ENLARGED BOTTOM REGION (High-yield statutory panel)
                # ------------------------------------------------
                print("[OCR] Pass 3: Enlarged bottom statutory panel")
                t0 = time.perf_counter()
                bottom_large = cv2.resize(
                    bottom_region,
                    None,
                    fx=2.0,
                    fy=2.0,
                    interpolation=cv2.INTER_CUBIC,
                )
                bottom_path = self._save_temp_image(bottom_large, ".png")
                if bottom_path:
                    temp_files.append(bottom_path)
                    p3_evidence = self._run_ocr(bottom_path, "bottom_region")
                    all_evidence.extend(p3_evidence)
                pass_timings["Pass 3 (Bottom panel)"] = (time.perf_counter() - t0) * 1000

                # Check if faint dot-matrix fields (price, dates, batch) need enhanced recovery
                curr_texts = " ".join(str(getattr(e, "text", "")).lower() for e in all_evidence)
                has_price = bool(re.search(r"\b\d+\.\d{2}\b", curr_texts))
                has_batch = bool(re.search(r"batch|b\.?\s*no", curr_texts))
                # ------------------------------------------------
                # PASS 4
                # CONTRAST ENHANCED DOT-MATRIX REGION (CLAHE)
                # ------------------------------------------------
                # Always run Pass 4 if dot-matrix print or price might be faint
                print("[OCR] Pass 4: Enhanced bottom region (CLAHE dot-matrix)")
                t0 = time.perf_counter()
                gray = cv2.cvtColor(bottom_region, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                enhanced = cv2.resize(
                    enhanced,
                    None,
                    fx=2.0,
                    fy=2.0,
                    interpolation=cv2.INTER_CUBIC,
                )
                enhanced = cv2.GaussianBlur(enhanced, (3, 3), 0)
                enhanced_path = self._save_temp_image(enhanced, ".png")
                if enhanced_path:
                    temp_files.append(enhanced_path)
                    p4_evidence = self._run_ocr(enhanced_path, "bottom_enhanced")
                    all_evidence.extend(p4_evidence)
                pass_timings["Pass 4 (CLAHE dot-matrix)"] = (time.perf_counter() - t0) * 1000

                # ------------------------------------------------
                # PASS 5
                # HIGH CONTRAST THRESHOLD (Conditional Fallback)
                # ------------------------------------------------
                # Check whether Pass 4 already recovered the price and dot-matrix markers
                p4_texts = " ".join(str(getattr(e, "text", "")).lower() for e in all_evidence)
                p4_has_price = bool(re.search(r"\b\d+\.\d{2}\b", p4_texts))
                p4_has_batch = bool(re.search(r"batch|b\.?\s*no", p4_texts))

                if not (p4_has_price and p4_has_batch):
                    print("[OCR] Pass 5: High contrast dot-matrix fallback")
                    t0 = time.perf_counter()
                    threshold = cv2.adaptiveThreshold(
                        gray,
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        31,
                        7,
                    )
                    threshold = cv2.resize(
                        threshold,
                        None,
                        fx=2.0,
                        fy=2.0,
                        interpolation=cv2.INTER_CUBIC,
                    )
                    threshold_path = self._save_temp_image(threshold, ".png")
                    if threshold_path:
                        temp_files.append(threshold_path)
                        p5_evidence = self._run_ocr(threshold_path, "bottom_high_contrast")
                        all_evidence.extend(p5_evidence)
                    pass_timings["Pass 5 (Threshold fallback)"] = (time.perf_counter() - t0) * 1000
                else:
                    print("[OCR] Pass 5: Skipped (Dot-matrix and price details already captured by earlier passes)")

            print("\n[OCR Multi-Pass Breakdown]")
            for p_label, p_ms in pass_timings.items():
                print(f"  • {p_label:32}: {p_ms:>8.1f} ms ({p_ms/1000:.1f}s)")

            # ----------------------------------------------------
            # DEDUPLICATE
            # ----------------------------------------------------

            evidence = self._deduplicate(
                all_evidence
            )

            print(
                f"[OCR] Total raw detections: "
                f"{len(all_evidence)}"
            )

            print(
                f"[OCR] Unique OCR evidence: "
                f"{len(evidence)}"
            )

            # ----------------------------------------------------
            # DEBUG OUTPUT
            # ----------------------------------------------------

            print(
                "\n[OCR] DETECTED TEXT:"
            )

            for index, item in enumerate(
                evidence
            ):
                try:
                    print(
                        f"{index + 1}. "
                        f"[{item.capture_type}] "
                        f"{item.text}"
                    )
                except UnicodeEncodeError:
                    safe_text = str(item.text).encode("ascii", "replace").decode("ascii")
                    print(
                        f"{index + 1}. "
                        f"[{item.capture_type}] "
                        f"{safe_text}"
                    )

            print()

            return evidence

        finally:

            # ----------------------------------------------------
            # CLEAN TEMP OCR FILES
            # ----------------------------------------------------

            for path in temp_files:

                try:

                    if (
                        path
                        and os.path.exists(path)
                    ):
                        os.remove(path)

                except OSError:

                    pass