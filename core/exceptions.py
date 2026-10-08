"""Application-specific exceptions with user-readable messages."""
from __future__ import annotations


class WorkbenchError(Exception):
    """Base class. ``str(exc)`` is safe to show to the user; technical detail goes to the log."""


class HdfStructureError(WorkbenchError):
    """The HEC-RAS HDF file does not contain an expected structure."""


class MissingVariableError(WorkbenchError):
    """A requested HEC-RAS result variable is not present in the file."""


class UnitError(WorkbenchError):
    """A unit string is unknown or a conversion is dimensionally invalid."""


class ObservationError(WorkbenchError):
    """Observation download, parsing or cache failure."""


class ProviderError(ObservationError):
    """A remote data provider returned an error or unusable payload."""


class CacheError(ObservationError):
    """The local observation cache is unreadable or inconsistent."""


class AnalysisError(WorkbenchError):
    """An analysis could not be computed with the supplied data."""
