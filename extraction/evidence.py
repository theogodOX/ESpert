"""Provider-neutral OCR classification data structures."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ClassifiedEvidence:
    evidence_index: int = 0
    raw_text: str = ""
    normalized_text: str = ""
    label: str = "OTHER_DECLARATION"
    confidence: float = 1.0
    source_image: Optional[str] = None
    capture_type: Optional[str] = None
    group_id: Optional[int] = None
    visual_only: bool = False
    bbox: Optional[Any] = None

    def __post_init__(self) -> None:
        if not self.normalized_text and self.raw_text:
            self.normalized_text = self.raw_text
        elif not self.raw_text and self.normalized_text:
            self.raw_text = self.normalized_text

    @property
    def text(self) -> str:
        return self.raw_text

    @property
    def category(self) -> str:
        return self.label

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
