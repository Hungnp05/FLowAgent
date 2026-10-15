class FlowAgentError(Exception):
    pass


class TaskNotFoundError(FlowAgentError, LookupError):
    pass


class ProjectNotFoundError(FlowAgentError, LookupError):
    pass


class EventNotFoundError(FlowAgentError, LookupError):
    pass


class ProjectExistsError(FlowAgentError, ValueError):
    pass


class InvalidScheduleError(FlowAgentError, ValueError):
    pass


class InvalidDateError(FlowAgentError, ValueError):
    pass


class MissingApiKeyError(FlowAgentError):
    pass


class InvalidPinError(FlowAgentError, ValueError):
    pass


class SecretDecryptionError(FlowAgentError):
    pass


class ModelArtifactError(FlowAgentError):
    pass


class PriorityModelUnavailableError(FlowAgentError):
    pass


class NoChangesError(FlowAgentError, ValueError):
    pass


class MemoryNotFoundError(FlowAgentError, LookupError):
    pass
