"""Schemas and configuration models for Swarm Robotics domain."""

from __future__ import annotations

from typing import Optional
from pydantic import Field
from research_os.schemas.base import ArtifactBaseModel


class SwarmConfig(ArtifactBaseModel):
    """Execution parameters for multi-robot swarm simulation."""

    num_robots: int = Field(default=50, ge=2, description="Number of autonomous robots in arena")
    arena_size: list[float] = Field(default_factory=lambda: [10.0, 10.0], description="Arena [width, height] in meters")
    communication_radius: float = Field(default=2.5, ge=0.1, description="Local wireless radio range in meters")
    bandwidth_cap_bytes: float = Field(default=64.0, ge=1.0, description="Per-robot channel capacity cap in bytes/sec")
    packet_drop_rate: float = Field(default=0.20, ge=0.0, le=1.0, description="Simulated RF packet loss probability")
    event_trigger_threshold: float = Field(default=0.15, ge=0.01, description="Velocity state divergence threshold delta_v")
    max_steps: int = Field(default=400, ge=10, description="Simulation discrete time steps")
    dt: float = Field(default=0.1, ge=0.01, description="Time step duration in seconds")
    seed: int = Field(default=42, description="Random number generator seed")


class SwarmPaperAttributes(ArtifactBaseModel):
    """Extracted dimensional attributes for a swarm robotics paper."""

    paper_id: str = Field(description="Unique paper ID")
    title: str = Field(description="Paper title")
    year: Optional[int] = Field(default=None, description="Publication year")
    algorithm_type: str = Field(description="Coordination algorithm category")
    swarm_size_tested: str = Field(description="Scale of swarm evaluated (e.g. 'N=10 to 500')")
    communication_model: str = Field(description="Communication topology or constraints")
    local_sensing_noise: str = Field(description="Noise modeling in sensors")
    simulation_platform: str = Field(description="Simulator or physical hardware used")
    primary_metrics: list[str] = Field(default_factory=list, description="Primary evaluation metrics")
    baseline_methods: list[str] = Field(default_factory=list, description="Baselines compared against")
