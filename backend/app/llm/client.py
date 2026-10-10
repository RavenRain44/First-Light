from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx


class LLMClient(ABC):
    model: str

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise RuntimeError("Embedding inference is not configured")


class AkamaiLLMClient(LLMClient):
    """OpenAI-compatible client for the Akamai-hosted organizer endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            body["response_format"] = response_format
        if tools:
            body["tools"] = tools
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"].get("content")
        if not content:
            raise RuntimeError(f"Inference response did not contain text: {json.dumps(data)[:500]}")
        return content

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": texts},
            )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda item: item["index"])
        return [[float(value) for value in row["embedding"]] for row in rows]


class UnavailableLLMClient(LLMClient):
    model = "template-fallback"

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise RuntimeError("Akamai inference is not configured")
