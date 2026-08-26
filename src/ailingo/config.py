"""User configuration: LLM model, API keys, sources, practice settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from .paths import config_path


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    prefix: str
    env_var: str | None
    suggested_models: tuple[str, ...]
    key_url: str
    blurb: str

    @property
    def default_model(self) -> str:
        return f"{self.prefix}:{self.suggested_models[0]}"


PROVIDERS: dict[str, ProviderInfo] = {
    # Suggested models: the balanced mid-tier model of each provider first (that's the
    # default), then the cheap tier, then the flagship. Verified against the provider
    # docs in August 2026; any other id the provider accepts works too.
    "openai": ProviderInfo(
        id="openai",
        label="OpenAI",
        prefix="openai",
        env_var="OPENAI_API_KEY",
        suggested_models=("gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.4-mini"),
        key_url="https://platform.openai.com/api-keys",
        blurb="GPT-5.6 Terra is the balanced default; Luna is the cheap one.",
    ),
    "anthropic": ProviderInfo(
        id="anthropic",
        label="Anthropic",
        prefix="anthropic",
        env_var="ANTHROPIC_API_KEY",
        suggested_models=("claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5", "claude-fable-5"),
        key_url="https://console.anthropic.com/settings/keys",
        blurb="Claude Sonnet 5 is the sweet spot; Haiku 4.5 if you want it cheap.",
    ),
    "google": ProviderInfo(
        id="google",
        label="Google Gemini",
        prefix="google",
        env_var="GOOGLE_API_KEY",
        suggested_models=("gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.1-pro-preview"),
        key_url="https://aistudio.google.com/app/apikey",
        blurb="Gemini 3.7 Flash is the current workhorse and very cheap.",
    ),
    "openrouter": ProviderInfo(
        id="openrouter",
        label="OpenRouter",
        prefix="openrouter",
        env_var="OPENROUTER_API_KEY",
        suggested_models=(
            "openai/gpt-5.6-terra",
            "anthropic/claude-sonnet-5",
            "google/gemini-3.7-flash",
            "openai/gpt-5.6-luna",
        ),
        key_url="https://openrouter.ai/keys",
        blurb="One key, every model. Use the 'vendor/model' naming.",
    ),
    "custom": ProviderInfo(
        id="custom",
        label="Other (any Pydantic AI model id)",
        prefix="",
        env_var=None,
        suggested_models=("groq:llama-3.3-70b-versatile", "mistral:mistral-large-latest"),
        key_url="https://ai.pydantic.dev/models/",
        blurb="Any 'provider:model' identifier that Pydantic AI understands.",
    ),
}

# env var each pydantic-ai provider prefix reads its key from
PREFIX_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai-chat": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "google-gla": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "cohere": "CO_API_KEY",
    "xai": "XAI_API_KEY",
    "huggingface": "HF_TOKEN",
    "cerebras": "CEREBRAS_API_KEY",
    "moonshotai": "MOONSHOTAI_API_KEY",
}


def model_prefix(model_id: str) -> str:
    return model_id.split(":", 1)[0] if ":" in model_id else ""


def env_var_for_model(model_id: str) -> str | None:
    return PREFIX_ENV_VARS.get(model_prefix(model_id))


def provider_for_model(model_id: str) -> ProviderInfo:
    prefix = model_prefix(model_id)
    for info in PROVIDERS.values():
        if info.prefix and info.prefix == prefix:
            return info
    return PROVIDERS["custom"]


class Config(BaseModel):
    model: str | None = None
    api_keys: dict[str, str] = Field(default_factory=dict)  # env var name -> key
    sources: dict[str, bool] = Field(
        default_factory=lambda: {"codex": True, "claude_code": True, "opencode": True}
    )
    exercises_per_session: int = 6
    max_prompts_per_run: int = 300
    auto_analyze: bool = True
    analysis_interval_days: int = 7
    notifications_enabled: bool = False
    notification_time: str = "18:00"
    user_name: str = ""
    onboarded: bool = False

    def source_enabled(self, name: str) -> bool:
        return self.sources.get(name, True)

    def apply_api_keys_to_env(self) -> None:
        """Expose stored keys to pydantic-ai without overriding a real environment."""
        for env_var, key in self.api_keys.items():
            if key and not os.environ.get(env_var):
                os.environ[env_var] = key

    def has_key_for(self, model_id: str) -> bool:
        env_var = env_var_for_model(model_id)
        if env_var is None:
            return True  # unknown provider: assume it's configured out of band
        return bool(os.environ.get(env_var) or self.api_keys.get(env_var))


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    try:
        data: dict[str, Any] = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return Config()
    try:
        cfg = Config.model_validate(data)
    except Exception:
        cfg = Config()
    cfg.apply_api_keys_to_env()
    return cfg


def save_config(cfg: Config) -> None:
    path = config_path()
    path.write_text(json.dumps(cfg.model_dump(), indent=2) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    cfg.apply_api_keys_to_env()
