import unittest

from gliner_cpu import CpuReranker, positive_score


class GlinerTests(unittest.TestCase):
    def test_negative_class_is_not_treated_as_relevance(self):
        result = {'relevance': [{'label': 'no', 'confidence': .9}, {'label': 'yes', 'confidence': .1}]}
        self.assertEqual(positive_score(result), .1)

    def test_missing_or_nonfinite_scores_rejected(self):
        for values in [[{'label': 'yes', 'confidence': .9}],
                       [{'label': 'yes', 'confidence': float('nan')}, {'label': 'no', 'confidence': .2}]]:
            with self.assertRaises(ValueError): positive_score({'relevance': values})

    def test_chunks_cover_whole_page_without_overflow(self):
        reranker = CpuReranker.__new__(CpuReranker)
        reranker.encoded_length = lambda text, tasks: 100 + len(text.split()) * 3
        text = ' '.join(f'word{i}' for i in range(500))
        chunks = reranker.passages(text, 'question', 'chunks')
        self.assertEqual(set(text.split()), {word for chunk in chunks for word in chunk.split()})
        self.assertTrue(all(reranker.encoded_length(chunk, {}) <= 512 for chunk in chunks))


if __name__ == '__main__': unittest.main()
