from dataclasses import dataclass
from typing import List, Optional

from compliance.context import ComplianceContext


@dataclass
class TextGeometry:
    text: str
    label: str
    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float


@dataclass
class TypographyResult:
    text: str
    label: str
    height_px: int
    width_px: int
    position_x: int
    position_y: int
    relative_size_ratio: Optional[float]
    size_status: str
    placement_status: str
    message: str
    physical_height_mm: Optional[float] = None
    minimum_height_mm: Optional[float] = None


class TypographyAnalyzer:
    """
    Measures OCR geometry and, when package dimensions + image scale
    are supplied, checks the package's minimum declaration height.
    """

    PDP_THRESHOLDS = [
        (50.0, 1.0),
        (100.0, 1.5),
        (500.0, 2.5),
        (2500.0, 4.0),
        (float("inf"), 6.0),
    ]

    PDP_MOULDED_THRESHOLDS = [
        (50.0, 2.0),
        (100.0, 3.0),
        (500.0, 4.0),
        (2500.0, 6.0),
        (float("inf"), 6.0),
    ]

    def analyze(
        self,
        classified_evidence,
        context: Optional[ComplianceContext] = None,
    ) -> List[TypographyResult]:

        context = context or ComplianceContext()

        geometries = []

        for item in classified_evidence:
            if item.visual_only:
                continue

            bbox = getattr(item, "bbox", None)
            if not bbox:
                continue

            geometry = self._geometry_from_bbox(
                text=item.normalized_text,
                label=item.label,
                bbox=bbox,
            )

            if geometry:
                geometries.append(geometry)

        reference_height = self._reference_height(geometries)
        minimum_height = self.minimum_print_height_mm(context)

        results = []

        for geometry in geometries:
            ratio = None
            if reference_height:
                ratio = geometry.height / reference_height

            physical_height = None
            size_status = "MEASURED_ONLY"
            message = (
                "Image-space typography and position measured. "
                "Physical font size requires image scale."
            )

            if context.pixels_per_mm and context.pixels_per_mm > 0:
                physical_height = (
                    geometry.height / context.pixels_per_mm
                )

                if minimum_height is not None:
                    if physical_height < minimum_height:
                        size_status = "FAIL"
                        message = (
                            f"Measured character height {physical_height:.2f} mm "
                            f"is below the configured minimum {minimum_height:.2f} mm."
                        )
                    else:
                        size_status = "PASS"
                        message = (
                            f"Measured character height {physical_height:.2f} mm "
                            f"meets the configured minimum {minimum_height:.2f} mm."
                        )
                else:
                    size_status = "MEASURED"
                    message = (
                        f"Measured character height {physical_height:.2f} mm."
                    )

            results.append(
                TypographyResult(
                    text=geometry.text,
                    label=geometry.label,
                    height_px=geometry.height,
                    width_px=geometry.width,
                    position_x=geometry.x,
                    position_y=geometry.y,
                    relative_size_ratio=ratio,
                    size_status=size_status,
                    placement_status="MEASURED",
                    message=message,
                    physical_height_mm=physical_height,
                    minimum_height_mm=minimum_height,
                )
            )

        return results

    @classmethod
    def calculate_pdp_area_cm2(
        cls,
        context: ComplianceContext,
    ) -> Optional[float]:
        shape = context.package_shape.lower().strip()

        if shape in {"rectangular", "rectangle", "box", "carton"}:
            if (
                context.package_height_cm is None
                or context.package_width_cm is None
            ):
                return None
            return context.package_height_cm * context.package_width_cm

        if shape in {"cylindrical", "cylinder", "round"}:
            if (
                context.package_height_cm is None
                or context.package_circumference_cm is None
            ):
                return None
            return (
                0.40
                * context.package_height_cm
                * context.package_circumference_cm
            )

        if shape in {"irregular", "polyhedral", "irregular_polyhedral"}:
            if context.package_surface_area_cm2 is None:
                return None
            return 0.40 * context.package_surface_area_cm2

        return None

    @classmethod
    def minimum_print_height_mm(
        cls,
        context: ComplianceContext,
    ) -> Optional[float]:
        area = cls.calculate_pdp_area_cm2(context)
        if area is None:
            return None

        thresholds = cls.PDP_THRESHOLDS
        if context.print_type.lower() in {
            "blown",
            "moulded",
            "molded",
            "perforated",
            "embossed",
        }:
            thresholds = cls.PDP_MOULDED_THRESHOLDS

        for upper_bound, minimum in thresholds:
            if area <= upper_bound:
                return minimum

        return None

    @staticmethod
    def _geometry_from_bbox(
        text: str,
        label: str,
        bbox,
    ) -> Optional[TextGeometry]:
        try:
            x1, y1, x2, y2 = [int(value) for value in bbox]
        except (TypeError, ValueError):
            return None

        width = max(0, x2 - x1)
        height = max(0, y2 - y1)

        if width == 0 or height == 0:
            return None

        return TextGeometry(
            text=text,
            label=label,
            x=x1,
            y=y1,
            width=width,
            height=height,
            center_x=(x1 + x2) / 2,
            center_y=(y1 + y2) / 2,
        )

    @staticmethod
    def _reference_height(
        geometries: List[TextGeometry],
    ) -> Optional[float]:
        if not geometries:
            return None

        heights = sorted(
            geometry.height
            for geometry in geometries
            if geometry.height > 0
        )

        if not heights:
            return None

        middle = len(heights) // 2

        if len(heights) % 2 == 0:
            return (heights[middle - 1] + heights[middle]) / 2

        return float(heights[middle])
