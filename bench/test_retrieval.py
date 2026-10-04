"""Regression checks for silent truncation, dropped failures, and traversal."""
import unittest
from unittest.mock import patch

from common import build_tree
from deep_eval import judge, section_metrics, validate_cohort
from methods import KevClient, KevTree, new_cost


class RetrievalTests(unittest.TestCase):
    def client(self):
        client = KevClient.__new__(KevClient)
        client.option_limit = 128; client.state_limit = 7168
        client.ntok = lambda text: len(text.split())
        return client

    def test_choice_truncation_rejected_before_request(self):
        with self.assertRaisesRegex(ValueError, "silently truncates Choice"):
            self.client().ask("question", {"q": {"type": "choice", "criteria": {"p0": "word " * 128}}}, new_cost())

    def test_state_truncation_rejected_before_request(self):
        with self.assertRaisesRegex(ValueError, "silently truncate this state"):
            self.client().ask("word " * 7169, {"q": {"type": "noul"}}, new_cost())

    def test_state_render_matches_server(self):
        self.assertEqual(self.client().render({"question": "q", "page": "p"}), "question: q\npage: p")

    def test_empty_section_selection_and_overlap(self):
        rec, size = section_metrics([{"sections": [], "gold": [2]}, {"sections": [(1, 3), (2, 4)], "gold": [2]}])
        self.assertEqual(rec, .5); self.assertEqual(size, 2)

    def test_failed_or_duplicate_questions_rejected(self):
        gold = {"q": {"doc": "d", "gold": [1]}}
        for result in [{"rows": [], "failed": [{"id": "q"}]}, {"rows": [{"id": "q"}, {"id": "q"}]}]:
            with self.assertRaises(ValueError): validate_cohort({"m": result}, gold)

    def test_judge_string_false_rejected(self):
        with patch("deep_eval.llm", return_value={"correct": "false"}):
            with self.assertRaises(ValueError): judge("q", "gold", "answer")

    def test_bookmarks_keep_front_matter(self):
        class Doc:
            def __len__(self): return 10
            def get_toc(self): return [[1, f"Section {p}", p] for p in range(3, 8)]
        self.assertEqual(build_tree(Doc())[0]["start"], 0)

    def test_single_child_and_opening_page_traversal(self):
        tree = KevTree.__new__(KevTree)
        tree.top = [{"id": 0, "title": "parent", "start": 0, "end": 2}]
        tree.kids = [[{"id": 1, "start": 1, "end": 2}], []]
        tree.desc = {0: "parent", 1: "child"}; tree.choice_mode = "full"
        tree.kev = self.client(); tree._lead = lambda _: "intro"
        tree.kev.choice = lambda *args: {"s1": .8, "s0:opening": .2}
        tree.MAX_TOKENS = 7168
        self.assertEqual(tree.sections("q", new_cost()), [(.8, [1, 2]), (.2, [0])])


if __name__ == "__main__": unittest.main()
