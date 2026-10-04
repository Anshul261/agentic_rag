import unittest

from pageindex_demo import select_demo


class DemoTests(unittest.TestCase):
    def test_demo_uses_distinct_cached_documents_without_gold_fields(self):
        qs = [{"financebench_id": str(i), "doc_name": d, "question": "q", "answer": "secret", "evidence": []}
              for i, d in enumerate(["missing", "a", "a", "b", "c"])]
        selected = select_demo(qs, {"a": [], "b": [], "c": []})
        self.assertEqual([q["document"] for q in selected], ["a", "b", "c"])
        self.assertTrue(all(set(q) == {"id", "document", "question"} for q in selected))

    def test_gliner_adapter_accepts_real_sdk_primitives(self):
        from gliner_jev_adapter import GLiNERClient
        from jev_reference import LocalPages, reference
        class Engine:
            def encoded_length(self, text, tasks):
                return 513 if "pick" in tasks else 100
            def score(self, texts, tasks):
                return [.8] * len(texts)
        tree = [{"node_id": "leaf", "title": "Cash flow", "summary": "Cash and expenditures", "start_index": 1, "end_index": 2}]
        client = GLiNERClient(Engine(),max_context=512)
        client.set_document("doc", tree, ["cash flow", "assets"])
        found = reference(client).locate(LocalPages({"doc": tree}, {"doc": {1: "cash flow", 2: "assets"}}), "doc", "How much cash?")
        self.assertEqual(set(found["pages"]), {1, 2})
        self.assertTrue(any(e["mode"] == "chunked_binary_odds" for e in client.events))
        self.assertTrue(any(e["mode"] == "chunked_binary_verify" for e in client.events))

    def test_opening_pages_keep_parent_context(self):
        from gliner_jev_adapter import GLiNERClient
        class Engine:
            def encoded_length(self, text, tasks):
                return 100
        child={"node_id":"child","title":"child","summary":"child state","start_index":3,"end_index":4}
        parent={"node_id":"parent","title":"parent","summary":"parent state","start_index":1,"end_index":4,"nodes":[child]}
        client=GLiNERClient(Engine())
        client.set_document("doc",[parent])
        self.assertEqual(client.path_for("p1"),["parent"])
        self.assertEqual(client.path_for("p3"),["parent","child"])
        chunks,_=client.chunks("question","check","p3","candidate")
        self.assertIn("parent state",chunks[0])
        self.assertIn("child state",chunks[0])


if __name__ == "__main__":
    unittest.main()
