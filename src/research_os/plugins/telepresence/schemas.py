"""Schemas and configuration models for Telepresence and Haptics domain."""

from __future__ import annotations

from pydantic import Field
from research_os.schemas.base import ArtifactBaseModel


class TelepresenceConfig(ArtifactBaseModel):
    """Execution parameters for network jitter and tracking RMSE telepresence simulation."""

    packet_latency_ms: float = Field(default=120.0, ge=1.0, description="Mean network round-trip packet latency in ms")
    jitter_variance_ms: float = Field(default=35.0, ge=0.0, description="Network packet transmission jitter variance in ms")
    packet_loss_rate: float = Field(default=0.08, ge=0.0, le=1.0, description="Packet loss probability")
    prediction_horizon_ms: float = Field(default=60.0, ge=5.0, description="Jitter buffer forward Kalman/AR prediction window in ms")
    duration_seconds: float = Field(default=30.0, ge=2.0, description="Trajectory duration in seconds")
    tracking_frequency_hz: float = Field(default=100.0, ge=10.0, description="Operator command polling frequency in Hz")
    target_metric: str = Field(default="tracking_rmse", description="Target evaluation metric")
    expected_direction: str = Field(default="decrease", description="Target direction of improvement")
    success_threshold: float = Field(default=0.05, description="Target threshold value")
    seed: int = Field(default=42, description="Random seed")
