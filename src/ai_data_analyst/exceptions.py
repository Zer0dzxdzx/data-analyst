"""Domain exceptions for the analysis workflow."""


class AnalysisError(Exception):
    """Base error raised for expected analysis failures."""


class DataLoadError(AnalysisError):
    """Raised when a CSV cannot be loaded into a valid dataframe."""


class ConfigurationError(AnalysisError):
    """Raised when caller-provided configuration is invalid."""
