"""Typed exception hierarchy for the Ops Triage Agent."""


class TriageAgentError(Exception):
    """Base exception for the triage agent."""


# -- LLM errors ---------------------------------------------------------------

class LLMError(TriageAgentError):
    """Base for LLM-layer failures."""


class LLMRateLimitError(LLMError):
    """LLM API returned 429 after exhausting retries."""


class LLMServerError(LLMError):
    """LLM API returned a 5xx status after exhausting retries."""


class LLMResponseError(LLMError):
    """LLM returned a malformed or unparseable response.

    Attributes:
        raw_response: The decoded JSON body of the offending response, when
            available, for debugging.
    """

    def __init__(self, message: str, raw_response: dict | None = None) -> None:
        """Inits LLMResponseError with the failure message and raw payload.

        Args:
            message: Human-readable description of the failure.
            raw_response: The decoded LLM response body, if any.
        """
        super().__init__(message)
        self.raw_response = raw_response


class LLMTimeoutError(LLMError):
    """LLM API call timed out after exhausting retries."""


# -- Config errors -------------------------------------------------------------

class ConfigurationError(TriageAgentError):
    """Startup configuration is invalid or missing required values."""


# -- Parse errors --------------------------------------------------------------

class ParseError(TriageAgentError):
    """Failed to parse JSON from LLM output.

    Attributes:
        raw_content: The raw LLM text that failed to parse, retained so the
            caller can log or surface it for debugging.
    """

    def __init__(self, message: str, raw_content: str | None = None) -> None:
        """Inits ParseError with the failure message and the raw LLM text.

        Args:
            message: Human-readable description of the parse failure.
            raw_content: The original LLM text that could not be parsed.
        """
        super().__init__(message)
        self.raw_content = raw_content
