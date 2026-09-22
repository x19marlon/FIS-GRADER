"""Opt-in real CocoIndex/LanceDB tests; requires the cached embedding model.

Run with RUN_RAG_INTEGRATION=1 python -m unittest discover -s tests -v.
All writes use temporary fixtures, never the project's rubric/index.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.getenv("RUN_RAG_INTEGRATION") == "1", "opt-in local model integration test")
class IncrementalIndexTests(unittest.TestCase):
    def test_update_replaces_removed_chunks_and_handles_deleted_source(self):
        import lancedb

        script = """
from pathlib import Path
import sys
from src.rag import config
config.SOURCE_DIRECTORY = Path(sys.argv[1])
config.LANCEDB_URI = Path(sys.argv[2])
from src.rag.index import app
app.update_blocking()
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "documents"
            source.mkdir()
            rubric = source / "rubrica.md"
            database = root / "index"

            def update():
                result = subprocess.run(
                    [sys.executable, "-c", script, str(source), str(database)],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, timeout=90,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            def rows():
                return lancedb.connect(str(database)).open_table("rubric_chunks").to_arrow().to_pylist()

            rubric.write_text("# Rúbrica de prueba\n\nLa navegación vale dos puntos.", encoding="utf-8")
            update()
            first = rows()
            self.assertTrue(first)
            update()
            self.assertEqual(rows(), first)

            rubric.write_text("# Rúbrica de prueba\n\nLa claridad visual vale tres puntos.", encoding="utf-8")
            update()
            changed = rows()
            self.assertTrue(any("tres puntos" in row["text"] for row in changed))
            self.assertFalse(any("dos puntos" in row["text"] for row in changed))
            for row in changed:
                text = rubric.read_text(encoding="utf-8")
                self.assertEqual(text[row["chunk_start"]:row["chunk_end"]], row["text"])

            rubric.unlink()
            update()
            self.assertEqual(rows(), [])
