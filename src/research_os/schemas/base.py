"""Base model for all Research OS schemas providing YAML and JSON serialization."""

from __future__ import annotations

import json
from typing import Any, TypeVar
import yaml
from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound="ArtifactBaseModel")


class ArtifactBaseModel(BaseModel):
    """Base class for all typed artifacts in Research OS.

    Enforces strict attribute validation, disallows undeclared fields,
    and provides deterministic JSON and YAML round-trip serialization.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_json(self, indent: int = 2) -> str:
        """Serialize artifact to formatted JSON string."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls: type[T], json_str: str) -> T:
        """Deserialize artifact from JSON string."""
        return cls.model_validate_json(json_str)

    def to_yaml(self) -> str:
        """Serialize artifact to formatted YAML string."""
        data = json.loads(self.model_dump_json())
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls: type[T], yaml_str: str) -> T:
        """Deserialize artifact from YAML string."""
        raw_dict = yaml.safe_load(yaml_str)
        if not isinstance(raw_dict, dict):
            raise ValueError(f"YAML content did not parse into a dictionary: {raw_dict}")
        return cls.model_validate(raw_dict)
