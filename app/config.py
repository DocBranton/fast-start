"""Runtime configuration, read from environment variables."""
import os

# Default chat endpoints on the Databricks workspace (system.ai).
# databricks-genie is intentionally excluded: it is a Genie space, not a chat endpoint.
DEFAULT_MODELS = [
    "gpt-5-6-terra",
    "gpt-5-6-luna",
    "gpt-5-4",
    "gemini-3-8-flash",
    "gemini-3-7-flash",
    "gemini-3-6-flash",
    "gemini-3-5-flash",
    "gemini-3-5-flash-lite",
    "grok-4-6",
]


def _list(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


class Settings:
    def __init__(self) -> None:
        host = os.getenv("DATABRICKS_HOST", "").strip().rstrip("/")
        if host and not host.startswith("http"):
            host = "https://" + host
        self.databricks_host = host
        # Auth option 1: personal access token / service principal token
        self.databricks_token = os.getenv("DATABRICKS_TOKEN", "").strip()
        # Auth option 2: OAuth machine-to-machine (service principal)
        self.client_id = os.getenv("DATABRICKS_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("DATABRICKS_CLIENT_SECRET", "").strip()

        # Comma-separated allowlist shown in the model picker.
        self.models = _list(os.getenv("WINGMAN_MODELS")) or DEFAULT_MODELS
        self.default_model = os.getenv("WINGMAN_DEFAULT_MODEL", "").strip() or self.models[0]
        # true = ask Databricks which allowlisted endpoints are actually READY
        self.discover_models = os.getenv("WINGMAN_DISCOVER_MODELS", "true").lower() == "true"

        self.max_tokens = int(os.getenv("WINGMAN_MAX_TOKENS", "1024"))
        self.temperature = float(os.getenv("WINGMAN_TEMPERATURE", "0.3"))
        self.request_timeout = float(os.getenv("WINGMAN_TIMEOUT_SECONDS", "120"))
        self.system_prompt = os.getenv(
            "WINGMAN_SYSTEM_PROMPT",
            "You are Wingman, the AI assistant inside the Global Mission Workbench, a "
            "sustainment tool that connects mission demand to organic, partner and "
            "industrial capabilities. Be concise and practical. If you are unsure, say "
            "so. Do not invent part numbers, tail numbers or data you were not given.",
        )
        # Force canned responses (useful for pipeline smoke tests with no model access).
        self.mock = os.getenv("WINGMAN_MOCK", "").lower() == "true" or not host
        self.app_version = os.getenv("APP_VERSION", "dev")

    @property
    def auth_mode(self) -> str:
        if self.mock:
            return "mock"
        if self.databricks_token:
            return "token"
        if self.client_id and self.client_secret:
            return "oauth-m2m"
        return "none"


settings = Settings()
