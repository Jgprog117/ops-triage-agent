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
    """LLM returned a malformed or unparseable response."""

    def __init__(self, message: str, raw_response: dict | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class LLMTimeoutError(LLMError):
    """LLM API call timed out after exhausting retries."""


# -- Tool errors ---------------------------------------------------------------

class ToolExecutionError(TriageAgentError):
    """A tool call failed during triage.

    severity: "transient" (retry may help), "degraded" (partial result),
              "fatal" (unrecoverable — bad data, DB down, bug).
    """

    def __init__(self, message: str, severity: str = "transient"):
        super().__init__(message)
        self.severity = severity


# -- Webhook errors ------------------------------------------------------------

class WebhookDeliveryError(TriageAgentError):
    """Webhook delivery failed after all retry attempts."""


# -- Config errors -------------------------------------------------------------

class ConfigurationError(TriageAgentError):
    """Startup configuration is invalid or missing required values."""


# -- Parse errors --------------------------------------------------------------

class ParseError(TriageAgentError):
    """Failed to parse JSON from LLM output.

    Attaches the raw content for debugging.
    """

    def __init__(self, message: str, raw_content: str | None = None):
        super().__init__(message)
        self.raw_content = raw_content
