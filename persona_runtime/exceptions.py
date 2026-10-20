"""Domain-specific exceptions."""


class PersonaRuntimeError(Exception):
    """Base error for the persona runtime."""


class ConfigurationError(PersonaRuntimeError):
    """Required configuration is missing or invalid."""


class DatabaseError(PersonaRuntimeError):
    """MongoDB operation failed."""


class PersonaNotFoundError(PersonaRuntimeError):
    """Persona identity could not be resolved."""


class IngestionError(PersonaRuntimeError):
    """Persona markdown ingestion failed."""


class SubcategoryConflictError(PersonaRuntimeError):
    """Generated subcategory conflicts with canonical facts."""


class LLMError(PersonaRuntimeError):
    """OpenAI / structured LLM call failed."""


class StructuredOutputError(LLMError):
    """LLM returned invalid structured output."""


class ConversationError(PersonaRuntimeError):
    """Conversation operation failed."""


class MemoryRetrievalError(PersonaRuntimeError):
    """Memory retrieval failed; callers must not fabricate memories."""
