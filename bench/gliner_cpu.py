"""CPU-only GLiNER relevance reranking of the same hybrid top-30 candidates.

uv run --project bench --no-env-file --no-sync bench/gliner_cpu.py --mode snippet
uv run --project bench --no-env-file --no-sync bench/gliner_cpu.py --mode chunks
No LLM calls during retrieval. Original benchmark files are never overwritten.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import statistics
import time
from pathlib import Path

# Set before torch import. The wheel used for this experiment is CPU-only too.
if os.environ.get('BENCH_DEVICE', 'cpu') == 'cpu':
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
import psutil
import torch
from gliner2 import AutoExtractor

from common import HERE, bootstrap_ci, hit, load_doc, load_subset, mrr
from methods import Hybrid, new_cost, snippet

MODEL = 'fastino/GLiNER2.5-Decide'
REVISION = '5a7adf72a23b4d311abae6ce050d7f0012bb3416'


def positive_score(result):
    values = {v['label']: float(v['confidence']) for v in result['relevance']}
    if set(values) != {'yes', 'no'} or any(not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
        raise ValueError(f'Invalid classification output: {result}')
    if abs(sum(values.values()) - 1) > .01: raise ValueError('Expected a binary softmax distribution')
    return values['yes']


class CpuReranker:
    def __init__(self, threads=4, batch_size=4, precision='fp32'):
        torch.set_num_threads(threads); torch.set_num_interop_threads(1)
        start = time.perf_counter()
        self.model = AutoExtractor.from_pretrained(MODEL, revision=REVISION, map_location='cpu')
        self.model.eval()
        if any(p.device.type != 'cpu' for p in self.model.parameters()): raise RuntimeError('Model must run exclusively on CPU')
        self.load_sec = time.perf_counter() - start
        self.precision = precision
        if precision == 'int8':
            self.model = torch.ao.quantization.quantize_dynamic(self.model, {torch.nn.Linear}, dtype=torch.qint8)
        # Keep class probabilities in float32 even when encoder matrix multiplies use bf16.
        self.model.classifier.register_forward_hook(lambda module, inputs, output: output.float())
        self.batch_size = batch_size
        self.process = psutil.Process()
        self.model_parameter_count = sum(p.numel() for p in self.model.parameters())
        self.peak_rss = self.process.memory_info().rss
        with torch.inference_mode(): self.score(['Revenue was $100 million.'], self.tasks('What was revenue?'))

    def tasks(self, question):
        return {'relevance': {'labels': ['yes', 'no'],
                'prompt': f'Does this passage state information needed to answer the question: {question}',
                'multi_label': True, 'cls_threshold': 0.0, 'class_act': 'softmax'}}

    def encoded_length(self, text, tasks):
        schema = self.model._classification_schema(tasks)
        if not text.endswith(('.', '!', '?')): text += '.'
        record = self.model.processor.transform_and_format(text, schema.build())
        return len(record.input_ids)

    def passages(self, text, question, mode):
        tasks = self.tasks(question)
        if mode == 'snippet':
            selected = snippet(text, question, 170)
            words = selected.split()
            while self.encoded_length(' '.join(words) or '(blank page)', tasks) > 512:
                if not words: raise ValueError('Question/schema alone exceeds 512 positions')
                words.pop()
            return [' '.join(words) or '(blank page)']
        # Whole page coverage using original character spans, with 32-word overlap.
        spans = list(re.finditer(r'\S+', text))
        if not spans: return ['(blank page)']
        out = []; start = 0
        while start < len(spans):
            end = min(start + 200, len(spans))
            while end > start:
                chunk = text[spans[start].start():spans[end - 1].end()]
                if self.encoded_length(chunk, tasks) <= 512: break
                end -= 1
            if end <= start: raise ValueError('Question/schema plus one word exceeds 512 positions')
            out.append(chunk)
            if end == len(spans): break
            start = max(start + 1, end - 32)
        return out

    def score(self, passages, tasks):
        with torch.inference_mode(), torch.autocast('cpu', dtype=torch.bfloat16, enabled=self.precision == 'bf16'):
            outputs = self.model.batch_classify_text(passages, tasks, batch_size=self.batch_size, include_confidence=True, max_len=None)
        if len(outputs) != len(passages): raise ValueError('Classifier dropped passages')
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        return [positive_score(r) for r in outputs]

    def search(self, question, pages, texts, mode):
        started = time.perf_counter(); cpu_started = time.process_time()
        passages, owner = [], []
        for page in pages:
            chunks = self.passages(texts[page], question, mode)
            passages.extend(chunks); owner.extend([page] * len(chunks))
        tasks = self.tasks(question)
        lengths = [self.encoded_length(t, tasks) for t in passages]
        if max(lengths, default=0) > 512: raise ValueError('Unbounded input')
        infer_start = time.perf_counter()
        scores = self.score(passages, tasks)
        infer_sec = time.perf_counter() - infer_start
        page_scores = {p: -1.0 for p in pages}
        for p, s in zip(owner, scores): page_scores[p] = max(page_scores[p], s)
        # Stable ties retain the original hybrid ordering.
        ranked = sorted(pages, key=lambda p: -page_scores[p])
        return {'ranked': ranked[:10], 'conf': page_scores[ranked[0]],
                'scores': page_scores, 'kept': [p for p in ranked if page_scores[p] >= .5],
                'passages': len(passages), 'input_tokens': sum(lengths), 'max_input_tokens': max(lengths),
                'infer_sec': infer_sec, 'rerank_sec': time.perf_counter() - started,
                'cpu_sec': time.process_time() - cpu_started}


def candidates(subset):
    # Fingerprint inputs and baseline implementation so resume never mixes candidate lists.
    docs = sorted({q['doc'] for q in subset})
    digest = hashlib.sha256((HERE / 'methods.py').read_bytes())
    digest.update(json.dumps([(q['id'], q['question'], q['doc']) for q in subset]).encode())
    for doc in docs: digest.update((HERE / f'pdfs/{doc}.pdf').read_bytes())
    key = digest.hexdigest()
    path = HERE / f'cache/gliner_candidates_{key}.json'
    if path.exists(): return json.loads(path.read_text()), key
    out = {}; hybrid = Hybrid()
    for doc in docs:
        start = time.perf_counter(); hybrid.index(doc); index_sec = time.perf_counter() - start
        for q in subset:
            if q['doc'] != doc: continue
            start = time.perf_counter(); pages = hybrid.candidates(q['question'], 30)
            out[q['id']] = {'pages': pages, 'latency': time.perf_counter() - start, 'index_sec': index_sec}
        print(f'Indexed {doc}', flush=True)
    path.write_text(json.dumps(out)); return out, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['snippet', 'chunks'], default='snippet')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--batch-size', type=int, default=4)
    ap.add_argument('--precision', choices=['fp32', 'bf16', 'int8'], default='fp32')
    ap.add_argument('--questions', type=int)
    ap.add_argument('--label', default='')
    args = ap.parse_args()
    subset = load_subset(10, args.questions)
    candidate_rows, candidate_key = candidates(subset)
    tag = f'gliner_{args.mode}@cpu' + (f'-{args.label}' if args.label else '')
    path = HERE / f'results/{tag}.json'
    config = {'model': MODEL, 'revision': REVISION, 'device': 'cpu', 'precision': args.precision, 'threads': args.threads,
              'batch_size': args.batch_size, 'mode': args.mode, 'candidate_key': candidate_key,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'question_ids': [q['id'] for q in subset],
              'versions': {p: importlib.metadata.version(p) for p in ['torch', 'gliner2', 'transformers', 'huggingface_hub']}}
    output = json.loads(path.read_text()) if path.exists() else {'method': tag, 'metadata': config, 'rows': [], 'failed': [], 'index_sec': {}}
    if output['metadata'] != config: raise ValueError('Existing result configuration differs; supply a new --label')
    done = {r['id'] for r in output['rows']}
    reranker = CpuReranker(args.threads, args.batch_size, args.precision)
    output['load_sec'] = reranker.load_sec; output['parameters'] = reranker.model_parameter_count
    for q in subset:
        if q['id'] in done: continue
        texts, _ = load_doc(q['doc']); c = candidate_rows[q['id']]
        try:
            result = reranker.search(q['question'], c['pages'], texts, args.mode)
            output['rows'].append({'id': q['id'], 'doc': q['doc'], 'gold': q['gold'],
                                   'candidates': c['pages'], 'candidate_hit30': hit(c['pages'], q['gold'], 30),
                                   'latency': result['rerank_sec'] + c['latency'], 'candidate_sec': c['latency'],
                                   **new_cost(), **result})
            output['index_sec'][q['doc']] = c['index_sec']
            print(f'{tag} {len(output["rows"])}/{len(subset)} hit@3={100 * statistics.mean(hit(r["ranked"],r["gold"],3) for r in output["rows"]):.1f}% last={result["rerank_sec"]:.2f}s passages={result["passages"]}', flush=True)
        except Exception as exc:
            output['failed'].append({'id': q['id'], 'error': repr(exc)}); print(f'FAILED {q["id"]}: {exc!r}', flush=True)
        output['peak_rss_mb'] = reranker.peak_rss / 1024**2
        path.write_text(json.dumps(output, indent=2))
    if output['failed']: raise SystemExit('Some questions failed; inspect result JSON')
    print(f'Saved {path}', flush=True)


if __name__ == '__main__': main()
