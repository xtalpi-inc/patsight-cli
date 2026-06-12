class ClientError(Exception):
    """Base error for remote job clients."""


class ConfigError(ClientError):
    """Invalid configuration file or profile."""


class LoginError(ClientError):
    """Authentication failed."""


class SubmitError(ClientError):
    """Job submission failed."""


class QueryError(ClientError):
    """Status query failed."""


class FetchResultError(ClientError):
    """Result fetch failed."""


class ExportError(ClientError):
    """Export type/format is invalid for the job."""


class JobNotFoundError(ClientError):
    """Job does not exist or is not visible."""


class RegistryError(ClientError):
    """Unknown or duplicate client type in registry."""
