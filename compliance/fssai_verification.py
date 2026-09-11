from dataclasses import dataclass, field
from typing import List

from compliance.fssai_verifier import (
    FSSAIValidator,
)
from extraction.schemas import ProductData


@dataclass
class FSSAILicenseCheck:
    license_number: str
    format_valid: bool
    status: str
    message: str


@dataclass
class FSSAIVerification:
    checks: List[FSSAILicenseCheck] = field(
        default_factory=list
    )

    overall_status: str = "NOT_CHECKED"

    verified_count: int = 0
    invalid_count: int = 0
    official_check_required_count: int = 0


class FSSAIVerificationService:
    """
    Runs FSSAI validation against all extracted licence numbers.

    Important distinction:

    VALID FORMAT
        !=
    OFFICIALLY VERIFIED

    Until an authoritative verification result is obtained,
    the status remains OFFICIAL_CHECK_REQUIRED.
    """

    def __init__(self):
        self.validator = FSSAIValidator()

    def verify(
        self,
        product: ProductData,
    ) -> FSSAIVerification:

        result = FSSAIVerification()

        licenses = product.fssai_licenses

        if not licenses:
            result.overall_status = "NOT_FOUND"
            return result

        for license_number in licenses:

            check = self.validator.validate(
                license_number
            )

            result.checks.append(
                FSSAILicenseCheck(
                    license_number=check.license_number,
                    format_valid=check.format_valid,
                    status=check.status,
                    message=check.message,
                )
            )

            if check.status == "VERIFIED":
                result.verified_count += 1

            elif check.status == "INVALID_FORMAT":
                result.invalid_count += 1

            elif (
                check.status
                == "OFFICIAL_CHECK_REQUIRED"
            ):
                result.official_check_required_count += 1

        if result.invalid_count > 0:

            result.overall_status = "INVALID"

        elif result.official_check_required_count > 0:

            result.overall_status = (
                "OFFICIAL_CHECK_REQUIRED"
            )

        elif (
            result.verified_count
            == len(result.checks)
        ):

            result.overall_status = "VERIFIED"

        else:

            result.overall_status = "UNCERTAIN"

        return result