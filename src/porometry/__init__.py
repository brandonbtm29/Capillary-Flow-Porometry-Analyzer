"""Capillary Flow Porometry Analyzer: read and analyze PMI CapWin capillary flow porometry (.CFT) files."""

from .analysis import Analysis, Settings, analyze
from .cft import PSI_TO_KPA, Run, read_cft
from .qc import Level, QCSettings, check
from .workspace import Workspace

__version__ = "0.7.0"  # single source of the version: pyproject.toml reads it; see CHANGELOG.md
__all__ = ["Analysis", "Settings", "analyze", "PSI_TO_KPA", "Run", "read_cft", "Level", "QCSettings", "check",
           "Workspace"]
