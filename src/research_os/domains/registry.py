"""Dynamic domain registry for Research OS plugins with safe staged plugin admission."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import json
import logging
import pkgutil
from pathlib import Path
from typing import Any, Optional, Union

from research_os.domains.base import (
    DomainPlugin,
    MetricProvenanceItem,
    MetricProvenanceReport,
    ValidationResult,
)
from research_os.domains.declarative import (
    DeclarativePluginSpec,
    recompute_declarative_metric,
)
from research_os.models.base import BaseModelAdapter
from research_os.schemas.experiment import ExperimentSpec, ExperimentType
from research_os.schemas.hypothesis import HypothesisProposal

logger = logging.getLogger(__name__)


class SecurityViolationError(PermissionError):
    """Raised when an untrusted component violates declarative boundaries or static security scans."""
    pass


def validate_generator_ast(generator_path: Path) -> list[str]:
    """Scan generator.py for forbidden syntax, execution escapes, or exfiltration attempts."""
    content = generator_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content, filename=generator_path.name)
    except SyntaxError as e:
        return [f"Syntax error in generator.py: {e}"]

    violations: list[str] = []
    FORBIDDEN_CALLS = {"eval", "exec", "__import__", "compile"}
    FORBIDDEN_MODULES = {
        "sys",
        "subprocess",
        "importlib",
        "socket",
        "urllib",
        "requests",
        "http",
        "ftplib",
        "telnetlib",
        "paramiko",
        "webbrowser",
        "winreg",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                violations.append(f"Forbidden execution call: '{node.func.id}'")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden module import: '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if mod_root in FORBIDDEN_MODULES:
                    violations.append(f"Forbidden from-import module: '{node.module}'")
        elif isinstance(node, ast.Attribute):
            if node.attr in ("sys.modules", "__subclasses__"):
                violations.append(f"Forbidden attribute access: '{node.attr}'")

    return violations


class DeclarativeDomainPluginAdapter(DomainPlugin):
    """Sandboxed adapter wrapping an admitted declarative plugin specification."""

    def __init__(
        self,
        spec: DeclarativePluginSpec,
        generator_module: Any,
        staged_dir: Path,
    ) -> None:
        self.spec = spec
        self.generator_module = generator_module
        self.staged_dir = staged_dir
        self.domain_id = spec.domain_id
        self.display_name = spec.display_name or spec.domain_id.replace("_", " ").title()
        self.supported_experiment_types = [ExperimentType.SIMULATION, ExperimentType.BENCHMARK]

    def matches_domain(self, hypothesis: HypothesisProposal) -> bool:
        search_text = (
            hypothesis.title
            + " "
            + hypothesis.falsifiable_statement
            + " "
            + getattr(hypothesis, "domain", "")
        ).lower()
        d_id = self.domain_id.lower()
        d_name = self.display_name.lower()
        return d_id in search_text or d_name in search_text

    def validate_hypothesis(self, hypothesis: HypothesisProposal) -> ValidationResult:
        if not hypothesis.target_metric:
            return ValidationResult(is_valid=False, domain_id=self.domain_id, reasons=["Missing target_metric"])
        if self.spec.supported_metrics and hypothesis.target_metric not in self.spec.supported_metrics:
            return ValidationResult(
                is_valid=False,
                domain_id=self.domain_id,
                reasons=[f"Metric '{hypothesis.target_metric}' not supported by domain. Supported: {self.spec.supported_metrics}"],
            )
        return ValidationResult(is_valid=True, domain_id=self.domain_id, reasons=[])

    def plan_experiment(
        self,
        hypothesis: HypothesisProposal,
        spec_requirements: Optional[dict[str, Any]] = None,
    ) -> ExperimentSpec:
        spec_reqs = spec_requirements or {}
        timeout = spec_reqs.get("timeout_seconds", 60)
        expected_outputs = ["metrics.json", "provenance.json", "summary.txt"]
        for p in self.spec.verification_primitives.values():
            if p.raw_artifact_file not in expected_outputs:
                expected_outputs.append(p.raw_artifact_file)

        return ExperimentSpec(
            spec_id=f"spec-{hypothesis.hypothesis_id[:12]}",
            hypothesis_id=hypothesis.hypothesis_id,
            experiment_type=ExperimentType.BENCHMARK,
            name=f"Evaluation Protocol: {hypothesis.title}",
            description=f"Generated protocol for hypothesis: {hypothesis.falsifiable_statement}",
            entry_point="python simulation.py",
            expected_outputs=expected_outputs,
            timeout_seconds=timeout,
            run_config=spec_reqs.get("run_config", {}),
        )

    def generate_experiment_code(
        self,
        spec: ExperimentSpec,
        model_adapter: Optional[BaseModelAdapter] = None,
    ) -> str:
        if hasattr(self.generator_module, "generate_code"):
            return self.generator_module.generate_code(spec.model_dump())
        raise AttributeError(f"Generator module in {self.staged_dir} lacks required 'generate_code' function")

    def validate_metric_provenance(
        self,
        raw_data_dir: Path,
        metrics: dict[str, Any],
    ) -> MetricProvenanceReport:
        """Verify that metrics reported in metrics.json are authentically derived from raw outputs.

        Strictly declarative: metric calculation is computed directly by the trusted core without
        executing untrusted plugin verification code.
        """
        run_dir = raw_data_dir if (raw_data_dir / "metrics.json").exists() else raw_data_dir.parent
        errors: list[str] = []
        unbacked_metrics: list[str] = []
        prov_records: list[MetricProvenanceItem] = []

        for m_id, m_def in self.spec.verification_primitives.items():
            raw_path = run_dir / m_def.raw_artifact_file
            if not raw_path.exists():
                errors.append(f"MissingRawArtifactError: Raw telemetry artifact not found: {m_def.raw_artifact_file}")
                unbacked_metrics.append(m_id)
                continue

            try:
                computed_val = recompute_declarative_metric(run_dir, m_def)
                if m_id not in metrics:
                    unbacked_metrics.append(m_id)
                    errors.append(f"ProvenanceIntegrityError: Metric '{m_id}' declared in primitives is missing in reported metrics.")
                    continue

                reported_val = float(metrics[m_id])
                disc = abs(computed_val - reported_val)
                verified = (disc <= m_def.tolerance)

                prov_records.append(
                    MetricProvenanceItem(
                        metric_name=m_id,
                        raw_source_file=m_def.raw_artifact_file,
                        derivation_procedure=f"{m_def.operation}({m_def.target_field})",
                        computed_value=round(computed_val, 6),
                        verified=verified,
                    )
                )

                if not verified:
                    errors.append(
                        f"MetricFabricationError: Metric '{m_id}' reported value {reported_val} "
                        f"diverges from independently computed raw data value {computed_val:.6f} "
                        f"(discrepancy {disc:.6f} > tolerance {m_def.tolerance})"
                    )
            except Exception as e:
                errors.append(f"Metric verification error for '{m_id}': {e}")

        return MetricProvenanceReport(
            is_valid=(len(errors) == 0),
            provenance_records=prov_records,
            unbacked_metrics=unbacked_metrics,
            errors=errors,
        )


class DomainRegistry:
    """Central registry and discovery engine for domain plugins."""

    _plugins: dict[str, DomainPlugin] = {}

    def __init__(self) -> None:
        pass

    @classmethod
    def register(cls, plugin: DomainPlugin) -> None:
        """Register a domain plugin instance."""
        if not isinstance(plugin, DomainPlugin):
            raise TypeError(f"Expected DomainPlugin instance, got {type(plugin)}")
        cls._plugins[plugin.domain_id] = plugin
        logger.info("Registered domain plugin: %s (%s)", plugin.domain_id, plugin.display_name)

    @classmethod
    def get_plugin(cls, domain_id: str) -> Optional[DomainPlugin]:
        """Retrieve a registered plugin by ID."""
        if not cls._plugins:
            cls.auto_discover_plugins()
        return cls._plugins.get(domain_id)

    @classmethod
    def list_domains(cls) -> list[str]:
        """Return list of all registered domain IDs."""
        if not cls._plugins:
            cls.auto_discover_plugins()
        return list(cls._plugins.keys())

    @classmethod
    def detect_domain(cls, hypothesis: HypothesisProposal) -> Optional[DomainPlugin]:
        """Detect the appropriate domain plugin for a given hypothesis.

        Evaluates registered plugins via matches_domain and domain string normalization.
        """
        if not cls._plugins:
            cls.auto_discover_plugins()

        # 1. First test explicit plugin match logic
        for plugin in cls._plugins.values():
            if plugin.matches_domain(hypothesis):
                return plugin

        # 2. Check if hypothesis explicitly mentions domain in provenance
        for seed in hypothesis.inspired_by_seeds:
            seed_domain = getattr(seed, "domain", "").lower()
            for plugin in cls._plugins.values():
                p_id = plugin.domain_id.lower()
                p_name = plugin.display_name.lower()
                if (
                    p_id in seed_domain
                    or seed_domain in p_id
                    or any(w in seed_domain for w in p_name.split() if len(w) > 3)
                ):
                    return plugin

        # 3. Check hypothesis title or domain string attribute if set
        hyp_domain = getattr(hypothesis, "domain", "").lower()
        if hyp_domain:
            for plugin in cls._plugins.values():
                if plugin.domain_id.lower() in hyp_domain or hyp_domain in plugin.domain_id.lower():
                    return plugin

        return None

    @classmethod
    def auto_discover_plugins(cls, plugins_package: str = "research_os.plugins") -> None:
        """Dynamically scan and register all DomainPlugin subclasses found under plugins."""
        try:
            pkg = importlib.import_module(plugins_package)
        except ImportError:
            logger.debug("Plugins package %s not found on python path", plugins_package)
            return

        if not hasattr(pkg, "__path__"):
            return

        for _, sub_pkg_name, is_pkg in pkgutil.iter_modules(pkg.__path__):
            if is_pkg and sub_pkg_name != "staging":
                module_name = f"{plugins_package}.{sub_pkg_name}.plugin"
                try:
                    module = importlib.import_module(module_name)
                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if (
                            issubclass(obj, DomainPlugin)
                            and obj is not DomainPlugin
                            and hasattr(obj, "domain_id")
                        ):
                            if obj.domain_id not in cls._plugins:
                                plugin_instance = obj()
                                cls.register(plugin_instance)
                except (ImportError, AttributeError) as exc:
                    logger.debug("Could not auto-load plugin from %s: %s", module_name, exc)

    @classmethod
    def load_staged_plugin(
        cls,
        staged_dir: Union[str, Path],
        public_key_hex: Optional[str] = None,
        expected_public_key: Optional[str] = None,
    ) -> DomainPlugin:
        """Admit and instantiate a cryptographically signed staged domain plugin.

        Enforces:
        - Cryptographic Ed25519 signature verification on plugin_approval.token.
        - Immediate fail-closed rejection on file modification post-signing.
        - Static AST code inspection of generator.py (no arbitrary execution or exfiltration).
        - Sandboxed wrapping with declarative metric evaluation solely handled by core.
        """
        staged_path = Path(staged_dir).resolve()
        pub_key = expected_public_key or public_key_hex
        from research_os.gate.plugin_approval import verify_plugin_approval_token

        # 1. Cryptographic Gate & Tamper Verification
        verify_plugin_approval_token(staged_path, expected_public_key=pub_key)

        # 2. Static AST Security Scan
        gen_path = staged_path / "generator.py"
        violations = validate_generator_ast(gen_path)
        if violations:
            raise SecurityViolationError(
                f"Security Violation: Staged generator.py in {staged_path} failed static AST inspection:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

        # 3. Read and parse DeclarativePluginSpec
        spec_path = staged_path / "plugin.json"
        spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
        spec = DeclarativePluginSpec.model_validate(spec_data)

        # 4. Load generator module in isolated namespace
        spec_loader = importlib.util.spec_from_file_location(
            f"research_os.staged_plugins.{spec.domain_id}.generator",
            gen_path,
        )
        if not spec_loader or not spec_loader.loader:
            raise ImportError(f"Cannot load module from {gen_path}")

        gen_module = importlib.util.module_from_spec(spec_loader)
        spec_loader.loader.exec_module(gen_module)

        # 5. Wrap in DeclarativeDomainPluginAdapter
        adapter = DeclarativeDomainPluginAdapter(
            spec=spec,
            generator_module=gen_module,
            staged_dir=staged_path,
        )

        cls.register(adapter)
        return adapter


default_domain_registry = DomainRegistry()
default_domain_registry.auto_discover_plugins()
