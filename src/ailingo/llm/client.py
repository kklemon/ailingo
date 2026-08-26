"""Pydantic AI plumbing: build a model from an identifier and create typed agents."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings

from ..config import Config, env_var_for_model
from . import prompts


class LLMError(RuntimeError):
    """A user-facing error about the LLM configuration or call."""


def resolve_model(config: Config, model_id: str | None = None) -> str:
    model = model_id or config.model
    if not model:
        raise LLMError("No model configured. Run the onboarding or set one in Settings.")
    if ":" not in model:
        raise LLMError(f"'{model}' is not a Pydantic AI model id. Expected 'provider:model', e.g. openai:gpt-5.6-terra.")
    return model


def build_model(config: Config, model_id: str | None = None) -> Model:
    model = resolve_model(config, model_id)
    config.apply_api_keys_to_env()
    env_var = env_var_for_model(model)
    if env_var and not os.environ.get(env_var):
        raise LLMError(f"Missing API key: set {env_var} or enter it in Settings.")
    try:
        return infer_model(model)
    except Exception as exc:  # pydantic_ai.exceptions.UserError and friends
        raise LLMError(f"Could not create model '{model}': {exc}") from exc


def default_settings(model: Model | None = None, *, fast: bool = False) -> ModelSettings:
    """Keep calls snappy: this is editing work, not theorem proving."""
    settings: dict[str, Any] = {"timeout": 180}
    system = getattr(model, "system", "") if model is not None else ""
    name = str(getattr(model, "model_name", "") or "")
    if system == "openai":
        # 'low' is accepted by every reasoning model from gpt-5 to gpt-5.6; 'minimal'
        # (gpt-5) and 'none' (gpt-5.1+) are not universally supported, so don't bother.
        settings["openai_reasoning_effort"] = "low"
    elif system == "google":
        if name.startswith("gemini-2"):
            settings["google_thinking_config"] = {"thinking_budget": 0 if fast else 1024}
        else:
            # Gemini 3.x uses thinking_level; 'low' is the smallest level 3.7 Flash accepts.
            settings["google_thinking_config"] = {"thinking_level": "low"}
    return ModelSettings(**settings)  # type: ignore[typeddict-item]


def make_agent(
    model: Model, output_type: type[Any], instructions: str, retries: int = 2, *, fast: bool = False
) -> Agent[None, Any]:
    return Agent(
        model,
        output_type=output_type,
        instructions=instructions,
        retries=retries,
        model_settings=default_settings(model, fast=fast),
    )


async def test_connection(config: Config, model_id: str | None = None) -> str:
    """Make one tiny request. Returns the model's reply text or raises LLMError."""
    model = build_model(config, model_id)
    agent: Agent[None, str] = Agent(model, model_settings=ModelSettings(timeout=60))
    try:
        result = await asyncio.wait_for(agent.run(prompts.CONNECTION_TEST), timeout=75)
    except TimeoutError as exc:
        raise LLMError("The model did not answer within 75 seconds.") from exc
    except Exception as exc:
        raise LLMError(_humanize(exc)) from exc
    return str(result.output).strip()


def _humanize(exc: Exception) -> str:
    text = str(exc)
    status = getattr(exc, "status_code", None)
    if status == 401 or "401" in text or "invalid_api_key" in text.lower() or "authentication" in text.lower():
        return "Authentication failed — the API key was rejected."
    if status == 404 or "404" in text or "not found" in text.lower() or "does not exist" in text.lower():
        return f"The model was not found by the provider. ({text[:160]})"
    if status == 429 or "429" in text:
        return "Rate limited or out of credits (HTTP 429)."
    return f"{type(exc).__name__}: {text[:300]}"


def humanize_error(exc: Exception) -> str:
    if isinstance(exc, LLMError):
        return str(exc)
    return _humanize(exc)
