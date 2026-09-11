from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class OCREvidence:
    text: str
    confidence: float
    source_image: str
    capture_type: Optional[str] = None
    bbox: Optional[list] = None


@dataclass
class ProductData:
    product_name: Optional[str] = None

    mrp: Optional[float] = None
    mrp_tax_inclusive_wording: Optional[str] = None

    net_quantity: Optional[str] = None
    net_quantity_value: Optional[float] = None
    net_quantity_unit: Optional[str] = None
    quantity_format_valid: Optional[bool] = None
    quantity_unit_valid: Optional[bool] = None

    unit_sale_price: Optional[str] = None
    unit_sale_price_value: Optional[float] = None
    unit_sale_price_unit: Optional[str] = None

    manufacturing_date: Optional[str] = None
    manufacturing_date_is_future: Optional[bool] = None

    expiry_date: Optional[str] = None
    packed_on: Optional[str] = None
    best_before: Optional[str] = None
    derived_shelf_life: Optional[str] = None

    manufacturer_name: Optional[str] = None
    manufacturer_address: Optional[str] = None

    marketer_name: Optional[str] = None
    marketer_address: Optional[str] = None

    batch_number: Optional[str] = None
    fssai_licenses: list[str] = field(default_factory=list)

    country_of_origin: Optional[str] = None
    consumer_care: Optional[str] = None
    drained_weight: Optional[str] = None

    apparel_dimensions: Optional[str] = None
    fabric_dimensions: Optional[str] = None

    printed_usp: Optional[float] = None

    evidence: list[Any] = field(default_factory=list)
