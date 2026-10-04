import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from jev_reference import (SOURCE, MODEL, PINNED_SHA256, SOURCE_SHA256,
                           LocalPages, RecordedClient, reference, validate_tree)


class FakeClient:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions):
        self.calls.append((state, questions))
        answers = {}
        for key, q in questions.items():
            if q.type == "choice":
                labels = list(q.criteria)
                probs = {v: (len(labels) - i) / sum(range(1, len(labels) + 1)) for i, v in enumerate(labels)}
                answers[key] = NS(probabilities=probs)
            else:
                answers[key] = NS(noul=.2 if state["page"] == "a" else .1)
        return NS(answers=answers, usage=NS(input_tokens=7))


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.ref = reference(self.client)

    def test_pinned_original_functions(self):
        self.assertEqual(SOURCE_SHA256, PINNED_SHA256)
        names = [n.name for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(names, [n for n in names if callable(getattr(self.ref, n))])
        self.assertEqual(self.ref.MODEL, MODEL)

    def test_opening_pages_and_single_option_shortcut(self):
        node = {"node_id": "p", "title": "parent", "summary": "state", "start_index": 1, "end_index": 5}
        child = {"node_id": "c", "title": "child", "summary": "content", "start_index": 3, "end_index": 5}
        opts, targets = self.ref.section_options(node, [child])
        self.assertEqual(targets["p:opening"][2:], (1, 2))
        self.assertIn("content", opts["c"])
        self.assertEqual(self.ref.ask_choice("question", "choose", {"c": "only"}), ({"c": 1.}, 0))
        self.assertEqual(len(self.client.calls), 0)

    def test_beam_geometric_mean(self):
        leaf = lambda key, p: {"node_id": key, "title": key, "summary": key, "start_index": p, "end_index": p}
        branch = {**leaf("b", 1), "end_index": 2, "nodes": [leaf("c", 1), leaf("d", 2)]}
        sections, trace, tokens = self.ref.search_sections("question", [branch, leaf("a", 3)], beam=2)
        self.assertAlmostEqual(sections[0]["score"], 2 / 3)
        self.assertAlmostEqual(sections[1]["score"], (2 / 9) ** .5)
        self.assertEqual(tokens, 14)
        self.assertEqual(len(trace), 2)

    def test_windows_and_verifier_fallback(self):
        self.ref.MAX_OPTIONS = 2
        self.assertEqual(self.ref.windows([1, 2, 3], {1: "a", 2: "b", 3: "c"}), [[1, 2], [3]])
        self.ref.MAX_TOKENS = 1
        self.assertEqual(self.ref.windows([1, 2], {1: "a", 2: "b"}), [[1], [2]])
        kept, scores, tokens = self.ref.check_pages("question", [2, 1, 3], {1: "a", 2: "b", 3: "c"})
        self.assertEqual(kept[0], 1)
        self.assertEqual(len(kept), 2)
        self.assertEqual(tokens, 21)
        self.assertTrue(all(v < .5 for v in scores.values()))

    def test_local_indices_and_validation(self):
        tree = [{"node_id": "1", "title": "leaf", "summary": "state", "start_index": 1, "end_index": 2}]
        validate_tree(tree, 2)
        pages = LocalPages({"doc": tree}, {"doc": {1: "a", 2: "b"}})
        found = self.ref.locate(pages, "doc", "question")
        self.assertEqual(found["pages"], [1, 2])
        self.assertEqual(set(found["text"]), {1, 2})
        self.assertTrue(all(set(state) <= {"question", "page"} for state, _ in self.client.calls))
        tree[0]["end_index"] = 3
        with self.assertRaises(ValueError):
            validate_tree(tree, 2)

    def test_cache_preserves_response_and_marks_latency(self):
        from typesafe_sdk import Choice
        calls = []
        raw = {"model": MODEL, "answers": {"pick": {"type": "choice", "probabilities": {"a": .7, "b": .3}, "choice": "a"}}, "usage": {"input_tokens": 10, "output_tokens": 1}}
        class SDK:
            def system_one(self, **kwargs):
                calls.append(kwargs)
                return NS(model_dump=lambda **_: raw)
        with tempfile.TemporaryDirectory() as folder:
            client = RecordedClient(SDK(), folder)
            kwargs = {"state": {"question": "q"}, "questions": {"pick": Choice(criteria={"a": "A", "b": "B"})}}
            a, b = client.system_one(**kwargs), client.system_one(**kwargs)
            self.assertEqual(a.answers["pick"].probabilities, b.answers["pick"].probabilities)
            self.assertEqual(len(calls), 1)
            self.assertEqual([e["cached"] for e in client.events], [False, True])
            self.assertNotIn("api_key", next(Path(folder).glob("*.json")).read_text())


if __name__ == "__main__":
    unittest.main()
