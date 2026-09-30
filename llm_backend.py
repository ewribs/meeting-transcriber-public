from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class LLMBackend(Protocol):
    name: str

    @property
    def last_elapsed_seconds(self) -> float | None:
        ...

    def generate(
        self,
        prompt: str,
        response_format: Any = None,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        ...


@dataclass
class OllamaBackend:
    model: str
    url: str
    context_size: int = 0
    name: str = "ollama"
    _last_elapsed_seconds: float | None = None
    urlopen: Callable[..., Any] = urllib.request.urlopen

    @property
    def last_elapsed_seconds(self) -> float | None:
        return self._last_elapsed_seconds

    def generate(
        self,
        prompt: str,
        response_format: Any = None,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
        }

        if self.context_size > 0:
            payload["options"] = {"num_ctx": self.context_size}

        if response_format is not None:
            payload["format"] = response_format

        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        effective_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else 120.0
        )

        started = time.perf_counter()
        try:
            with self.urlopen(
                request,
                timeout=effective_timeout,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.url}: {error}"
            ) from error
        finally:
            self._last_elapsed_seconds = time.perf_counter() - started

        response_text = str(result.get("response", "")).strip()
        if not response_text:
            raise RuntimeError("Ollama returned an empty response.")
        return response_text


class MLXBackend:
    name = "mlx"

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int = 3000,
    ) -> None:
        self.model_name = model
        self.max_tokens = int(max_tokens)
        self._model = None
        self._tokenizer = None
        self._last_elapsed_seconds: float | None = None

    @property
    def last_elapsed_seconds(self) -> float | None:
        return self._last_elapsed_seconds

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        try:
            from mlx_lm import load
        except ImportError as exc:
            raise RuntimeError(
                "MLX backend requested, but mlx-lm is not installed. "
                "Install mlx-lm in the Python environment or select Ollama."
            ) from exc

        self._model, self._tokenizer = load(self.model_name)

    def _chat_prompt(self, user_prompt: str) -> str:
        self._ensure_loaded()
        assert self._tokenizer is not None

        messages = [{"role": "user", "content": user_prompt}]
        try:
            return str(
                self._tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
            )
        except (TypeError, ValueError):
            return str(
                self._tokenizer.apply_chat_template(
                    [
                        {
                            "role": "user",
                            "content": user_prompt.rstrip() + "\n\n/no_think",
                        }
                    ],
                    tokenize=False,
                    add_generation_prompt=True,
                )
            )

    @staticmethod
    def _strip_thinking(text: str) -> str:
        value = text.strip()
        value = re.sub(
            r"(?is)^\s*<think>.*?</think>\s*",
            "",
            value,
            count=1,
        ).strip()
        if value.startswith("<think>"):
            raise RuntimeError(
                "MLX response ended inside a thinking block."
            )
        return value

    def _token_count(self, text: str) -> int:
        assert self._tokenizer is not None
        try:
            return len(self._tokenizer.encode(text))
        except Exception:
            return 0

    def generate(
        self,
        prompt: str,
        response_format: Any = None,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        # timeout_seconds is accepted for interface compatibility. mlx-lm's
        # in-process generation API does not currently provide a safe hard
        # cancellation primitive, so callers retain their existing timeout
        # semantics on the Ollama path.
        del timeout_seconds
        self._ensure_loaded()

        try:
            from mlx_lm import generate
        except ImportError as exc:
            raise RuntimeError(
                "MLX backend requested, but mlx-lm is not installed."
            ) from exc

        user_prompt = prompt.rstrip()
        if response_format is not None:
            schema_text = json.dumps(
                response_format,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            user_prompt += (
                "\n\nReturn ONLY valid JSON. Do not use Markdown fences or "
                "commentary. The JSON must conform to this schema:\n"
                + schema_text
            )

        formatted_prompt = self._chat_prompt(user_prompt)

        started = time.perf_counter()
        try:
            raw = generate(
                model=self._model,
                tokenizer=self._tokenizer,
                prompt=formatted_prompt,
                max_tokens=self.max_tokens,
                verbose=False,
            )
        except TypeError:
            raw = generate(
                self._model,
                self._tokenizer,
                prompt=formatted_prompt,
                max_tokens=self.max_tokens,
                verbose=False,
            )
        finally:
            self._last_elapsed_seconds = time.perf_counter() - started

        response_text = self._strip_thinking(str(raw))
        output_tokens = self._token_count(response_text)
        if output_tokens >= max(1, int(self.max_tokens * 0.98)):
            raise RuntimeError(
                "MLX response appears truncated at the generation token ceiling."
            )

        if response_format is not None:
            candidate = response_text.strip()
            if candidate.startswith("```"):
                candidate = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    candidate,
                    flags=re.IGNORECASE,
                )
                candidate = re.sub(r"\s*```$", "", candidate).strip()
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"MLX returned malformed structured JSON: {exc}"
                ) from exc
            response_text = json.dumps(parsed, ensure_ascii=False)

        if not response_text:
            raise RuntimeError("MLX returned an empty response.")
        return response_text


def normalize_backend_name(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"mlx", "mlx-lm"}:
        return "mlx"
    return "ollama"


def create_backend(
    backend_name: str,
    *,
    ollama_model: str,
    ollama_url: str,
    context_size: int,
    mlx_model: str,
    mlx_max_tokens: int,
    ollama_urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> LLMBackend:
    normalized = normalize_backend_name(backend_name)
    if normalized == "mlx":
        return MLXBackend(
            model=mlx_model,
            max_tokens=mlx_max_tokens,
        )
    return OllamaBackend(
        model=ollama_model,
        url=ollama_url,
        context_size=context_size,
        urlopen=ollama_urlopen,
    )
