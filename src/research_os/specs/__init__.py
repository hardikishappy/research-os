"""Strong-typed specification contracts, units, and metric catalog for Research OS."""

from .units import UnitType, ValueWithUnit, parse_unit
from .catalog import MetricCatalog, MetricDefinition
from .mechanism import MechanismContract, MechanismEventRequirement
from .contracts import (
    RunnerIntrospection,
    SpecContractValidationError,
    introspect_runner_contract,
    verify_spec_contract,
)

__all__ = [
    "UnitType",
    "ValueWithUnit",
    "parse_unit",
    "MetricCatalog",
    "MetricDefinition",
    "MechanismContract",
    "MechanismEventRequirement",
    "RunnerIntrospection",
    "SpecContractValidationError",
    "introspect_runner_contract",
    "verify_spec_contract",
]
