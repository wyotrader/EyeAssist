"""
Base class for modality integrators.

An integrator's job:
  1. Take vision-service output (structured findings extracted from
     the rasterized PDF)
  2. Compare values against normative data
  3. Flag findings as WNL / BRDL / ABNL
  4. Call the LLM (via the orchestrator) with RAG context from the
     appropriate subspecialty collection to generate interpretation prose
  5. Return a populated ReportContext

Subclasses implement build_context(). Everything else is shared.
"""

from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from ..schemas import ReportContext


TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'


class Integrator(ABC):
    """Base class — one subclass per modality."""

    modality: str = ''
    template_filename: str = ''

    def __init__(self, llm_client=None, rag_client=None):
        """
        llm_client: handle for calling Gemma 4 via the orchestrator/Ollama
        rag_client: handle for querying the appropriate ChromaDB collection

        Both are injected so integrators are testable in isolation
        (pass mocks in tests, real clients in production).
        """
        self.llm = llm_client
        self.rag = rag_client
        self._template = None

    @property
    def template(self) -> dict:
        """Lazy-load the YAML template for this modality."""
        if self._template is None:
            path = TEMPLATES_DIR / self.template_filename
            with open(path) as f:
                self._template = yaml.safe_load(f)
        return self._template

    @property
    def template_path(self) -> Path:
        return TEMPLATES_DIR / self.template_filename

    @property
    def rag_collections(self) -> list[str]:
        """
        List of RAG collections this modality should query.
        Templates may specify either:
          rag_collections: [retina, neuro, general]   # preferred, explicit list
          rag_collection: retina                      # legacy single-collection
        """
        plural = self.template.get('rag_collections')
        if plural:
            return list(plural)
        single = self.template.get('rag_collection', 'general')
        return [single]

    @property
    def rag_collection(self):
        """Backwards-compat — returns the first collection or the full list."""
        cols = self.rag_collections
        return cols[0] if len(cols) == 1 else cols

    @abstractmethod
    def build_context(self, vision_output: dict, patient_meta: dict) -> ReportContext:
        """
        Build a fully populated ReportContext from vision output.

        vision_output: structured dict from eyeassist-vision (parsed
                       values, percentiles, raw text, etc.)
        patient_meta:  patient identifying info (name, DOB, MRN, etc.)
        """
        ...
