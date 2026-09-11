from dataclasses import dataclass


@dataclass
class ComplianceContext:
    """
    Describes the type and circumstances of the package being checked.

    The frontend can populate these later.
    For now, sensible defaults are used for a normal packaged-food label.
    """

    product_type: str = "food"

    imported_goods: bool = False
    e_commerce_listing: bool = False

    solid_by_weight: bool = True
    liquid_by_volume: bool = False
    sold_by_length: bool = False
    sold_by_number: bool = False

    apparel: bool = False
    fabric_or_sheet: bool = False

    drained_weight_applicable: bool = False

    expiry_required: bool = True

    transparent_outer_wrapper: bool = False
    opaque_outer_package: bool = True

    multi_piece_pack: bool = False
    combination_pack: bool = False
    wholesale_master_carton: bool = False

    institutional_bulk_sale: bool = False

    electronic_goods: bool = False
    electronic_goods_with_qr: bool = False

    small_pack: bool = False
    bulk_pack: bool = False

    tobacco_product: bool = False
    gutkha_pan_masala: bool = False

    cement_or_fertilizer: bool = False

    physical_measurement_available: bool = False

    package_shape: str = "cylindrical"

    # Dimensions used for PDP calculations.
    package_height_cm: float | None = None
    package_width_cm: float | None = None
    package_circumference_cm: float | None = None
    package_surface_area_cm2: float | None = None

    # Whether the inspected declaration uses standard print
    # or embossed/blown/moulded/perforated presentation.
    print_type: str = "standard"

    # Optional image calibration. Example: 4.0 means 4 pixels = 1 mm.
    pixels_per_mm: float | None = None