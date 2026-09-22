"""GPU policy and transport regressions without requiring an Ollama server."""

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.rag import ollama


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.model_patch = patch.object(ollama, "OLLAMA_MODEL", "test:small")
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def metrics(self, size=100, vram=100):
        return {"models": [{"name": "test:small", "size": size, "size_vram": vram}]}

    def test_full_gpu_is_accepted(self):
        with patch.object(ollama, "request_json", return_value=self.metrics()):
            self.assertEqual(ollama.require_gpu()["execution"], "GPU")

    def test_cpu_and_partial_gpu_are_rejected_before_chat(self):
        for vram, message in [(0, "en CPU"), (60, "CPU\\+GPU")]:
            with self.subTest(vram=vram):
                with patch.object(ollama, "request_json", side_effect=[{}, self.metrics(vram=vram)]) as request:
                    with self.assertRaisesRegex(ollama.OllamaError, message):
                        ollama.chat([{"role": "user", "content": "pregunta"}])
                    self.assertEqual([c.args[0] for c in request.call_args_list], ["/api/generate", "/api/ps"])

    def test_unknown_or_unrelated_model_metrics_are_rejected(self):
        for response in [{}, {"models": []}, self.metrics(size=0), self.metrics(vram=None),
                         {"models": [{"name": "other:model", "size": 100, "size_vram": 100}]}]:
            with self.subTest(response=response):
                with patch.object(ollama, "request_json", return_value=response):
                    with self.assertRaises(ollama.OllamaError):
                        ollama.require_gpu()

    def test_chat_passes_context_and_rechecks_gpu(self):
        messages = [{"role": "user", "content": "Contexto: 10 puntos. Pregunta: ¿máximo?"}]
        with patch.object(ollama, "request_json", side_effect=[
            {}, self.metrics(), {"done": True, "message": {"content": "10 puntos"}}, self.metrics(),
        ]) as request:
            self.assertEqual(ollama.chat(messages), "10 puntos")
            self.assertEqual(request.call_args_list[2].args[1]["messages"], messages)
            self.assertEqual(request.call_args_list[3].args[0], "/api/ps")

    def test_gpu_loss_after_generation_rejects_answer(self):
        with patch.object(ollama, "request_json", side_effect=[
            {}, self.metrics(), {"done": True, "message": {"content": "answer"}}, self.metrics(vram=0),
        ]):
            with self.assertRaisesRegex(ollama.OllamaError, "en CPU"):
                ollama.chat([])

    def test_invalid_or_truncated_answer(self):
        for response in [{"done": True, "message": {"content": " "}},
                         {"done": False},
                         {"done": True, "done_reason": "length", "message": {"content": "partial"}}]:
            with patch.object(ollama, "request_json", side_effect=[{}, self.metrics(), response, self.metrics()]):
                with self.assertRaises(ollama.OllamaError):
                    ollama.chat([])

    def test_transport_errors_are_actionable(self):
        for error in [URLError("connection refused"), TimeoutError(),
                      HTTPError("http://localhost", 404, "missing", {}, None)]:
            with patch.object(ollama, "urlopen", side_effect=error):
                with self.assertRaises(ollama.OllamaError):
                    ollama.request_json("/api/ps")

    def test_only_final_answer_is_returned(self):
        for answer in ["<think>internal analysis</think>Respuesta", "internal analysis</think>Respuesta"]:
            with patch.object(ollama, "request_json", side_effect=[
                {}, self.metrics(), {"done": True, "message": {"content": answer}}, self.metrics(),
            ]):
                self.assertEqual(ollama.chat([]), "Respuesta")

    def test_invalid_json_is_rejected(self):
        for body in [b"not json", b"[]", b'{"error":"failure"}']:
            with patch.object(ollama, "urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises(ollama.OllamaError):
                    ollama.request_json("/api/ps")

    def test_http_payload_and_timeout(self):
        with patch.object(ollama, "urlopen", return_value=io.BytesIO(b'{"models":[]}')) as opened:
            ollama.request_json("/api/chat", {"model": "test:small"})
            self.assertEqual(json.loads(opened.call_args.args[0].data), {"model": "test:small"})
            self.assertEqual(opened.call_args.kwargs["timeout"], ollama.OLLAMA_TIMEOUT)
