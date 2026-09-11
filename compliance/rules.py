import re
from dataclasses import dataclass
from typing import Optional

from extraction.schemas import ProductData
from compliance.context import ComplianceContext


# ============================================================
# STATUS CONSTANTS
# ============================================================

PASS = "PASS"
FAIL = "FAIL"
NOT_FOUND = "NOT_FOUND"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
NOT_APPLICABLE = "NOT_APPLICABLE"


# ============================================================
# RULE DEFINITION
# ============================================================

@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    field: str
    title: str
    evaluator: object
    statutory_section: str = "36(1)"


# ============================================================
# HELPERS
# ============================================================

def result(
    status: str,
    message: str,
    value=None,
):
    """
    ComplianceEngine expects each evaluator to return:
        status, message, value
    """
    return status, message, value


def normalized_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


# ============================================================
# LM-001
# Manufacturer / Packer / Importer
# ============================================================

def evaluate_manufacturer(
    product: ProductData,
    context: ComplianceContext,
):
    if not product.manufacturer_name:
        return result(
            NOT_FOUND,
            "Manufacturer / packer / importer legal name was not detected.",
        )

    if not product.manufacturer_address:
        return result(
            REVIEW_REQUIRED,
            "Manufacturer name was detected, but complete physical address was not confidently detected.",
            product.manufacturer_name,
        )

    return result(
        PASS,
        "Manufacturer identity and physical address were detected.",
        product.manufacturer_name,
    )


# ============================================================
# LM-002
# Common / Generic Name
# ============================================================

def evaluate_generic_name(
    product: ProductData,
    context: ComplianceContext,
):
    if not product.product_name:
        return result(
            NOT_FOUND,
            "Common / generic product name was not detected.",
        )

    return result(
        PASS,
        "Common / generic product name was detected.",
        product.product_name,
    )


# ============================================================
# LM-003
# Net Quantity
# ============================================================

def evaluate_net_quantity(
    product: ProductData,
    context: ComplianceContext,
):
    if not product.net_quantity:
        return result(
            NOT_FOUND,
            "Net quantity was not detected.",
        )

    if product.quantity_unit_valid is False:
        return result(
            FAIL,
            "Net quantity uses an invalid metric unit.",
            product.net_quantity,
        )

    if product.quantity_format_valid is False:
        return result(
            FAIL,
            "Net quantity must use exactly one space between number and unit and use the allowed metric form.",
            product.net_quantity,
        )

    return result(
        PASS,
        "Net quantity and metric unit format are valid.",
        product.net_quantity,
    )


# ============================================================
# LM-004
# Drained Weight
# ============================================================

def evaluate_drained_weight(
    product: ProductData,
    context: ComplianceContext,
):
    if not context.drained_weight_applicable:
        return result(
            NOT_APPLICABLE,
            "Drained weight is not applicable for the selected product context.",
        )

    if not product.drained_weight:
        return result(
            NOT_FOUND,
            "Required drained weight was not detected.",
        )

    return result(
        PASS,
        "Drained weight was detected.",
        product.drained_weight,
    )


# ============================================================
# LM-005
# Maximum Retail Price
# ============================================================

def evaluate_mrp(
    product: ProductData,
    context: ComplianceContext,
):
    if product.mrp is None:
        return result(
            NOT_FOUND,
            "MRP was not detected.",
        )

    if not product.mrp_tax_inclusive_wording:
        return result(
            REVIEW_REQUIRED,
            "MRP was detected, but required tax-inclusive wording was not confidently detected.",
            product.mrp,
        )

    return result(
        PASS,
        "MRP and tax-inclusive wording were detected.",
        product.mrp,
    )


# ============================================================
# LM-006
# Dual MRP
# ============================================================

def evaluate_dual_mrp(
    product: ProductData,
    context: ComplianceContext,
):
    mrp_values = []

    for evidence in product.evidence:
        text = normalized_text(
            getattr(evidence, "text", None)
        )

        if not text:
            continue

        if "mrp" not in text.lower():
            continue

        matches = re.findall(
            r"(?:₹|Rs\.?|INR)?\s*(\d+(?:\.\d{1,2})?)",
            text,
            flags=re.IGNORECASE,
        )

        for match in matches:
            try:
                value = float(match)
            except ValueError:
                continue

            mrp_values.append(value)

    unique_values = sorted(set(mrp_values))

    if len(unique_values) <= 1:
        return result(
            PASS,
            "No conflicting MRPs were detected.",
            product.mrp,
        )

    return result(
        FAIL,
        f"Multiple different MRP values were detected: {unique_values}.",
        unique_values,
    )


# ============================================================
# USP HELPERS
# ============================================================

def quantity_in_base_units(product: ProductData) -> Optional[float]:
    value = product.net_quantity_value
    unit = (product.net_quantity_unit or "").lower()

    if value is None or not unit:
        return None

    if unit == "g":
        return value

    if unit == "kg":
        return value * 1000.0

    if unit == "ml":
        return value

    if unit == "l":
        return value * 1000.0

    return None


def expected_usp_base(
    product: ProductData,
    context: ComplianceContext,
):
    value = product.net_quantity_value
    unit = (product.net_quantity_unit or "").lower()

    if value is None or not unit:
        return None

    # Sold by number
    if context.sold_by_number:
        return "per 1 piece", 1.0

    # Sold by length
    if context.sold_by_length:
        return "per 1 metre", 1.0

    # Liquid
    if context.liquid_by_volume:
        ml = quantity_in_base_units(product)

        if ml is None:
            return None

        if ml < 1000:
            declared_u = (product.unit_sale_price_unit or "").lower()
            if "per 1 ml" in declared_u or "per ml" in declared_u or declared_u.endswith("/ml"):
                return "per 1 ml", 1.0
            return "per 100 ml", 100.0

        return "per 1 l", 1000.0

    # Solid by weight
    if context.solid_by_weight:
        grams = quantity_in_base_units(product)

        if grams is None:
            return None

        if grams < 1000:
            declared_u = (product.unit_sale_price_unit or "").lower()
            if "per 1 g" in declared_u or "per g" in declared_u or "per gram" in declared_u or declared_u.endswith("/g") or declared_u.endswith("/gm"):
                return "per 1 g", 1.0
            return "per 100 g", 100.0

        return "per 1 kg", 1000.0

    return None


def calculated_usp(
    product: ProductData,
    context: ComplianceContext,
):
    if product.mrp is None:
        return None

    quantity = quantity_in_base_units(product)

    if quantity is None or quantity <= 0:
        return None

    base = expected_usp_base(product, context)

    if base is None:
        return None

    base_label, base_quantity = base

    usp = product.mrp * base_quantity / quantity

    return usp, base_label


# ============================================================
# LM-007
# Unit Sale Price
# ============================================================

def evaluate_usp(
    product: ProductData,
    context: ComplianceContext,
):
    if context.institutional_bulk_sale:
        return result(
            NOT_APPLICABLE,
            "USP formatting is exempt for the selected institutional bulk-sale context.",
        )

    if product.mrp is None:
        return result(
            REVIEW_REQUIRED,
            "USP cannot be evaluated because MRP is missing.",
        )

    if (
        product.net_quantity_value is None
        or not product.net_quantity_unit
    ):
        return result(
            REVIEW_REQUIRED,
            "USP cannot be evaluated because net quantity is missing.",
        )

    calculated = calculated_usp(product, context)

    if calculated is None:
        return result(
            REVIEW_REQUIRED,
            "USP could not be calculated from the available quantity context.",
        )

    calculated_value, required_base = calculated

    # No declared USP detected.
    if product.unit_sale_price_value is None:
        return result(
            REVIEW_REQUIRED,
            (
                f"Calculated USP is {calculated_value:.2f} "
                f"{required_base}, but no declared USP was confidently detected."
            ),
            calculated_value,
        )

    declared_value = product.unit_sale_price_value

    tolerance = calculated_value * 0.005
    difference = abs(
        declared_value - calculated_value
    )

    if difference > tolerance:
        return result(
            FAIL,
            (
                f"Declared USP {declared_value:.2f} does not match "
                f"calculated USP {calculated_value:.2f} within ±0.5%. "
                f"Required base: {required_base}."
            ),
            declared_value,
        )

    # Numeric value is correct.
    # Unit-base verification is only performed when the extractor
    # actually supplied a declared USP unit.
    declared_unit = (
        product.unit_sale_price_unit or ""
    ).lower()

    if declared_unit:
        required_lower = required_base.lower()

        compatible = (
            required_lower in declared_unit
            or (
                required_base == "per 100 g"
                and ("100g" in declared_unit or "100 g" in declared_unit)
            )
            or (
                required_base == "per 1 g"
                and ("per 1 g" in declared_unit or "per g" in declared_unit or "per gram" in declared_unit or declared_unit == "per 1 g")
            )
            or (
                required_base == "per 100 ml"
                and ("100ml" in declared_unit or "100 ml" in declared_unit)
            )
            or (
                required_base == "per 1 ml"
                and ("per 1 ml" in declared_unit or "per ml" in declared_unit or declared_unit == "per 1 ml")
            )
            or (
                required_base == "per 1 kg"
                and (
                    "1kg" in declared_unit
                    or "kg" in declared_unit
                )
            )
            or (
                required_base == "per 1 l"
                and (
                    "1l" in declared_unit
                    or "litre" in declared_unit
                )
            )
        )

        if not compatible:
            return result(
                FAIL,
                (
                    f"USP value is numerically acceptable, but the "
                    f"declared USP base does not match the required "
                    f"base {required_base}."
                ),
                declared_value,
            )

    return result(
        PASS,
        (
            f"Declared USP {declared_value:.2f} matches calculated USP "
            f"{calculated_value:.2f} within ±0.5%; base {required_base}."
        ),
        declared_value,
    )


# ============================================================
# LM-008
# Manufacturing / Import Date
# ============================================================

def evaluate_manufacturing_date(
    product: ProductData,
    context: ComplianceContext,
):
    if not product.manufacturing_date:
        return result(
            NOT_FOUND,
            "Manufacturing / import date was not detected.",
        )

    if product.manufacturing_date_is_future:
        return result(
            FAIL,
            "Manufacturing / import date appears future/post-dated.",
            product.manufacturing_date,
        )

    return result(
        PASS,
        "Manufacturing / import date was detected.",
        product.manufacturing_date,
    )


# ============================================================
# LM-009
# Country of Origin
# ============================================================

def evaluate_country_of_origin(
    product: ProductData,
    context: ComplianceContext,
):
    required = (
        context.imported_goods
        or context.e_commerce_listing
    )

    if not required:
        return result(
            NOT_APPLICABLE,
            "Country of origin is not required for the selected context.",
        )

    if not product.country_of_origin:
        return result(
            NOT_FOUND,
            "Required country of origin was not detected.",
        )

    return result(
        PASS,
        "Country of origin was detected.",
        product.country_of_origin,
    )


# ============================================================
# LM-010
# Consumer Care
# ============================================================

def evaluate_consumer_care(
    product: ProductData,
    context: ComplianceContext,
):
    if not product.consumer_care:
        return result(
            NOT_FOUND,
            "Consumer care information was not detected.",
        )

    return result(
        PASS,
        "Consumer care information was detected.",
        product.consumer_care,
    )


# ============================================================
# LM-011
# Apparel Dimensions
# ============================================================

def evaluate_apparel_dimensions(
    product: ProductData,
    context: ComplianceContext,
):
    if not context.apparel:
        return result(
            NOT_APPLICABLE,
            "Apparel rules are not applicable.",
        )

    if not product.apparel_dimensions:
        return result(
            NOT_FOUND,
            "Required chest, waist and length dimensions were not detected.",
        )

    return result(
        PASS,
        "Apparel metric dimensions were detected.",
        product.apparel_dimensions,
    )


# ============================================================
# LM-012
# Fabric / Sheet Dimensions
# ============================================================

def evaluate_fabric_dimensions(
    product: ProductData,
    context: ComplianceContext,
):
    if not context.fabric_or_sheet:
        return result(
            NOT_APPLICABLE,
            "Fabric / sheet rules are not applicable.",
        )

    if not product.fabric_dimensions:
        return result(
            NOT_FOUND,
            "Required length and width dimensions were not detected.",
        )

    return result(
        PASS,
        "Fabric / sheet metric dimensions were detected.",
        product.fabric_dimensions,
    )


# ============================================================
# LM-013
# Expiry / Best Before
# ============================================================

def evaluate_expiry(
    product: ProductData,
    context: ComplianceContext,
):
    if not context.expiry_required:
        return result(
            NOT_APPLICABLE,
            "Expiry / best-before requirement is not enabled for this context.",
        )

    if (
        not product.expiry_date
        and not product.best_before
    ):
        return result(
            NOT_FOUND,
            "Required expiry date or best-before information was not detected.",
        )

    return result(
        PASS,
        "Expiry / best-before information was detected.",
        product.expiry_date or product.best_before,
    )


# ============================================================
# LM-014
# E-commerce
# ============================================================

def evaluate_ecommerce(
    product: ProductData,
    context: ComplianceContext,
):
    if not context.e_commerce_listing:
        return result(
            NOT_APPLICABLE,
            "E-commerce listing checks are not enabled.",
        )

    missing = []

    if product.mrp is None:
        missing.append("MRP")

    if not product.net_quantity:
        missing.append("Net Quantity")

    if (
        context.imported_goods
        and not product.country_of_origin
    ):
        missing.append("Country of Origin")

    if not product.consumer_care:
        missing.append("Consumer Care")

    if missing:
        return result(
            NOT_FOUND,
            "Missing e-commerce information: " + ", ".join(missing),
            missing,
        )

    return result(
        PASS,
        "Configured e-commerce mandatory information was detected.",
    )


# ============================================================
# LM-015
# Prohibited Quantity Wording
# ============================================================

PROHIBITED_QUANTITY_PATTERNS = [
    r"\bapprox(?:imately)?\b",
    r"\babout\b",
    r"\bwhen packed\b",
    r"\bjumbo\b",
    r"\bgiant pack\b",
]


def evaluate_prohibited_quantity_words(
    product: ProductData,
    context: ComplianceContext,
):
    for evidence in product.evidence:
        text = normalized_text(
            getattr(evidence, "text", None)
        )

        if not text:
            continue

        for pattern in PROHIBITED_QUANTITY_PATTERNS:
            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                return result(
                    FAIL,
                    "Prohibited quantity wording was detected.",
                    text,
                )

    return result(
        PASS,
        "No configured prohibited quantity wording was detected.",
    )


# ============================================================
# RULE REGISTRY
# ============================================================

RULES = [
    RuleDefinition(
        rule_id="LM-001",
        field="manufacturer_name",
        title="Manufacturer / Packer / Importer",
        evaluator=evaluate_manufacturer,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-002",
        field="product_name",
        title="Common / Generic Name",
        evaluator=evaluate_generic_name,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-003",
        field="net_quantity",
        title="Net Quantity",
        evaluator=evaluate_net_quantity,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-004",
        field="drained_weight",
        title="Drained Weight",
        evaluator=evaluate_drained_weight,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-005",
        field="mrp",
        title="Maximum Retail Price",
        evaluator=evaluate_mrp,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-006",
        field="mrp",
        title="Dual MRP",
        evaluator=evaluate_dual_mrp,
        statutory_section="36(3)",
    ),

    RuleDefinition(
        rule_id="LM-007",
        field="unit_sale_price",
        title="Unit Sale Price",
        evaluator=evaluate_usp,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-008",
        field="manufacturing_date",
        title="Manufacturing / Import Date",
        evaluator=evaluate_manufacturing_date,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-009",
        field="country_of_origin",
        title="Country of Origin",
        evaluator=evaluate_country_of_origin,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-010",
        field="consumer_care",
        title="Consumer Care",
        evaluator=evaluate_consumer_care,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-011",
        field="apparel_dimensions",
        title="Apparel Size / Dimensions",
        evaluator=evaluate_apparel_dimensions,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-012",
        field="fabric_dimensions",
        title="Fabric / Sheet Dimensions",
        evaluator=evaluate_fabric_dimensions,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-013",
        field="expiry_date",
        title="Expiry / Best Before",
        evaluator=evaluate_expiry,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-014",
        field="ecommerce",
        title="E-commerce Mandatory Information",
        evaluator=evaluate_ecommerce,
        statutory_section="36(1)",
    ),

    RuleDefinition(
        rule_id="LM-015",
        field="net_quantity",
        title="Prohibited Quantity Wording",
        evaluator=evaluate_prohibited_quantity_words,
        statutory_section="36(1)",
    ),
]