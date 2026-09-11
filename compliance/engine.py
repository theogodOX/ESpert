from dataclasses import dataclass, field
from typing import Any, List, Optional

from extraction.schemas import ProductData
from compliance.context import ComplianceContext
from compliance.required_fields import get_required_fields

from compliance.rules import (
    RULES,
    PASS,
    FAIL,
    NOT_FOUND,
    REVIEW_REQUIRED,
    NOT_APPLICABLE,
)


@dataclass
class ComplianceCheck:
    rule_id: str
    field: str
    title: str
    status: str
    message: str
    value: Any = None
    statutory_section: Optional[str] = None


@dataclass
class FieldStatus:
    """
    Data-completion contract for the future frontend.

    Detected values:
        editable = False

    Missing values:
        editable = True
    """

    key: str
    label: str
    value: Any = None
    required: bool = True
    editable: bool = True


@dataclass
class ComplianceReport:
    checks: List[ComplianceCheck] = field(
        default_factory=list
    )

    overall_status: str = REVIEW_REQUIRED

    passed: int = 0
    failed: int = 0
    not_found: int = 0
    review_required: int = 0
    not_applicable: int = 0

    field_status: List[FieldStatus] = field(
        default_factory=list
    )


class ComplianceEngine:
    """
    Executes deterministic compliance rules.

    The engine does not call Gemini and does not invent missing values.
    """

    def evaluate(
        self,
        product: ProductData,
        context: Optional[ComplianceContext] = None,
    ) -> ComplianceReport:

        if context is None:
            context = ComplianceContext()

        report = ComplianceReport()

        # --------------------------------------------
        # Run compliance rules
        # --------------------------------------------

        for rule in RULES:

            status, message, value = rule.evaluator(
                product,
                context,
            )

            statutory_section = None

            if status == FAIL:
                statutory_section = rule.statutory_section

            report.checks.append(
                ComplianceCheck(
                    rule_id=rule.rule_id,
                    field=rule.field,
                    title=rule.title,
                    status=status,
                    message=message,
                    value=value,
                    statutory_section=statutory_section,
                )
            )

        # --------------------------------------------
        # Summary
        # --------------------------------------------

        self._calculate_summary(report)

        # --------------------------------------------
        # Frontend field-completion contract
        # --------------------------------------------

        report.field_status = self._build_field_status(
            product,
            context,
        )

        return report

    @staticmethod
    def _value_is_present(value: Any) -> bool:
        """
        Determines whether a ProductData field has a usable value.

        Lists are present only when they contain at least one item.
        Strings must contain non-whitespace text.
        Numeric zero is considered a real value.
        """

        if value is None:
            return False

        if isinstance(value, str):
            return bool(value.strip())

        if isinstance(value, list):
            return len(value) > 0

        return True

    @classmethod
    def _build_field_status(
        cls,
        product: ProductData,
        context: ComplianceContext,
    ) -> List[FieldStatus]:

        fields = get_required_fields(
            context.product_type
        )

        result = []

        for field_definition in fields:

            value = getattr(
                product,
                field_definition.key,
                None,
            )

            present = cls._value_is_present(value)

            result.append(
                FieldStatus(
                    key=field_definition.key,
                    label=field_definition.label,
                    value=value,
                    required=field_definition.required,
                    editable=not present,
                )
            )

        return result

    @staticmethod
    def _calculate_summary(
        report: ComplianceReport,
    ):

        report.passed = sum(
            1
            for check in report.checks
            if check.status == PASS
        )

        report.failed = sum(
            1
            for check in report.checks
            if check.status == FAIL
        )

        report.not_found = sum(
            1
            for check in report.checks
            if check.status == NOT_FOUND
        )

        report.review_required = sum(
            1
            for check in report.checks
            if check.status == REVIEW_REQUIRED
        )

        report.not_applicable = sum(
            1
            for check in report.checks
            if check.status == NOT_APPLICABLE
        )

        # Deterministic overall status.

        if report.failed > 0:
            report.overall_status = FAIL

        elif report.review_required > 0:
            report.overall_status = REVIEW_REQUIRED

        elif report.not_found > 0:
            report.overall_status = REVIEW_REQUIRED

        else:
            report.overall_status = PASS