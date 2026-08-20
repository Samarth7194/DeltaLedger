from __future__ import annotations

import json
import time
from typing import Any, TypeVar

import anyio
import httpx
from pydantic import BaseModel, ValidationError

from app.ai.inference import InferenceMetadata, metadata_from_usage
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleClient:
    provider = "openai_compatible"

    def __init__(self, settings: Settings, *, provider_type: str) -> None:
        if not settings.ai_provider_api_key:
            raise DeltaLedgerError(
                "AI_PROVIDER_API_KEY is required for openai_compatible providers."
            )
        self.provider_type = provider_type
        self.base_url = settings.ai_provider_base_url.rstrip("/")
        self.timeout = settings.ai_provider_timeout_seconds
        self.max_retries = settings.ai_provider_max_retries
        self.input_cost_per_million = settings.ai_provider_input_token_cost_usd_per_million
        self.output_cost_per_million = settings.ai_provider_output_token_cost_usd_per_million
        self.headers = {
            "Authorization": f"Bearer {settings.ai_provider_api_key}",
            "Content-Type": "application/json",
        }

    async def embeddings(
        self,
        *,
        model: str,
        inputs: list[str],
        dimensions: int,
    ) -> tuple[list[list[float]], InferenceMetadata]:
        started = time.perf_counter()
        response, retry_count = await self._post(
            "/embeddings",
            {"model": model, "input": inputs, "dimensions": dimensions},
        )
        try:
            vectors = [
                [float(value) for value in item["embedding"]]
                for item in sorted(response["data"], key=lambda row: row.get("index", 0))
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise DeltaLedgerError("OpenAI-compatible embedding response was invalid.") from exc
        metadata = metadata_from_usage(
            provider=self.provider,
            provider_type=self.provider_type,
            model=model,
            model_version=(
                response.get("model") if isinstance(response.get("model"), str) else model
            ),
            prompt_version=None,
            latency_ms=(time.perf_counter() - started) * 1000,
            success=True,
            parse_status="valid",
            retry_count=retry_count,
            usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
        )
        return vectors, metadata

    async def chat_json(
        self,
        *,
        model: str,
        prompt_version: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_model: type[T],
    ) -> tuple[T, InferenceMetadata, dict[str, Any]]:
        started = time.perf_counter()
        response, retry_count = await self._post(
            "/chat/completions",
            {
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, sort_keys=True, default=str),
                    },
                ],
            },
        )
        raw_content = _message_content(response)
        try:
            parsed_payload = json.loads(raw_content)
            parsed = response_model.model_validate(parsed_payload)
            parse_status = "valid"
            error_type = None
        except (json.JSONDecodeError, ValidationError) as exc:
            metadata = metadata_from_usage(
                provider=self.provider,
                provider_type=self.provider_type,
                model=model,
                model_version=_response_model_name(response, model),
                prompt_version=prompt_version,
                latency_ms=(time.perf_counter() - started) * 1000,
                success=False,
                parse_status="invalid",
                retry_count=retry_count,
                usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
                input_cost_per_million=self.input_cost_per_million,
                output_cost_per_million=self.output_cost_per_million,
                error_type=exc.__class__.__name__,
            )
            raise StructuredOutputError(
                "Provider returned invalid structured output.",
                metadata,
            ) from exc
        metadata = metadata_from_usage(
            provider=self.provider,
            provider_type=self.provider_type,
            model=model,
            model_version=_response_model_name(response, model),
            prompt_version=prompt_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            success=True,
            parse_status=parse_status,
            retry_count=retry_count,
            usage=response.get("usage") if isinstance(response.get("usage"), dict) else None,
            input_cost_per_million=self.input_cost_per_million,
            output_cost_per_million=self.output_cost_per_million,
            error_type=error_type,
        )
        return parsed, metadata, response

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}{path}",
                        headers=self.headers,
                        json=payload,
                    )
                if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
                    last_error = DeltaLedgerError(
                        f"OpenAI-compatible provider returned status {response.status_code}."
                    )
                    if attempt < self.max_retries - 1:
                        await anyio.sleep(min(8.0, 2.0**attempt))
                        continue
                response.raise_for_status()
                return response.json(), attempt
            except (httpx.HTTPError, ValueError, DeltaLedgerError) as exc:
                last_error = exc
                if attempt >= self.max_retries - 1:
                    break
                await anyio.sleep(min(8.0, 2.0**attempt))
        message = last_error.__class__.__name__ if last_error else "Unknown provider error"
        raise DeltaLedgerError(f"OpenAI-compatible provider request failed: {message}")


class StructuredOutputError(DeltaLedgerError):
    def __init__(self, message: str, metadata: InferenceMetadata) -> None:
        super().__init__(message)
        self.metadata = metadata


def _message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeltaLedgerError(
            "OpenAI-compatible chat response was missing message content."
        ) from exc
    if not isinstance(content, str):
        raise DeltaLedgerError("OpenAI-compatible chat response content was not a string.")
    return content


def _response_model_name(response: dict[str, Any], fallback: str) -> str:
    model = response.get("model")
    return model if isinstance(model, str) and model else fallback
