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


class RecallVecTest(unittest.TestCase):
    """Vector layer: RRF merge, provider=none parity, failure fallback."""

    def setUp(self):
        import unittest.mock as mock
        self.db = pathlib.Path(tempfile.mkdtemp()) / "recall.db"
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            self.skipTest("sqlite-vec not installed")
        self.cfg = {"provider": "openai",
                    "base_url": "http://unused",
                    "model": "fake-emb"}
        recall._vec_failed = False
        self._p = mock.patch.object(
            recall.config, "load_config",
            return_value={"recall": self.cfg})
        self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(lambda: setattr(recall, "_vec_failed", False))

    def _embed_side(self, texts, cfg):
        # 2-cluster fake embedding: texts sharing vocab → [1,0], else [0,1]
        vocab = {"restart", "audio", "daemon", "pipewire", "reboot"}
        return [[1.0, 0.0] if vocab & set(t.lower().split())
                else [0.0, 1.0] for t in texts]

    def test_vec_hit_outranks_on_paraphrase(self):
        import unittest.mock as mock
        with mock.patch.object(recall, "_embed", self._embed_side), \
                mock.patch.object(recall, "_queue_embed",
                                  recall._embed_and_store):
            recall.add("turn", "user: reboot audio daemon",
                       path=self.db)
            recall.add("turn", "user: unrelated groceries list",
                       path=self.db)
            # paraphrase query — no lexical overlap with the hit
            hits = recall.search("restart pipewire", path=self.db)
        self.assertTrue(hits)
        self.assertIn("audio daemon", hits[0]["body"])

    def test_provider_none_identical_to_fts(self):
        self._p.stop()  # real config → provider=none
        recall.index_turn("kernel module rebuild", "ok", path=self.db)
        recall.index_turn("brew coffee", "ok", path=self.db)
        hits = recall.search("kernel", path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertIn("kernel", hits[0]["body"])

    def test_embed_failure_still_returns_fts(self):
        import unittest.mock as mock
        def boom(texts, cfg):
            raise RuntimeError("api down")
        with mock.patch.object(recall, "_embed", boom):
            recall.index_turn("systemd unit failed", "ok", path=self.db)
            hits = recall.search("systemd", path=self.db)
        self.assertTrue(hits)
        self.assertIn("systemd", hits[0]["body"])

    def test_dims_mismatch_recreates_vec_table(self):
        import unittest.mock as mock, sqlite3
        def emb3(texts, cfg):
            return [[1.0, 0.0, 0.0] for _ in texts]
        def emb2(texts, cfg):
            return [[1.0, 0.0] for _ in texts]
        with mock.patch.object(recall, "_embed", emb3):
            recall._embed_and_store(1, "first", self.cfg, self.db)
        with mock.patch.object(recall, "_embed", emb2):
            recall._embed_and_store(2, "second", self.cfg, self.db)
        db = sqlite3.connect(str(self.db))
        try:
            dims = db.execute(
                "SELECT value FROM recall_meta WHERE key='dims'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(dims, "2")


if __name__ == "__main__":
    unittest.main()
