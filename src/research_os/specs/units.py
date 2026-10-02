"""Strong-typed scientific unit definitions and automated conversions for Research OS.

Enforces:
- Canonical representations for dimensioned and dimensionless metrics.
- Automatic normalization (e.g. Percentage [0, 100] -> Fraction [0.0, 1.0]).
- Elimination of unit confusion between specifications, runners, and validators.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Union
from pydantic import Field, model_validator

from research_os.schemas.base import ArtifactBaseModel


class UnitType(str, Enum):
    """Catalog of supported scientific and computational measurement units."""

    # Dimensionless ratios
    FRACTION = "fraction"              # [0.0, 1.0]
    PERCENTAGE = "percentage"          # [0.0, 100.0]
    SCALAR = "scalar"                  # Arbitrary numeric scalar
    COUNT = "count"                    # Discrete integer count

    # Time units
    SECONDS = "seconds"
    MILLISECONDS = "milliseconds"
    MICROSECONDS = "microseconds"

    # Data volume units
    BYTES = "bytes"
    KILOBYTES = "kilobytes"
    MEGABYTES = "megabytes"
    GIGABYTES = "gigabytes"

    # Rate units
    RATE_PER_SECOND = "rate_per_sec"
    BYTES_PER_SECOND = "bytes_per_sec"


# Alias mapping for flexible parsing
UNIT_ALIASES: dict[str, UnitType] = {
    "fraction": UnitType.FRACTION,
    "ratio": UnitType.FRACTION,
    "[0,1]": UnitType.FRACTION,
    "percentage": UnitType.PERCENTAGE,
    "percent": UnitType.PERCENTAGE,
    "%": UnitType.PERCENTAGE,
    "scalar": UnitType.SCALAR,
    "unitless": UnitType.SCALAR,
    "count": UnitType.COUNT,
    "seconds": UnitType.SECONDS,
    "sec": UnitType.SECONDS,
    "s": UnitType.SECONDS,
    "milliseconds": UnitType.MILLISECONDS,
    "msec": UnitType.MILLISECONDS,
    "ms": UnitType.MILLISECONDS,
    "microseconds": UnitType.MICROSECONDS,
    "us": UnitType.MICROSECONDS,
    "bytes": UnitType.BYTES,
    "b": UnitType.BYTES,
    "kilobytes": UnitType.KILOBYTES,
    "kb": UnitType.KILOBYTES,
    "megabytes": UnitType.MEGABYTES,
    "mb": UnitType.MEGABYTES,
    "gigabytes": UnitType.GIGABYTES,
    "gb": UnitType.GIGABYTES,
    "rate_per_sec": UnitType.RATE_PER_SECOND,
    "qps": UnitType.RATE_PER_SECOND,
    "hz": UnitType.RATE_PER_SECOND,
    "bytes_per_sec": UnitType.BYTES_PER_SECOND,
    "b/s": UnitType.BYTES_PER_SECOND,
    "bytes/sec": UnitType.BYTES_PER_SECOND,
}


def parse_unit(unit_input: Union[UnitType, str]) -> UnitType:
    """Resolve a raw unit string or enum into a canonical UnitType."""
    if isinstance(unit_input, UnitType):
        return unit_input
    norm = str(unit_input).strip().lower()
    if norm in UNIT_ALIASES:
        return UNIT_ALIASES[norm]
    try:
        return UnitType(norm)
    except ValueError:
        raise ValueError(f"Unknown scientific measurement unit '{unit_input}'. Unregistered units strictly forbidden (U1).")


class ValueWithUnit(ArtifactBaseModel):
    """Strongly-typed numeric measurement bound to an explicit scientific unit.
    
    Provides deterministic automatic unit conversions (e.g. auto-normalizing
    Percentage [0, 100] to Fraction [0.0, 1.0]).
    """

    value: float = Field(description="Numerical value of the measurement")
    unit: UnitType = Field(description="Scientific measurement unit")
    raw_unit_string: str = Field(default="", description="Original string representation before parsing")

    @model_validator(mode="before")
    @classmethod
    def parse_and_normalize_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_unit = data.get("unit", UnitType.SCALAR)
            data["raw_unit_string"] = str(raw_unit)
            data["unit"] = parse_unit(raw_unit)
            val = data.pop("raw_value", None)
            if val is not None and "value" not in data:
                data["value"] = float(val)
            else:
                data["value"] = float(data.get("value", 0.0))

            num_val = data["value"]
            unit_val = data["unit"]
            if unit_val == UnitType.PERCENTAGE and (num_val < 0.0 or num_val > 100.0):
                raise ValueError(f"Percentage value {num_val} must be in [0.0, 100.0].")
            if unit_val == UnitType.FRACTION and (num_val < 0.0 or num_val > 1.0):
                raise ValueError(f"Fraction value {num_val} must be in [0.0, 1.0].")

        return data

    @property
    def raw_value(self) -> float:
        return self.value

    @property
    def canonical_value(self) -> float:
        return self.to_canonical().value

    @property
    def canonical_unit(self) -> UnitType:
        return self.to_canonical().unit

    def to_canonical(self) -> ValueWithUnit:
        """Convert the current measurement to its canonical base unit.
        
        Rules:
        - PERCENTAGE -> FRACTION (divide by 100.0)
        - MILLISECONDS -> SECONDS (divide by 1000.0)
        - MICROSECONDS -> SECONDS (divide by 1,000,000.0)
        - KILOBYTES -> BYTES (multiply by 1024.0)
        - MEGABYTES -> BYTES (multiply by 1024.0^2)
        - GIGABYTES -> BYTES (multiply by 1024.0^3)
        """
        if self.unit == UnitType.PERCENTAGE:
            return ValueWithUnit(
                value=self.value / 100.0,
                unit=UnitType.FRACTION,
                raw_unit_string=self.raw_unit_string,
            )
        elif self.unit == UnitType.MILLISECONDS:
            return ValueWithUnit(
                value=self.value / 1000.0,
                unit=UnitType.SECONDS,
                raw_unit_string=self.raw_unit_string,
            )
        elif self.unit == UnitType.MICROSECONDS:
            return ValueWithUnit(
                value=self.value / 1_000_000.0,
                unit=UnitType.SECONDS,
                raw_unit_string=self.raw_unit_string,
            )
        elif self.unit == UnitType.KILOBYTES:
            return ValueWithUnit(
                value=self.value * 1024.0,
                unit=UnitType.BYTES,
                raw_unit_string=self.raw_unit_string,
            )
        elif self.unit == UnitType.MEGABYTES:
            return ValueWithUnit(
                value=self.value * (1024.0 ** 2),
                unit=UnitType.BYTES,
                raw_unit_string=self.raw_unit_string,
            )
        elif self.unit == UnitType.GIGABYTES:
            return ValueWithUnit(
                value=self.value * (1024.0 ** 3),
                unit=UnitType.BYTES,
                raw_unit_string=self.raw_unit_string,
            )
        return self

    def as_fraction(self) -> float:
        """Return the value strictly normalized as a fraction in [0.0, 1.0].
        
        If value was passed as percentage (e.g. 50.0), automatically converts to 0.50.
        If value cannot represent a valid fraction, raises ValueError.
        """
        canonical = self.to_canonical()
        if canonical.unit != UnitType.FRACTION and self.unit not in (UnitType.PERCENTAGE, UnitType.FRACTION):
            # If scalar between 0 and 1, allow fraction interpretation
            if 0.0 <= canonical.value <= 1.0:
                return canonical.value
            raise ValueError(
                f"Cannot interpret unit '{self.unit}' with value {self.value} as a [0, 1] fraction."
            )
        if not (0.0 <= canonical.value <= 1.0):
            raise ValueError(f"Normalized fraction {canonical.value} is out of bounds [0.0, 1.0].")
        return canonical.value

    def convert_to(self, target_unit: Union[UnitType, str]) -> ValueWithUnit:
        """Convert this measurement into the specified target unit if compatible."""
        target = parse_unit(target_unit)
        canonical = self.to_canonical()

        # If already matching target
        if self.unit == target:
            return self

        # Ratio conversions
        if canonical.unit == UnitType.FRACTION and target == UnitType.PERCENTAGE:
            return ValueWithUnit(value=canonical.value * 100.0, unit=UnitType.PERCENTAGE, raw_unit_string=str(target_unit))
        if canonical.unit == UnitType.FRACTION and target == UnitType.FRACTION:
            return canonical

        # Time conversions
        if canonical.unit == UnitType.SECONDS:
            if target == UnitType.MILLISECONDS:
                return ValueWithUnit(value=canonical.value * 1000.0, unit=UnitType.MILLISECONDS, raw_unit_string=str(target_unit))
            if target == UnitType.MICROSECONDS:
                return ValueWithUnit(value=canonical.value * 1_000_000.0, unit=UnitType.MICROSECONDS, raw_unit_string=str(target_unit))
            if target == UnitType.SECONDS:
                return canonical

        # Data volume conversions
        if canonical.unit == UnitType.BYTES:
            if target == UnitType.KILOBYTES:
                return ValueWithUnit(value=canonical.value / 1024.0, unit=UnitType.KILOBYTES, raw_unit_string=str(target_unit))
            if target == UnitType.MEGABYTES:
                return ValueWithUnit(value=canonical.value / (1024.0 ** 2), unit=UnitType.MEGABYTES, raw_unit_string=str(target_unit))
            if target == UnitType.GIGABYTES:
                return ValueWithUnit(value=canonical.value / (1024.0 ** 3), unit=UnitType.GIGABYTES, raw_unit_string=str(target_unit))
            if target == UnitType.BYTES:
                return canonical

        raise ValueError(f"Incompatible unit conversion from '{self.unit}' to '{target}'.")
