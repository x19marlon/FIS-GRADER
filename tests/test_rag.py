"""Regression tests that do not download models or contact external services."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.rag import retrieve as retrieval
from src.rag import service


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_input_does_not_open_store(self):
        with patch.object(retrieval.lancedb, "connect_async", new_callable=AsyncMock) as connect:
            for question, top_k in [("  ", 5), ("test", 0), ("test", 21), ("x" * 2001, 5)]:
                with self.assertRaises(ValueError):
                    await retrieval.retrieve(question, top_k)
            connect.assert_not_called()

    async def test_missing_index_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(retrieval, "LANCEDB_URI", Path(directory) / "missing"):
                with self.assertRaisesRegex(RuntimeError, "cocoindex update"):
                    await retrieval.retrieve("rúbrica")

    async def test_empty_table_does_not_load_model(self):
        table = SimpleNamespace(count_rows=AsyncMock(return_value=0))
        connection = SimpleNamespace(open_table=AsyncMock(return_value=table))
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(retrieval, "LANCEDB_URI", Path(directory)),
                patch.object(retrieval.lancedb, "connect_async", AsyncMock(return_value=connection)),
                patch.object(retrieval, "get_embedder") as embedder,
            ):
                self.assertEqual(await retrieval.retrieve("rúbrica"), [])
                embedder.assert_not_called()

    async def test_store_failure_is_explained(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(retrieval, "LANCEDB_URI", Path(directory)),
                patch.object(retrieval.lancedb, "connect_async", AsyncMock(side_effect=OSError("bad store"))),
            ):
                with self.assertRaisesRegex(RuntimeError, "índice local"):
                    await retrieval.retrieve("rúbrica")


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_retrieval_does_not_call_llm(self):
        with (
            patch.object(service, "retrieve", AsyncMock(return_value=[])),
            patch.object(service, "_complete") as complete,
        ):
            self.assertIn("No encontré contexto", await service.ask_rag("otra cosa"))
            complete.assert_not_called()

    async def test_answer_contains_traceable_sources(self):
        chunk = retrieval.RetrievedChunk(1, "src/classroom/rubrica.md", "Máximo 10 puntos", 0, 16, 0.7)
        with (
            patch.object(service, "retrieve", AsyncMock(return_value=[chunk])),
            patch.object(service, "_complete", return_value="El máximo es 10 puntos [1].") as complete,
        ):
            answer = await service.ask_rag("¿Puntaje máximo?")
            self.assertIn("10 puntos [1]", answer)
            self.assertIn("src/classroom/rubrica.md (caracteres 0–16)", answer)
            self.assertIn(chunk.text, complete.call_args.args[1])

    def test_rag_does_not_require_deepseek_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with patch.object(service, "chat", return_value="respuesta") as chat:
                self.assertEqual(service._complete("pregunta", "contexto"), "respuesta")
                self.assertIn("contexto", chat.call_args.args[0][1]["content"])


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"MONGODB_URI": "mongodb://localhost:27017"}):
            cls.bot = importlib.import_module("src.telegram.bot")

    async def asyncSetUp(self):
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.update = SimpleNamespace(effective_message=self.message, effective_user=SimpleNamespace(id=42))
        self.context = SimpleNamespace(args=["¿Puntaje", "máximo?"])
        self.authorization = patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "42"})
        self.authorization.start()
        self.addCleanup(self.authorization.stop)

    async def test_unauthorized_user_cannot_call_rag(self):
        self.update.effective_user.id = 99
        with patch.object(service, "ask_rag", new_callable=AsyncMock) as ask:
            await self.bot.ask_command(self.update, self.context)
            ask.assert_not_called()

    async def test_empty_question_shows_usage(self):
        self.context.args = []
        with patch.object(service, "ask_rag", new_callable=AsyncMock) as ask:
            await self.bot.ask_command(self.update, self.context)
            ask.assert_not_called()
            self.assertIn("/ask", self.message.reply_text.call_args.args[0])

    async def test_provider_error_is_not_exposed(self):
        with patch.object(service, "ask_rag", AsyncMock(side_effect=Exception("internal provider failure"))):
            with self.assertLogs(self.bot.LOGGER, level="ERROR"):
                await self.bot.ask_command(self.update, self.context)
            reply = self.message.reply_text.call_args.args[0]
            self.assertIn("error", reply)
            self.assertNotIn("internal provider", reply)

    async def test_long_answer_is_split(self):
        answer = "🙂" * 4200
        with patch.object(service, "ask_rag", AsyncMock(return_value=answer)):
            await self.bot.ask_command(self.update, self.context)
        replies = [call.args[0] for call in self.message.reply_text.call_args_list]
        self.assertEqual("".join(replies), answer)
        self.assertTrue(all(len(reply.encode("utf-16-le")) // 2 <= 4096 for reply in replies))

    def test_all_commands_are_registered_without_polling(self):
        with (
            patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:test"}),
            patch.object(self.bot.Application, "run_polling") as polling,
            patch.object(self.bot.Application, "add_handler") as add_handler,
        ):
            self.bot.main()
        commands = {command for call in add_handler.call_args_list for command in call.args[0].commands}
        self.assertEqual(commands, {"start", "help", "whoami", "groups", "summary", "commits", "history", "student", "excel", "ask"})
        polling.assert_called_once()

    def test_original_launch_import_works_without_cocoindex(self):
        script = """
import builtins, runpy
original = builtins.__import__
def restricted(name, *args, **kwargs):
    if name.startswith('cocoindex'):
        raise ImportError('RAG unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = restricted
runpy.run_path('src/telegram/bot.py', run_name='bot_import_test')
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "MONGODB_URI": "mongodb://localhost:27017"},
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
