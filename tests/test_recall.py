"""U5c: recall.db — write-through indexing, top-k FTS5 search, empty-db
safety (lexical fallback needs no keys)."""
import tempfile
import unittest
import pathlib

from dim import recall


class RecallTest(unittest.TestCase):
    def setUp(self):
        self.db = pathlib.Path(tempfile.mkdtemp()) / "recall.db"

    def test_index_and_search_turn(self):
        recall.index_turn("how do I restart pipewire",
                          "run systemctl --user restart wireplumber",
                          path=self.db)
        hits = recall.search("pipewire", path=self.db)
        self.assertTrue(hits)
        self.assertIn("wireplumber", hits[0]["body"])

    def test_ranking_prefers_relevant(self):
        recall.index_turn("launch discord", "", "LAUNCHED", path=self.db)
        recall.index_turn("fix wifi driver", "", "SPAWNED", path=self.db)
        hits = recall.search("wifi", path=self.db)
        self.assertEqual(hits[0]["kind"], "turn")
        self.assertIn("wifi", hits[0]["body"])

    def test_index_correction(self):
        recall.index_correction({"heard": "open disco",
                                 "picked": "app:browser"}, path=self.db)
        hits = recall.search("disco", path=self.db)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["kind"], "correction")

    def test_empty_db_returns_empty(self):
        self.assertEqual(recall.search("anything", path=self.db), [])
        self.assertEqual(recall.context_for("anything", path=self.db), "")

    def test_empty_query_safe(self):
        self.assertEqual(recall.search("!!!", path=self.db), [])
        self.assertEqual(recall.search("", path=self.db), [])

    def test_run_tool_form(self):
        recall.index_turn("my ssh key is at ~/.ssh/id_ed25519",
                          "noted", path=self.db)
        import unittest.mock as mock
        with mock.patch.object(recall, "DB_FILE", self.db):
            out = recall.run("search ssh")
            self.assertIn("id_ed25519", out)
            self.assertIn("no recall hits", recall.run("search zzzqqq"))

    def test_context_for_injection(self):
        recall.index_turn("deploy uses fly.toml", "ok", path=self.db)
        ctx = recall.context_for("deploy", path=self.db)
        self.assertIn("fly.toml", ctx)

    def test_blank_body_not_indexed(self):
        recall.add("turn", "   ", path=self.db)
        self.assertEqual(recall.search("turn", path=self.db), [])


if __name__ == "__main__":
    unittest.main()
