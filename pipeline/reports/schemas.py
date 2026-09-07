"""
Shared report data shapes.

Every modality integrator returns a ReportContext.
The renderer consumes a ReportContext + a YAML template.
This is the contract between the two halves of the pipeline.
"""

from dataclasses import dataclass, field
from typing import Literal


Status = Literal['WNL', 'BRDL', 'ABNL']


@dataclass
class Finding:
    """One row of a clinical results table (e.g. one ERG parameter)."""
    parameter: str
    od_value: str
    od_status: Status
    os_value: str
    os_status: Status


@dataclass
class InterpretationSection:
    """One labeled paragraph in the Interpretation block."""
    label: str
    text: str


@dataclass
class ReportContext:
    """
    Everything needed to render a clinical report, regardless of modality.

    Integrators populate this. The renderer reads it.
    """
    modality: str

    # Key/value blocks rendered as two-column tables
    patient: list[tuple[str, str]] = field(default_factory=list)
    device: list[tuple[str, str]] = field(default_factory=list)
    attestation: list[tuple[str, str]] = field(default_factory=list)

    # Color-coded clinical results
    findings: list[Finding] = field(default_factory=list)

    # Narrative interpretation (typically LLM-generated with RAG context)
    interpretation: list[InterpretationSection] = field(default_factory=list)

    # Free-text assessment & plan box
    assessment_plan: str = ''

    # Provenance — RAG sources used to generate the interpretation
    citations: list[str] = field(default_factory=list)

    # Confidence score from the integrator (0.0–1.0)
    confidence: float = 0.0
