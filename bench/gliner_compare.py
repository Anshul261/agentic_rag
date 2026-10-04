"""Compare saved baselines with GLiNER, retaining every answer and judgment.

Starts evaluating completed GLiNER questions while CPU retrieval continues.
Reuses the original benchmark's cached GLM responses when the exact prompt matches.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import statistics as st
import time
from pathlib import Path

import deep_eval
from common import HERE, bootstrap_ci, hit, load_doc, load_subset
from methods import llm as live_llm, new_cost

MODEL = deep_eval.MODEL


def cached_or_live(model, prompt, cost, max_tokens=1500):
    legacy = HERE / f'cache/{hashlib.md5(f"{model}\n{prompt}".encode()).hexdigest()}.json'
    if legacy.exists():
        value = json.loads(legacy.read_text())
        decoder = json.JSONDecoder()
        for i, char in enumerate(value['text']):
            if char != '{': continue
            try: result, _ = decoder.raw_decode(value['text'][i:])
            except json.JSONDecodeError: continue
            if isinstance(result, dict): return result
    return live_llm(model, prompt, cost, max_tokens)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gliner', default='gliner_snippet@cpu-bf16')
    ap.add_argument('--wait', action='store_true')
    args = ap.parse_args()
    deep_eval.llm = cached_or_live
    gold = {q['id']: q for q in load_subset()}
    methods = ['bm25', 'hybrid', 'llm_tree', 'kev_rerank@k2-0.9b', 'kev_rerank@kev4b-q8', 'kev_tree@k2-0.9b', args.gliner]
    path = HERE / f'results/{args.gliner}-answers.json'
    output = json.loads(path.read_text()) if path.exists() else {'model': MODEL, 'page_chars': 6000, 'records': {}}
    if output['model'] != MODEL: raise ValueError('Model mismatch in existing answers')
    while True:
        picks = {'oracle': {qid: g['gold'] for qid,g in gold.items()}, 'no_context': {qid: [] for qid in gold}}
        sources = {}
        for name in methods:
            src = HERE / f'results/{name}.json'
            if not src.exists(): continue
            result = json.loads(src.read_text()); sources[name] = result
            ids = [r['id'] for r in result['rows']]
            if len(ids) != len(set(ids)): raise ValueError(f'{name}: duplicate IDs')
            for r in result['rows']:
                if r['id'] not in gold or r['gold'] != gold[r['id']]['gold'] or r['doc'] != gold[r['id']]['doc']:
                    raise ValueError(f'{name}: cohort/evidence mismatch')
            if name != args.gliner:
                deep_eval.validate_cohort({name: result}, gold)
            picks[name] = {r['id']: r['ranked'][:3] for r in result['rows']}
        for name, pages_by_id in picks.items():
            records = output['records'].setdefault(name, {})
            jobs = [(qid,pages) for qid,pages in pages_by_id.items() if qid not in records]
            def one(item):
                qid,pages = item; g = gold[qid]; texts,_ = load_doc(g['doc'])
                answer = deep_eval.answer(g['question'], pages, texts)
                correct = deep_eval.judge(g['question'], g['answer'], answer)
                return qid, {'pages': pages, 'answer': answer, 'correct': correct}
            if jobs:
                with cf.ThreadPoolExecutor(4) as ex:
                    for qid, record in ex.map(one, jobs):
                        records[qid] = record; path.write_text(json.dumps(output, indent=2))
                print(f'{name}: {len(records)}/{len(gold)} answers, correct {100 * st.mean(r["correct"] for r in records.values()):.1f}%', flush=True)
        complete = all(len(output['records'].get(name,{})) == len(gold) for name in ['oracle','no_context',*methods])
        if complete: break
        if not args.wait: raise SystemExit('GLiNER retrieval is incomplete; rerun with --wait or after it finishes')
        if sources.get(args.gliner, {}).get('failed'): raise SystemExit('GLiNER questions failed; no complete-cohort comparison')
        time.sleep(10)
    lines = ['| method | n | answer correct | hit@3 | median retrieval seconds | p95 seconds |', '|---|---|---|---|---|---|']
    for name in ['oracle','no_context',*methods]:
        records = output['records'][name]
        acc = st.mean(r['correct'] for r in records.values())
        if name in sources:
            rows = sources[name]['rows']; latency = sorted(r['latency'] for r in rows)
            h = f'{100 * st.mean(hit(r["ranked"],r["gold"],3) for r in rows):.1f}%'
            median = f'{st.median(latency):.3f}'; p95 = f'{latency[int(.95 * (len(latency)-1))]:.3f}'
        else: h = median = p95 = '-'
        lines.append(f'| {name} | {len(records)} | {100 * acc:.1f}% | {h} | {median} | {p95} |')
    gliner = sources[args.gliner]
    lines += ['', f'GLiNER revision: {gliner["metadata"]["revision"]}. Device: CPU. Precision: {gliner["metadata"]["precision"]}. Threads: {gliner["metadata"]["threads"]}. Batch: {gliner["metadata"]["batch_size"]}.',
              f'Model load: {gliner["load_sec"]:.2f}s, excluded from query latency. Process peak RSS sample: {gliner["peak_rss_mb"]:.0f} MiB. Stored parameters: {gliner["parameters"]:,}.',
              'GLiNER uses hybrid top-30 candidates, one query-selected snippet of at most 170 words per page, and binary softmax relevance. Every input is checked to fit 512 positions including its schema. It generates no tokens during retrieval.',
              f'Candidate hit@30: {100 * st.mean(r["candidate_hit30"] for r in gliner["rows"]):.1f}%.',
              'Answerer and judge are GLM-5.3-Flash. Same original prompts, 6000 characters per page, and 46 questions. Exact legacy cached responses are reused; new prompts use JSON response mode. Confidence intervals are question-level bootstrap and do not account for clustering within documents.',
              'Saved Kev/K2 timings used GPUs; GLiNER uses CPU. This is a deployment comparison, not a comparison on identical hardware. Original K2 Choice options were truncated by its server. Snippet-based GLiNER is not a full-page retrieval test.']
    diff = [int(output['records'][args.gliner][qid]['correct']) - int(output['records']['hybrid'][qid]['correct']) for qid in gold]
    lo,hi = bootstrap_ci(diff)
    lines.append(f'Paired answer-accuracy difference vs hybrid: {100 * st.mean(diff):+.1f} percentage points; bootstrap 95% CI [{100 * lo:+.1f}, {100 * hi:+.1f}].')
    report = HERE / f'results/{args.gliner}-comparison.md'; report.write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines), flush=True)


if __name__ == '__main__': main()
