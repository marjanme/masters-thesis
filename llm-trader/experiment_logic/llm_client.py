import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol
from urllib import error, request

from experiment_logic.types import ConversationMessage


STRUCTURED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "probability_yes": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["reasoning", "probability_yes"],
}


class LLMClient(Protocol):
    def generate_response(self, complete_conversation: list[ConversationMessage]) -> str:
        ...


class MockLLMClient:
    def generate_response(self, complete_conversation: list[ConversationMessage]) -> str:
        response_object = {
            "reasoning": "Deterministic mock response for pipeline testing.",
            "probability_yes": 0.5,
        }
        return json.dumps(response_object)


class OllamaLLMClient:
    def __init__(self, model_name: str, ollama_base_url: str, timeout_seconds: int) -> None:
        self.model_name = model_name
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.debug_output_dir: Optional[Path] = None

    def set_debug_output_dir(self, debug_output_dir: Path) -> None:
        self.debug_output_dir = debug_output_dir

    def generate_response(self, complete_conversation: list[ConversationMessage]) -> str:
        payload = {
            "model": self.model_name,
            "messages": _serialize_conversation(complete_conversation),
            "stream": False,
            "think": False,
            "format": STRUCTURED_RESPONSE_SCHEMA,
            "options": {"temperature": 0},
        }

        try:
            response_payload = self._post("/api/chat", payload)
        except Exception as exc:
            self._write_failed_payload(payload, exc)
            raise

        message = response_payload.get("message", {})
        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama response is missing message.content.")

        return content

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.ollama_base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed with status {exc.code}: {response_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Ollama at {self.ollama_base_url}.") from exc

        response_object = json.loads(response_text)
        return response_object

    def _write_failed_payload(self, payload: dict, exc: Exception) -> None:
        if self.debug_output_dir is None:
            return

        self.debug_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_path = self.debug_output_dir / f"failed_payload_{timestamp}.json"
        debug_object = {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "ollama_base_url": self.ollama_base_url,
            "path": "/api/chat",
            "payload": payload,
        }
        debug_path.write_text(
            json.dumps(debug_object, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def build_llm_client(
    provider: str,
    model_name: Optional[str] = "qwen3.5:4b",
    ollama_base_url: str = "http://hivecore.famnit.upr.si:6666",
    timeout_seconds: int = 120,
) -> LLMClient:
    if provider == "mock":
        return MockLLMClient()

    if provider == "ollama":
        if model_name is None or not model_name.strip():
            raise ValueError("model_name is required when provider='ollama'.")
        return OllamaLLMClient(
            model_name=model_name,
            ollama_base_url=ollama_base_url,
            timeout_seconds=timeout_seconds,
        )

    raise ValueError(f"Unsupported provider: {provider!r}.")


def _serialize_conversation(complete_conversation: list[ConversationMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in complete_conversation]
