"""Whole-bucket RAG benchmark. No gold metadata enters retrieval.
Run: uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/bucket_gpu_bench.py
Resume-safe HTTP caching; all page indexes in raw artifacts are zero-based.
"""
import os
os.environ['BENCH_DEVICE']='cuda'
os.environ['TOKENIZERS_PARALLELISM']='false'
import argparse, concurrent.futures as cf, hashlib, json, math, re, statistics as st, time
from pathlib import Path
import httpx, numpy as np, pymupdf, torch
from huggingface_hub import get_token
from transformers import AutoModel, AutoTokenizer
from gliner_cpu import CpuReranker, MODEL, REVISION, positive_score
from methods import BM25, snippet

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/bucket_gpu'; OUT.mkdir(exist_ok=True)
QWEN='Qwen/Qwen3.8-27B:deepinfra'
JUDGE='zai-org/GLM-5.3-Flash'
ROUTES=['qwen','gliner','combo','hybrid','oracle']

def save(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,indent=2)); tmp.replace(path)

def load_corpus():
    cache=ROOT/'cache/bucket_pages.json'
    manifest=json.loads((ROOT/'data/bucket_manifest.json').read_text())
    if cache.exists(): return json.loads(cache.read_text())
    pages=[]
    for name in sorted({q['doc_name'] for q in questions()}):
        with pymupdf.open(ROOT/f'pdfs/{name}.pdf') as pdf:
            for i,p in enumerate(pdf): pages.append({'doc':name,'page':i,'text':p.get_text()})
    save(cache,pages); return pages

def questions():return [json.loads(s) for s in (ROOT/'data/fb_bucket_current.jsonl').read_text().splitlines()]

def encode(model,tok,texts,batch=64):
    out=[]
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        for start in range(0,len(texts),batch):
            inputs=tok(texts[start:start+batch],padding=True,truncation=True,max_length=384,return_tensors='pt').to('cuda')
            vec=model(**inputs).last_hidden_state[:,0].float()
            out.append(torch.nn.functional.normalize(vec,dim=-1).cpu().numpy())
            if len(texts)>1000 and start%6400==0:print(f'Dense encoding {start}/{len(texts)}',flush=True)
    return np.concatenate(out)

def build_candidates(pages,qs):
    path=OUT/'candidates.json'
    if path.exists():return json.loads(path.read_text())
    started=time.perf_counter(); chunks=[]; owners=[]
    for i,p in enumerate(pages):
        text=p['text'] or '(blank)'
        for start in range(0,len(text),1300):
            chunks.append(p['doc'].replace('_',' ')+'\n'+text[start:start+1500]);owners.append(i)
    tok=AutoTokenizer.from_pretrained('BAAI/bge-small-en-v1.5')
    model=AutoModel.from_pretrained('BAAI/bge-small-en-v1.5').to('cuda').eval()
    vecpath=ROOT/'cache/bucket_bge384.npz'
    if vecpath.exists():
        data=np.load(vecpath);vec=data['vec'];assert np.array_equal(data['owners'],owners)
    else:
        vec=encode(model,tok,chunks);np.savez_compressed(vecpath,vec=vec,owners=np.array(owners))
    query_start=time.perf_counter()
    queries=encode(model,tok,['Represent this sentence for searching relevant passages: '+q['question'] for q in qs])
    query_encode_sec=(time.perf_counter()-query_start)/len(qs)
    bm=BM25([p['doc'].replace('_',' ')+'\n'+p['text'] for p in pages])
    index_sec=time.perf_counter()-started
    result={'index_sec':index_sec,'chunks':len(chunks),'pages':len(pages),'rows':{}}
    owners=np.array(owners)
    for q,qv in zip(qs,queries):
        t=time.perf_counter(); scores=np.full(len(pages),-np.inf);np.maximum.at(scores,owners,vec@qv)
        dense=np.argsort(-scores,kind='stable');lex=np.argsort(-np.array(bm.scores(q['question'])),kind='stable')
        rrf=np.zeros(len(pages))
        for order in [dense,lex]:rrf[order]+=1/(60+np.arange(1,len(pages)+1))
        ranked=np.argsort(-rrf,kind='stable')[:30].tolist()
        result['rows'][q['financebench_id']]={'ranked':ranked,'sec':time.perf_counter()-t+query_encode_sec}
    del model;torch.cuda.empty_cache();save(path,result);return result

class GpuReranker(CpuReranker):
    def __init__(self,batch=16):
        from gliner2 import AutoExtractor
        start=time.perf_counter()
        self.model=AutoExtractor.from_pretrained(MODEL,revision=REVISION,map_location='cpu').to('cuda').eval()
        self.model.classifier.register_forward_hook(lambda m,i,o:o.float())
        self.batch_size=batch;self.load_sec=time.perf_counter()-start
        self.params=sum(p.numel() for p in self.model.parameters())
        self.score(['Revenue was $100 million.'],self.tasks('What was revenue?'))
    def score(self,passages,tasks):
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            outputs=self.model.batch_classify_text(passages,tasks,batch_size=self.batch_size,include_confidence=True,max_len=None)
        torch.cuda.synchronize()
        if len(outputs)!=len(passages):raise ValueError('Missing GLiNER outputs')
        return [positive_score(x) for x in outputs]

def gliner_retrieve(pages,qs,candidates):
    path=OUT/'gliner.json';data=json.loads(path.read_text()) if path.exists() else {'rows':{}}
    if len(data['rows'])==len(qs):return data
    model=GpuReranker();torch.cuda.reset_peak_memory_stats()
    data.update(model=MODEL,revision=REVISION,params=model.params,load_sec=model.load_sec,precision='bf16',batch_size=16)
    for q in qs:
        qid=q['financebench_id']
        if qid in data['rows']:continue
        start=time.perf_counter();pool=candidates['rows'][qid]['ranked']
        tasks=model.tasks(q['question']);texts=[]
        for pid in pool:
            p=pages[pid];words=model.passages(p['text'],q['question'],'snippet')[0].split()
            prefix=f'{p["doc"]}, PDF page {p["page"]+1}: '
            while model.encoded_length(prefix+' '.join(words),tasks)>512:
                if not words:raise ValueError('Question and document metadata exceed context budget')
                words.pop()
            texts.append(prefix+' '.join(words))
        lengths=[model.encoded_length(t,tasks) for t in texts]
        t=time.perf_counter();scores=model.score(texts,tasks);infer=time.perf_counter()-t
        order=sorted(range(len(pool)),key=lambda i:-scores[i])
        data['rows'][qid]={'ranked':[pool[i] for i in order], 'scores':scores,'snippets':dict(zip(map(str,pool),texts)),
            'sec':time.perf_counter()-start,'infer_sec':infer,'input_positions':sum(lengths),'max_positions':max(lengths)}
        data['gpu_peak_allocated_mb']=torch.cuda.max_memory_allocated()/1024**2
        save(path,data)
        print(f'GLiNER GPU {len(data["rows"])}/{len(qs)} {data["rows"][qid]["sec"]:.3f}s',flush=True)
    del model;torch.cuda.empty_cache();return data

class Api:
    def __init__(self):
        token=get_token()
        if not token:raise RuntimeError('HF login token unavailable')
        self.client=httpx.Client(headers={'Authorization':'Bearer '+token},timeout=180)
        self.cache=ROOT/'cache/bucket_api';self.cache.mkdir(exist_ok=True)
    def call(self,model,prompt,max_tokens=1200,response_format=None):
        payload={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':max_tokens,'response_format':response_format or {'type':'json_object'}}
        if model.startswith('Qwen/'):payload['chat_template_kwargs']={'enable_thinking':False}
        key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();path=self.cache/f'{key}.json'
        if path.exists():return json.loads(path.read_text())
        for attempt in range(5):
            t=time.perf_counter()
            try:
                response=self.client.post('https://router.huggingface.co/v1/chat/completions',json=payload)
                response.raise_for_status();raw=response.json();content=raw['choices'][0]['message']['content']
                value=json.loads(content)
                if not isinstance(value,dict):raise ValueError('Expected JSON object')
                result={'value':value,'sec':time.perf_counter()-t,'usage':raw['usage'],'model':raw['model'],'finish_reason':raw['choices'][0]['finish_reason']}
                save(path,result);return result
            except Exception as exc:
                if attempt==4:raise RuntimeError(f'{model}: {type(exc).__name__}: {str(exc)[:250]}') from exc
                time.sleep(min(2**attempt,8))


def qwen_rank(api,q,pool,snippets):
    # Local IDs prevent hallucinated global document/page identifiers.
    ctx='\n\n'.join(f'Candidate {i}: {p["doc"]}, PDF page {p["page"]+1}\n{snippets[str(pid)]}' for i,pid in enumerate(pool) for p in [PAGES[pid]])
    prompt='Rank the candidate financial-report pages by usefulness for answering the question. Prefer pages containing the needed figures, statements, and dates. Do not answer. Return JSON {"ranked":[candidate IDs, best first]}, up to 10 unique IDs.\nQuestion: '+q['question']+'\n\n'+ctx
    attempts=[]
    for attempt in range(4):
        response_format=None
        if attempt==3:
            response_format={'type':'json_schema','json_schema':{'name':'page_ranking','strict':True,'schema':{'type':'object','properties':{'ranked':{'type':'array','items':{'type':'integer','enum':list(range(len(pool)))},'minItems':1,'maxItems':10}},'required':['ranked'],'additionalProperties':False}}}
        result=api.call(QWEN,prompt,600,response_format=response_format);attempts.append(result)
        order=result['value'].get('ranked')
        if isinstance(order,list):
            order=[int(x) if isinstance(x,str) and x.isdecimal() else x for x in order]
        if isinstance(order,list) and order and all(type(x)==int and 0<=x<len(pool) for x in order) and len(set(order))==len(order):break
        prompt+=f'\nIMPORTANT: Use integer candidate IDs from 0 to {len(pool)-1}, never document names or PDF page numbers. Output at most 10 unique integers in the ranked array. This is retry {attempt+1}.'
    else:raise ValueError('Invalid Qwen ranking after schema repair')
    usage={key:sum(a['usage'].get(key,0) for a in attempts) for key in ['prompt_tokens','completion_tokens','estimated_cost']}
    return {'ranked':[pool[x] for x in order[:10]],'sec':sum(a['sec'] for a in attempts),'usage':usage,'model':result['model'],'schema_repairs':len(attempts)-1}

def read_and_judge(api,q,ranked):
    ctx='\n\n'.join(f'[{p["doc"]} PDF page {p["page"]+1}]\n{p["text"][:6000]}' for pid in ranked[:3] for p in [PAGES[pid]])
    answer=api.call(QWEN,'Use only the supplied report pages to answer the question. Calculate if needed and give units. If evidence is insufficient, state that. Cite the supplied document and PDF page. Return JSON {"answer":"...","sufficient":true or false}.\nQuestion: '+q['question']+'\n\n'+ctx,1400)
    value=answer['value']
    if not isinstance(value.get('answer'),str) or type(value.get('sufficient'))!=bool:raise ValueError('Invalid answer output')
    judge=api.call(JUDGE,'Assess only whether the candidate factual claims are supported by the supplied context. A justified refusal may be grounded even though it does not answer the question. Return JSON {"grounded":true or false,"reason":"brief reason"}.\nQuestion: '+q['question']+'\nCandidate: '+value['answer']+'\nContext:\n'+ctx,1800)
    if type(judge['value'].get('grounded'))!=bool:raise ValueError('Invalid groundedness judgment')
    return {'answer':answer,'context_judge':judge,'correctness_judge':reference_judge(api,q,value['answer']),'context_chars':len(ctx),'context_words':len(ctx.split())}

def reference_judge(api,q,answer):
    result=api.call(JUDGE,'Grade whether the candidate actually answers the question consistently with the GOLD REFERENCE. This is answer correctness, independent of retrieved context. The reference is the target. A refusal, "insufficient evidence", or missing information is INCORRECT when the reference provides concrete facts or figures, even if refusal would be sensible given poor retrieval. If the reference itself says a metric is not meaningful, a matching explanation can be correct. Ignore formatting and rounding within 1%. Return JSON {"correct":true or false,"reason":"brief comparison to reference"}.\nQuestion: '+q['question']+'\nGOLD REFERENCE: '+q['answer']+'\nCANDIDATE: '+answer,1200)
    if type(result['value'].get('correct'))!=bool:raise ValueError('Invalid reference-only correctness grade')
    return result

def reference_regrade(qs,data,workers):
    if len(data['rows'])!=len(qs) or data['errors']:raise RuntimeError('Complete retrieval/answer cohort required before regrading')
    data['grading_protocol']='Correctness: reference-only. Groundedness: context-aware. Discarded context-aware correctness grades are not used.'
    for row in data['rows'].values():
        for m in row['methods'].values():
            if 'judge' in m:m['context_judge']=m.pop('judge')
            context=m['context_judge']
            if 'correct' in context['value']:context['discarded_context_aware_correctness']=context['value'].pop('correct')
    save(OUT/'evaluation.json',data)
    api=Api();remaining=[q for q in qs if any('correctness_judge' not in data['rows'][q['financebench_id']]['methods'][route] for route in ROUTES)]
    def one(q):
        row=data['rows'][q['financebench_id']]
        grades={route:reference_judge(api,q,row['methods'][route]['answer']['value']['answer']) for route in ROUTES if 'correctness_judge' not in row['methods'][route]}
        return q['financebench_id'],grades
    with cf.ThreadPoolExecutor(workers) as ex:
        for i,(qid,grades) in enumerate(ex.map(one,remaining),1):
            for route,grade in grades.items():data['rows'][qid]['methods'][route]['correctness_judge']=grade
            save(OUT/'evaluation.json',data)
            print(f'Reference-only regrade {i}/{len(remaining)}',flush=True)
    return data

PAGES=[]
def evaluate(pages,qs,candidates,gliner,workers):
    global PAGES;PAGES=pages
    api=Api();path=OUT/'evaluation.json';data=json.loads(path.read_text()) if path.exists() else {'rows':{},'errors':{}}
    lookup={(p['doc'],p['page']):i for i,p in enumerate(pages)}
    # Two dataset rows repeat the same evidence page. The oracle should receive unique pages.
    old_oracles={}
    for q in qs:
        qid=q['financebench_id'];existing=data['rows'].get(qid)
        if existing and len(set(existing['gold']))!=len(existing['gold']):
            old_oracles[qid]=existing['methods']['oracle']
            existing['gold']=list(dict.fromkeys(existing['gold']))
            existing['methods']['oracle']={'retrieval':{'ranked':existing['gold'],'sec':0,'usage':{}},**read_and_judge(api,q,existing['gold'])}
    if old_oracles:
        save(OUT/'oracle_duplicates_before_fix.json',old_oracles);save(path,data)
    def one(q):
        qid=q['financebench_id'];pool=candidates['rows'][qid]['ranked'];g=gliner['rows'][qid]
        row={'id':qid,'question':q['question'],'gold':list(dict.fromkeys(lookup[(e['doc_name'],e['evidence_page_num'])] for e in q['evidence'])),'methods':{}}
        rankings={'qwen':qwen_rank(api,q,pool,g['snippets']),'gliner':{'ranked':g['ranked'],'sec':g['sec'],'usage':{}},
                  'combo':qwen_rank(api,q,g['ranked'][:10],g['snippets']),
                  'hybrid':{'ranked':pool,'sec':0,'usage':{}},'oracle':{'ranked':row['gold'],'sec':0,'usage':{}}}
        for route in ROUTES:
            rank=rankings[route]
            evaluated=read_and_judge(api,q,rank['ranked'])
            # Shared exact requests are intentionally cached; per-route production costs remain counted.
            row['methods'][route]={'retrieval':rank,**evaluated}
        return row
    remaining=[q for q in qs if q['financebench_id'] not in data['rows']]
    with cf.ThreadPoolExecutor(workers) as ex:
        futures={ex.submit(one,q):q['financebench_id'] for q in remaining}
        for f in cf.as_completed(futures):
            qid=futures[f]
            try:data['rows'][qid]=f.result();data['errors'].pop(qid,None);print(f'Qwen/eval {len(data["rows"])}/{len(qs)}',flush=True)
            except Exception as exc:data['errors'][qid]=repr(exc);print(f'FAILED {qid}: {exc}',flush=True)
            save(path,data)
    return data

def wilson(values):
    n=len(values);p=st.mean(values);z=1.96;d=1+z*z/n;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;c=(p+z*z/(2*n))/d
    return [100*(c-h),100*(c+h)]
def norm(s):return re.sub(r'\W+','',s.lower())
def summarize(pages,qs,candidates,gliner,evaluated):
    if len(evaluated['rows'])!=len(qs) or evaluated['errors']:raise RuntimeError('Incomplete cohort; resume before drawing conclusions')
    rows=list(evaluated['rows'].values());byid={q['financebench_id']:q for q in qs};summary={}
    def hit(ranked,gold,k):return bool(set(ranked[:k])&set(gold))
    for route in ROUTES:
        vals=[]
        for row in rows:
            m=row['methods'][route];rank=m['retrieval'];picks=rank['ranked'];g=row['gold'];qid=row['id']
            ru=rank['usage'];au=m['answer']['usage'];jud={**m['context_judge']['value'],'correct':m['correctness_judge']['value']['correct']};q=byid[qid]
            retrieval_sec=candidates['rows'][qid]['sec']+rank['sec']+(gliner['rows'][qid]['sec'] if route=='combo' else 0)
            if route=='oracle':retrieval_sec=0.0
            docs=list(dict.fromkeys(pages[p]['doc'] for p in picks));gold_docs={pages[p]['doc'] for p in g}
            first=next((i+1 for i,p in enumerate(picks) if p in g),None)
            texts=[norm(pages[p]['text'][:6000]) for p in picks[:3]]
            evidence=st.mean(any(norm(e['evidence_text']) in text for text in texts) for e in q['evidence'])
            vals.append({'correct':jud['correct'],'grounded':jud['grounded'],'hit3':hit(picks,g,3),'hit1':hit(picks,g,1),'hit10':hit(picks,g,10),
                'doc_hit3':any(pages[p]['doc'] in gold_docs for p in picks[:3]),'distinct_doc_hit3':bool(set(docs[:3])&gold_docs),'doc_hit1':docs[0] in gold_docs,'mrr10':1/first if first else 0,
                'ndcg3':sum(1/math.log2(i+2) for i,p in enumerate(picks[:3]) if p in g)/sum(1/math.log2(i+2) for i in range(min(3,len(set(g))))),
                'precision3':len(set(picks[:3])&set(g))/len(picks[:3]),'evidence_coverage':evidence,'retrieval_sec':retrieval_sec,
                'endtoend_sec':retrieval_sec+m['answer']['sec'],'context_words':m['context_words'],
                'retrieval_input':ru.get('prompt_tokens',0),'retrieval_output':ru.get('completion_tokens',0),
                'generation_input':au['prompt_tokens'],'generation_output':au['completion_tokens'],
                'generation_sec':m['answer']['sec'],'abstained':not m['answer']['value']['sufficient'],
                'confident_wrong':m['answer']['value']['sufficient'] and not jud['correct'],
                'schema_repairs':rank.get('schema_repairs',0),
                'retrieval_cost':ru.get('estimated_cost',0),'generation_cost':au.get('estimated_cost',0)})
        stats={k:st.mean(v[k] for v in vals) for k in vals[0]}
        stats['accuracy95']=wilson([v['correct'] for v in vals]);stats['retrieval_p95']=float(np.percentile([v['retrieval_sec'] for v in vals],95))
        stats['retrieval_median']=st.median(v['retrieval_sec'] for v in vals);stats['endtoend_median']=st.median(v['endtoend_sec'] for v in vals)
        summary[route]=stats
    meta={'n':len(qs),'docs':len({p['doc'] for p in pages}),'pages':len(pages),'bucket_sha256':hashlib.sha256((ROOT/'data/fb_bucket_current.jsonl').read_bytes()).hexdigest(),
          'question_fields_used_for_retrieval':['question'],'candidate_pool':30,'candidate_hit30':st.mean(hit(candidates['rows'][r['id']]['ranked'],r['gold'],30) for r in rows),
        'index_sec':candidates['index_sec'],'gliner':{k:v for k,v in gliner.items() if k!='rows'},'qwen':QWEN,'judge':JUDGE,
        'correctness_protocol':'Reference-only judge; no retrieved context. Context-groundedness is a separate score.',
          'reader_page_limit':3,'reader_chars_per_page':6000,'rank_input':'same query-centered bounded passage per page; GLiNER <=512 schema+text positions',
          'combo':'GLiNER top10 -> Qwen rerank','qwen_thinking':False,'gpu':torch.cuda.get_device_name(),'local_gpu_cost':'API cost zero; hardware/electricity excluded',
          'speed_note':'Warm GLiNER; HTTP wall latency observed under 6 concurrent question workers. No judge latency or cost included in production metrics.'}
    paired={}
    rng=np.random.default_rng(42)
    for a,b in [('qwen','gliner'),('qwen','combo'),('combo','gliner'),('gliner','hybrid'),('combo','hybrid')]:
        av=np.array([r['methods'][a]['correctness_judge']['value']['correct'] for r in rows],dtype=int)
        bv=np.array([r['methods'][b]['correctness_judge']['value']['correct'] for r in rows],dtype=int)
        delta=av-bv;boots=np.mean(delta[rng.integers(0,len(rows),size=(5000,len(rows)))],axis=1)
        wins=int(np.sum((av==1)&(bv==0)));losses=int(np.sum((av==0)&(bv==1)));n=wins+losses
        p=min(1,2*sum(math.comb(n,k) for k in range(min(wins,losses)+1))/2**n) if n else 1
        paired[f'{a}_minus_{b}']={'accuracy_delta_points':float(delta.mean()*100),'paired_bootstrap95_points':(np.percentile(boots,[2.5,97.5])*100).tolist(),'wins':wins,'losses':losses,'mcnemar_exact_p':p}
    meta['versions']={}
    import importlib.metadata
    for package in ['torch','gliner2','transformers','huggingface_hub']:meta['versions'][package]=importlib.metadata.version(package)
    meta['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    meta['pdf_manifest_sha256']=hashlib.sha256((ROOT/'data/bucket_manifest.json').read_bytes()).hexdigest()
    api_records=[json.loads(p.read_text()) for p in (ROOT/'cache/bucket_api').glob('*.json')]
    meta['unique_successful_qwen_requests']=sum(r['model'].startswith('Qwen/') for r in api_records)
    meta['unique_successful_qwen_estimated_cost_usd']=sum(r['usage'].get('estimated_cost',0) for r in api_records if r['model'].startswith('Qwen/'))
    save(OUT/'summary.json',{'metadata':meta,'methods':summary,'paired':paired})
    lines=['# Whole-bucket RAG comparison','',f'{len(qs)} questions, {meta["docs"]} documents, {len(pages):,} pages. Candidate recall@30: {100*meta["candidate_hit30"]:.1f}%.','',
           '| Retrieval route | Answer correct (95% CI) | Page hit@3 | Doc hit@3 | Evidence coverage | Grounded | Retrieval median / p95 (s) | End-to-end median (s) | API $ / 1k retrievals | API $ / 1k answered queries |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for route,s in summary.items():
        lo,hi=s['accuracy95'];lines.append(f'| {route} | {s["correct"]*100:.1f}% ({lo:.1f}–{hi:.1f}) | {s["hit3"]*100:.1f}% | {s["doc_hit3"]*100:.1f}% | {s["evidence_coverage"]*100:.1f}% | {s["grounded"]*100:.1f}% | {s["retrieval_median"]:.2f} / {s["retrieval_p95"]:.2f} | {s["endtoend_median"]:.2f} | {s["retrieval_cost"]*1000:.3f} | {(s["retrieval_cost"]+s["generation_cost"])*1000:.3f} |')
    lines += ['', 'All routes search the full corpus from the original question only, with no gold document filter. A shared BGE-small + BM25 reciprocal-rank pool supplies 30 pages. Qwen reranks all 30; GLiNER scores relevance independently; combo lets Qwen rerank GLiNER’s top 10. Hybrid and oracle are controls.', '',
        'GLiNER is an evidence selector, so its standalone quality is page/document relevance. Answer accuracy above uses the same Qwen3.8-27B reader for every route and an independent GLM-5.3-Flash judge. Correctness is judged from question, reference and candidate answer only. Groundedness is assessed separately with the retrieved context. Oracle measures the reader ceiling. GLiNER alone does not generate answers.', '',
        'Costs use the HF router’s returned estimated_cost, not an invoice; retrieval and generation are separated. Offline indexing, judge calls, GPU hardware and electricity are excluded. Latencies are warm observed wall times under concurrent API load; they are not controlled hardware comparisons.', '',
        'Exact gold page hits and evidence coverage are strict: repeated evidence elsewhere can still yield correct answers. Document hit@3 means the gold document occurs within the three pages given to the reader. Evidence coverage is normalized verbatim evidence found within those provided page excerpts. Groundedness is model-judged, not human audited. Confidence intervals measure binomial sampling uncertainty, not judge bias.', '',
        f'GPU: {meta["gpu"]}; GLiNER BF16, batch 16, peak allocated {gliner["gpu_peak_allocated_mb"]:.0f} MB. Offline index {meta["index_sec"]:.1f}s.', '',
        'Raw rankings, answers, judgments, token usage and costs: evaluation.json. Page catalog: ../../cache/bucket_pages.json (zero-based pages). Rerun command: `uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/bucket_gpu_bench.py`.' ]
    lines += ['', '| Route | Page hit@1 / @10 | MRR@10 | nDCG@3 | Gold-page precision@3 | Context words | Retrieval input / output tokens | Reader input / output tokens | Reader flagged insufficient | Confident but wrong |',
        '|---|---|---|---|---|---|---|---|---|---|']
    for route,s in summary.items():
        lines.append(f'| {route} | {s["hit1"]*100:.1f}% / {s["hit10"]*100:.1f}% | {s["mrr10"]:.3f} | {s["ndcg3"]:.3f} | {s["precision3"]*100:.1f}% | {s["context_words"]:.0f} | {s["retrieval_input"]:.0f} / {s["retrieval_output"]:.0f} | {s["generation_input"]:.0f} / {s["generation_output"]:.0f} | {s["abstained"]*100:.1f}% | {s["confident_wrong"]*100:.1f}% |')
    lines += ['', 'Precision and nDCG use the annotated gold pages as binary relevance labels. They can penalize other pages with equivalent evidence. Context and token counts are per-query means. The insufficient flag is the reader’s self-report and may accompany a partial answer. Confident but wrong means the reader marked evidence sufficient but the reference-only judge rejected its answer.', '', '| Paired comparison | Accuracy difference | Paired bootstrap 95% CI | Wins / losses | Exact McNemar p |','|---|---|---|---|---|']
    for comparison,p in paired.items():
        lo,hi=p['paired_bootstrap95_points'];lines.append(f'| {comparison} | {p["accuracy_delta_points"]:.1f} points | {lo:.1f} to {hi:.1f} | {p["wins"]} / {p["losses"]} | {p["mcnemar_exact_p"]:.3g} |')
    lines += ['', '| Route | Questions requiring ranking-format repair | Mean ranking repair calls |','|---|---|---|']
    for route in ['qwen','combo']:
        count=sum(r['methods'][route]['retrieval'].get('schema_repairs',0)>0 for r in rows)
        lines.append(f'| {route} | {count}/{len(rows)} | {summary[route]["schema_repairs"]:.2f} |')
    lines += ['', 'Ranking format repairs are charged to retrieval and included in latency. Numeric strings are normalized to integer candidate IDs. Document names and out-of-range or duplicate IDs are rejected; the final repair uses a strict integer-enum JSON schema. Using that schema on the first request is a production optimization not timed here.']
    lines += ['', 'Paired comparisons use the same 150 questions, with no multiplicity correction. Judge uncertainty is not included. This benchmark tests reranking, not a Qwen tree traverser and not GLiNER scanning every page. The shared first-stage retriever is part of every practical route.', '',
        f'The HF router returned estimated prices totaling ${meta["unique_successful_qwen_estimated_cost_usd"]:.4f} across {meta["unique_successful_qwen_requests"]} distinct successful Qwen requests in this benchmark cache, including controls and schema repairs. GLM evaluation calls and unsuccessful HTTP attempts are excluded. This is not an invoice.', '',
        'Model documentation: [GLiNER2.5-Decide](https://huggingface.co/fastino/GLiNER2.5-Decide), [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B). [DeepInfra pricing](https://deepinfra.com/Qwen/Qwen3.8-27B). GPU batch sweep: gpu_batch_probe.json.' ]
    requested=['# Requested system configurations','', '| System | Answer accuracy | Page hit@3 | Doc hit@3 | Median evidence selection (s) | Median full answer (s) | API $ / 1,000 queries |','|---|---|---|---|---|---|---|']
    for label,route,reader in [('Qwen retrieval + Qwen answer','qwen',True),('GLiNER evidence selection only','gliner',False),('GLiNER selection + Qwen answer','gliner',True),('GLiNER selection + Qwen rerank + Qwen answer','combo',True)]:
        s=summary[route];acc=f'{s["correct"]*100:.1f}%' if reader else 'N/A';lat=f'{s["endtoend_median"]:.2f}' if reader else 'N/A';cost=(s['retrieval_cost']+s['generation_cost']) if reader else s['retrieval_cost']
        requested.append(f'| {label} | {acc} | {s["hit3"]*100:.1f}% | {s["doc_hit3"]*100:.1f}% | {s["retrieval_median"]:.2f} | {lat} | {cost*1000:.3f} |')
    requested+=['','The fourth row tests an additional Qwen reranking step beyond the simple GLiNER + Qwen reader combination. GLiNER alone only selects evidence. Detailed controlled comparisons and methodology follow.','']
    (OUT/'report.md').write_text('\n'.join(requested+lines)+'\n')
    print('\n'.join(lines[:12]),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['all','retrieve','evaluate','report'],default='all');ap.add_argument('--workers',type=int,default=6);args=ap.parse_args()
    torch.set_num_threads(4);torch.set_float32_matmul_precision('high')
    qs=questions();pages=load_corpus();print(f'Corpus {len(qs)} questions / {len(pages)} pages',flush=True)
    candidates=build_candidates(pages,qs);gliner=gliner_retrieve(pages,qs,candidates)
    if args.stage=='retrieve':return
    if args.stage=='report':evaluated=json.loads((OUT/'evaluation.json').read_text())
    else:evaluated=evaluate(pages,qs,candidates,gliner,args.workers)
    evaluated=reference_regrade(qs,evaluated,args.workers)
    summarize(pages,qs,candidates,gliner,evaluated)
if __name__=='__main__':main()
