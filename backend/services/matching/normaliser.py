import re
from utils.text import clean_text

UNIT_CONVERSIONS = {
    "g": ("mass", 1),
    "kg": ("mass", 1000),
    "ml": ('volume', 1),
    "l": ("volume", 1000)
}

SIZE_PATTERN = re.compile(
    r"\s+\d+(?:\.\d+)?\s*(?:kg|ml|g|l)\b"
)

def normalise_name(name: str) -> str:
    name = re.sub(r"(?<=\w)['’](?=\w)", "", clean_text(name))
    return " ".join(name.split())

def normalise_size(quantity: float | None, unit: str | None) -> tuple[str, float] | None:
    if quantity is None or unit is None:
        return None
    unit = unit.lower().strip()
    if unit not in UNIT_CONVERSIONS:
        return None
    dimension, multiplier = UNIT_CONVERSIONS[unit]
    return dimension, round(quantity * multiplier, 6)

