"""Small Ollama HTTP client with mandatory GPU checks; no remote LLM fallback."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_CONTEXT_SIZE,
    OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT,
)


class OllamaError(RuntimeError):
    """An actionable error safe to show in the CLI and Telegram."""


def request_json(path: str, payload: dict | None = None) -> dict:
    """Perform bounded synchronous HTTP; callers in asyncio use to_thread."""

    url = urlsplit(OLLAMA_BASE_URL)
    if url.scheme not in {"http", "https"} or not url.netloc or url.query or url.fragment:
        raise OllamaError("OLLAMA_BASE_URL debe ser una URL HTTP válida.")
    request = Request(
        OLLAMA_BASE_URL + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            result = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise OllamaError(
                f"Ollama no encontró el modelo o endpoint. Comprueba OLLAMA_MODEL "
                f"y ejecuta ollama pull {OLLAMA_MODEL}."
            ) from error
        raise OllamaError(f"Ollama respondió con error HTTP {error.code}.") from error
    except (URLError, OSError) as error:
        raise OllamaError(
            "No se pudo conectar con Ollama o se agotó el tiempo. "
            "Comprueba OLLAMA_BASE_URL y que ollama serve esté activo."
        ) from error
    except (ValueError, UnicodeError) as error:
        raise OllamaError("Ollama devolvió una respuesta JSON inválida.") from error
    if not isinstance(result, dict) or result.get("error"):
        raise OllamaError("Ollama devolvió una respuesta inválida o un error.")
    return result


def require_gpu() -> dict:
    """Fail closed unless /api/ps reports the configured model fully in VRAM.

    These are Ollama allocation metrics, not hardware utilization percentages.
    CPU-only, mixed placement, missing models and unknown metrics are rejected.
    """

    model = OLLAMA_MODEL
    if ":" not in model.rsplit("/", 1)[-1]:
        model += ":latest"
    rows = request_json("/api/ps").get("models")
    if not isinstance(rows, list):
        raise OllamaError("No se pudo verificar la GPU: /api/ps no contiene modelos.")
    for row in rows:
        if not isinstance(row, dict) or model not in (row.get("name"), row.get("model")):
            continue
        size, vram = row.get("size"), row.get("size_vram")
        if type(size) is not int or type(vram) is not int or size <= 0 or vram < 0:
            raise OllamaError("Ollama no proporciona métricas válidas para verificar la GPU.")
        if vram == 0:
            raise OllamaError("Ollama cargó el modelo en CPU. El RAG requiere GPU; revisa drivers y ollama ps.")
        if vram < size:
            raise OllamaError(
                f"Ollama reporta CPU+GPU ({100 * vram / size:.1f}% en VRAM). "
                "El RAG exige carga completa en GPU. Libera VRAM o usa un modelo menor."
            )
        return {"model": model, "execution": "GPU", "size": size, "size_vram": vram}
    raise OllamaError("El modelo configurado no está cargado; no se puede verificar su GPU.")


def load_and_check_gpu() -> dict:
    """Load without a user prompt, then check actual placement before generation."""

    request_json("/api/generate", {
        "model": OLLAMA_MODEL,
        "prompt": "",
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_ctx": OLLAMA_CONTEXT_SIZE},
    })
    return require_gpu()


def chat(messages: list[dict[str, str]]) -> str:
    """Generate only after GPU verification, then recheck the returned model."""

    load_and_check_gpu()
    # Qwen3's documented soft switch complements Ollama's think=False.
    if OLLAMA_MODEL.rsplit("/", 1)[-1].split(":", 1)[0] == "qwen3" and messages:
        messages = [dict(message) for message in messages]
        messages[-1]["content"] += "\n/no_think"
    result = request_json("/api/chat", {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_ctx": OLLAMA_CONTEXT_SIZE, "num_predict": 1200, "temperature": 0},
    })
    require_gpu()
    message = result.get("message")
    answer = message.get("content") if isinstance(message, dict) else None
    if result.get("done") is not True or not isinstance(answer, str) or not answer.strip():
        raise OllamaError("Ollama devolvió una respuesta vacía o incompleta.")
    if result.get("done_reason") == "length":
        raise OllamaError("Ollama alcanzó el límite de respuesta; prueba una pregunta más concreta.")
    # Some model templates put reasoning in content instead of message.thinking.
    # Deliver only the final response, including when the opening tag is omitted.
    if "</think>" in answer:
        answer = answer.rsplit("</think>", 1)[1]
    if "<think>" in answer or not answer.strip():
        raise OllamaError("Ollama no devolvió una respuesta final utilizable.")
    return answer.strip()


def main() -> None:
    """Load the configured model and print the GPU placement reported by Ollama."""

    try:
        print(json.dumps(load_and_check_gpu(), indent=2, ensure_ascii=False))
    except OllamaError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
