"""Warm batch-size sweep on ten fixed bucket queries, without API calls."""
import json,time,statistics
import torch
from bucket_gpu_bench import GpuReranker,OUT,questions
m=GpuReranker();data=json.loads((OUT/'gliner.json').read_text());qs=questions()[::15];results={};reference=None
for batch in [8,16,32]:
    m.batch_size=batch;times=[];scores=[];torch.cuda.reset_peak_memory_stats()
    for q in qs:
        r=data['rows'][q['financebench_id']];texts=[r['snippets'][str(p)] for p in r['ranked']]
        tasks=m.tasks(q['question']);m.score(texts,tasks)
        t=time.perf_counter();s=m.score(texts,tasks);times.append(time.perf_counter()-t);scores.extend(s)
    if reference is None:reference=scores
    results[str(batch)]={'median_inference_sec':statistics.median(times),'mean_inference_sec':statistics.mean(times),'peak_mb':torch.cuda.max_memory_allocated()/1024**2,'max_score_difference':max(abs(a-b) for a,b in zip(scores,reference))}
    print(batch,results[str(batch)],flush=True)
(OUT/'gpu_batch_probe.json').write_text(json.dumps({'n':len(qs),'results':results},indent=2))
