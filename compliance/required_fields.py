from dataclasses import dataclass
from typing import List


@dataclass
class RequiredField:
    key: str
    label: str
    required: bool = True


FOOD_LABEL_FIELDS: List[RequiredField] = [
    RequiredField("product_name", "Common / Generic Name"),
    RequiredField("net_quantity", "Net Quantity"),
    RequiredField("mrp", "Maximum Retail Price (MRP)"),
    RequiredField("unit_sale_price", "Unit Sale Price (USP)", required=False),
    RequiredField("manufacturing_date", "Manufacturing Date"),
    RequiredField("expiry_date", "Expiry / Use By Date", required=False),
    RequiredField("best_before", "Best Before", required=False),
    RequiredField("derived_shelf_life", "Derived Shelf Life", required=False),
    RequiredField("manufacturer_name", "Manufacturer Name"),
    RequiredField("manufacturer_address", "Manufacturer Address"),
    RequiredField("marketer_name", "Marketer Name", required=False),
    RequiredField("marketer_address", "Marketer Address", required=False),
    RequiredField("batch_number", "Batch / Lot Number"),
    RequiredField("fssai_licenses", "FSSAI Licence Number", required=False),
    RequiredField("consumer_care", "Consumer Care Details", required=False),
    RequiredField("country_of_origin", "Country of Origin", required=False),
]


LABEL_SCHEMAS = {
    "food": FOOD_LABEL_FIELDS,
}


def get_required_fields(label_type: str = "food") -> List[RequiredField]:
    return LABEL_SCHEMAS.get(label_type, FOOD_LABEL_FIELDS)
