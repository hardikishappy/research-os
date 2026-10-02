"""Runtime and static verification engine for anti-fabrication invariants in Research OS.

Enforces that any domain declaring real-world physical, biological, neural, or chemical
properties must bind to authentic empirical records or recognized domain numerical engines
(e.g., scipy, torch, rdkit, mne) rather than mocking state transitions with pure PRNG.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Optional, Union

from research_os.core.integrity import EpistemicHonestyViolation


EMPIRICAL_PROPERTIES_DOMAINS = {
    "physical",
    "physics",
    "biological",
    "biology",
    "biotech",
    "neurotech",
    "neuroscience",
    "neural",
    "defense",
    "chemistry",
    "molecular",
    "eeg",
    "electrophysiology",
}

RECOGNIZED_NUMERICAL_ENGINES = {
    "scipy",
    "torch",
    "rdkit",
    "mne",
    "biopython",
    "Bio",
    "openmm",
    "qiskit",
    "sklearn",
}

DISALLOWED_PRNG_CALLS = {
    ("random", "random"),
    ("random", "uniform"),
    ("random", "gauss"),
    ("random", "normalvariate"),
    ("np.random", "normal"),
    ("np.random", "random"),
    ("np.random", "rand"),
    ("np.random", "randn"),
    ("numpy.random", "normal"),
    ("numpy.random", "random"),
    ("numpy.random", "rand"),
    ("numpy.random", "randn"),
}


def is_empirical_property_domain(domain_str: Optional[str]) -> bool:
    """Check if the declared domain asserts real-world physical, biological, or neural properties."""
    if not domain_str:
        return False
    lower_dom = domain_str.lower()
    return any(keyword in lower_dom for keyword in EMPIRICAL_PROPERTIES_DOMAINS)


def verify_anti_fabrication(
    code_source: Union[str, Path],
    domain: Optional[str] = None,
    allow_simulation_prng: bool = False,
) -> None:
    """Inspect runner code AST for disallowed pure-PRNG state transition mocking.
    
    Raises EpistemicHonestyViolation if a domain declaring physical, biological, or neural properties
    uses pure pseudo-random generation instead of verified data bindings or recognized solvers.
    """
    if not is_empirical_property_domain(domain):
        return

    if allow_simulation_prng:
        return

    if isinstance(code_source, Path):
        source = code_source.read_text(encoding="utf-8", errors="replace")
    else:
        source = str(code_source)

    try:
        tree = ast.parse(source)
    except Exception:
        # Syntax issues handled by runner sandbox parser
        return

    imported_modules: set[str] = set()
    prng_calls_found: list[str] = []
    has_data_binding: bool = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

        # Check for empirical data loading calls
        elif isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                val_name = ""
                if isinstance(node.func.value, ast.Name):
                    val_name = node.func.value.id
                elif isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    val_name = f"{node.func.value.value.id}.{node.func.value.attr}"
                func_name = f"{val_name}.{node.func.attr}" if val_name else node.func.attr

            # Detect recognized data binding methods
            if any(term in func_name.lower() for term in ["read_csv", "load", "from_file", "read_raw", "parse_fasta", "read_pdb"]):
                has_data_binding = True

            # Detect PRNG transition calls
            for mod_prefix, call_attr in DISALLOWED_PRNG_CALLS:
                if func_name == f"{mod_prefix}.{call_attr}" or (mod_prefix == "random" and func_name == call_attr):
                    prng_calls_found.append(func_name)

    # Check if recognized numerical solver engine is imported
    has_recognized_engine = bool(imported_modules.intersection(RECOGNIZED_NUMERICAL_ENGINES))

    if prng_calls_found and not (has_recognized_engine or has_data_binding):
        offending_calls = ", ".join(sorted(set(prng_calls_found)))
        raise EpistemicHonestyViolation(
            f"AntiFabricationViolation: Domain '{domain}' declares real-world physical, biological, or neural properties, "
            f"but runner code attempts to mock state transitions with pure PRNG ({offending_calls}) without binding "
            f"to authentic empirical records or recognized numerical engines ({', '.join(sorted(RECOGNIZED_NUMERICAL_ENGINES))})."
        )
