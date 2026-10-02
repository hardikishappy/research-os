"""Typed Domain Artifacts for Research OS.

All artifacts use strict Pydantic v2 models with deterministic serialization.
Conversational state is strictly forbidden.
"""

from .paper import ExtractedEquation, PaperExtraction, PaperMetadata, SectionProvenance
from .synthesis import CrossPaperSynthesis, ResearchGap
from .hypothesis import HypothesisProposal
from .experiment import ExperimentClass, ExperimentSpec, ExperimentType, HardwareRequirements, ResourceLimits
from .verification import MetricVerification, VerificationReport, VerificationStatus
from .gate import GateKind, GateStatus, HumanGateToken
from .evaluation import (
    EvaluationReport,
    GridCombinationSummary,
    GridEvaluationReport,
    HypothesisVerdict,
    MetricAggregate,
    ReplicationStatus,
    SeedRunSummary,
    StatisticalAnalysisResult,
    StatisticalSupport,
    ThresholdStatus,
)

__all__ = [
    "PaperMetadata",
    "SectionProvenance",
    "ExtractedEquation",
    "PaperExtraction",
    "ResearchGap",
    "CrossPaperSynthesis",
    "HypothesisProposal",
    "ExperimentClass",
    "ExperimentSpec",
    "ExperimentType",
    "HardwareRequirements",
    "ResourceLimits",
    "MetricVerification",
    "VerificationReport",
    "VerificationStatus",
    "GateKind",
    "GateStatus",
    "HumanGateToken",
    "EvaluationReport",
    "GridCombinationSummary",
    "GridEvaluationReport",
    "HypothesisVerdict",
    "MetricAggregate",
    "ReplicationStatus",
    "SeedRunSummary",
    "StatisticalSupport",
    "ThresholdStatus",
]
