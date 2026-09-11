import re
import webbrowser
from dataclasses import dataclass
from typing import Optional


FOSCOS_URL = "https://foscos.fssai.gov.in/"


@dataclass
class FSSAIResult:
    license_number: str
    format_valid: bool
    status: str
    message: str
    official_url: str = FOSCOS_URL

    registered_name: Optional[str] = None
    registered_address: Optional[str] = None
    license_type: Optional[str] = None
    active_status: Optional[str] = None


class FSSAIValidator:
    """
    FSSAI licence/registration validation layer.

    Current functionality:
    - normalizes a candidate licence number
    - validates the 14-digit format
    - reports that official verification is still required

    It does NOT:
    - claim that a licence is genuine from the number alone
    - scrape around CAPTCHA
    - fabricate official business information
    """

    @staticmethod
    def normalize_license_number(value: str) -> str:
        """
        Keep only numeric characters.

        Example:
            "ABC10723999000850" -> "10723999000850"
        """

        if not value:
            return ""

        return re.sub(
            r"\D",
            "",
            str(value),
        )

    @staticmethod
    def validate_format(
        license_number: str,
    ) -> bool:
        """
        FSSAI licence/registration numbers are 14 digits.
        """

        return bool(
            re.fullmatch(
                r"\d{14}",
                license_number,
            )
        )

    def validate(
        self,
        license_number: str,
    ) -> FSSAIResult:

        normalized = self.normalize_license_number(
            license_number
        )

        if not self.validate_format(
            normalized
        ):
            return FSSAIResult(
                license_number=normalized,
                format_valid=False,
                status="INVALID_FORMAT",
                message=(
                    "The FSSAI licence/registration number "
                    "is not a valid 14-digit number."
                ),
            )

        return FSSAIResult(
            license_number=normalized,
            format_valid=True,
            status="OFFICIAL_CHECK_REQUIRED",
            message=(
                "The licence number has a valid 14-digit format. "
                "Official FoSCoS verification is required to "
                "confirm licence status and registered details."
            ),
        )

    @staticmethod
    def open_official_verification_page() -> None:
        """
        Open the official FoSCoS website.

        Automatic official verification is intentionally not
        performed here because the public verification workflow
        may require interactive controls/CAPTCHA.
        """

        webbrowser.open(
            FOSCOS_URL
        )