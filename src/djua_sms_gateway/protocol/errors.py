"""Protocol-specific exceptions."""


class ProtocolError(ValueError):
    """Base class for deterministic protocol errors."""


class D1ParseError(ProtocolError):
    """Raised when a raw SMS cannot be parsed as a D1 message."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        prefix = f"{field}: " if field else ""
        super().__init__(f"{code}: {prefix}{message}")


class NormalizationError(ProtocolError):
    """Raised when invalid telemetry cannot be normalized safely."""
