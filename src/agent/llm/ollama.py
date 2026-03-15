from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from agent.config.loader import Config

logger = logging.getLogger(__name__)

_FORMAT_REMINDER = """\
Respond with a JSON object. Required fields: "thought" (one or two sentences of internal reasoning) and "actions" (array of tool calls). Every chain MUST end with a "finish" action.

Example (tool call then finish):
{"thought": "I need to check the weather first.", "actions": [{"type": "get_weather", "payload": {}}, {"type": "finish", "payload": {}}]}

Example (direct answer):
{"thought": "I know the answer from context.", "actions": [{"type": "send_message", "payload": {"content": "The ship is MV Ortelius."}}, {"type": "finish", "payload": {}}]}"""


class OllamaClient:
    def __init__(self, config: Config) -> None:
        self._model = config.agent.model
        self._temperature = config.agent.temperature
        self._max_tokens = config.agent.max_tokens
        self._base_url = config.photo_pipeline.ollama_url

    async def ainvoke(
        self, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> dict:
        # Extract the JSON schema from RESPONSE_FORMAT and pass it to Ollama
        # for native structured output enforcement.
        schema = response_format.get("json_schema", {}).get("schema", None)

        # Inject the format reminder before the final generation step.
        # Always appended as a user message so it works at any chain depth,
        # including after tool results (which arrive as role="tool").
        augmented = list(messages)
        augmented.append({"role": "user", "content": _FORMAT_REMINDER})

        body: dict[str, Any] = {
            "model": self._model,
            "messages": augmented,
            "stream": False,
            "format": schema if schema else "json",
            "options": {"temperature": self._temperature, "num_predict": self._max_tokens, "num_ctx": 8192},
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=body,
                timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
            )
            resp.raise_for_status()

        data = resp.json()
        content = data["message"]["content"]

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Ollama returned invalid JSON: %s", exc)
            result = {
                "actions": [
                    {
                        "type": "send_message",
                        "payload": {"content": "Sorry, I had trouble processing that. Could you repeat?"},
                    }
                ]
            }

        result["_usage"] = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return result
