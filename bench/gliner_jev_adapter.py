"""Execute upstream jev-doc-search functions unchanged with a GLiNER client shim.
Apache-2.0 upstream: VectifyAI/jev-doc-search, revision 7b1008c437c8c9a88da8a427a76052fb0454977a.
Native described-label categorical classification when it fits GLiNER's encoder;
otherwise full-coverage binary chunks mapped to a normalized Choice distribution.
"""
import hashlib,json,math,re,threading,time,types
from pathlib import Path
import numpy as np,torch
from bucket_gpu_bench import GpuReranker
from typesafe_sdk import Choice, Noul
from jev_reference import reference

REFERENCE=Path(__file__).resolve().parent/'reference/jev-doc-search/tree_search.py'
def reference_module(client):
    module=reference(client)
    module.source_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    return module

class LocalPageIndexClient:
    def __init__(self,tree,texts):self.tree=tree;self.texts=texts
    def get_document_structure(self,doc_id):return self.tree
    def get_page_content(self,doc_id,selector):
        return [{'page_index':int(p),'markdown':self.texts[int(p)-1]} for p in selector.split(',')]

class GLiNERClient:
    def __init__(self,engine=None,max_context=4096):
        self.engine=engine or GpuReranker(batch=8);self.max_context=max_context;self.lock=threading.Lock();self.set_document('',[])
    def set_document(self,name,tree,texts=None):
        self.doc=name;self.paths={};self.page_paths={};self.summaries={};self.events=[]
        self.page_lookup={hashlib.sha256(t[:60000].encode()).hexdigest():i+1 for i,t in enumerate(texts or [])}
        def visit(nodes,path):
            for n in nodes:
                current=path+[n['title']];self.paths[n['node_id']]=current
                self.summaries[tuple(current)]=n.get('summary','')
                # Parent context also covers opening pages; children overwrite
                # their own ranges with the more specific hierarchy below.
                for p in range(n['start_index'],n['end_index']+1):self.page_paths[p]=current
                if n.get('nodes'):visit(n['nodes'],current)
        visit(tree,[])
    def path_for(self,key):
        if key.startswith('p') and key[1:].isdigit():return self.page_paths.get(int(key[1:]),[])
        return self.paths.get(key.split(':opening')[0],[])
    @staticmethod
    def common_path(paths):
        if not paths:return []
        out=[]
        for values in zip(*paths):
            if len(set(values))!=1:break
            out.append(values[0])
        return out
    def tasks(self,q,instructions):
        return {'relevance':{'labels':['yes','no'],'prompt':f'{instructions} Is this candidate relevant to answering the question: {q}', 'multi_label':True,'cls_threshold':0.,'class_act':'softmax'}}
    def context_summary(self,path):
        # Query-independent parent context, bounded separately from candidate
        # coverage. Keep two nearest ancestor summaries at thirty words each.
        return ' '.join(' '.join(self.summaries.get(tuple(path[:i]),'').split()[:30])
                        for i in range(max(1,len(path)-1),len(path)+1))
    def chunks(self,q,instructions,key,body):
        tasks=self.tasks(q,instructions);hierarchy=self.path_for(key);path=' > '.join(t[:100] for t in hierarchy)
        prefix=f'Document: {self.doc}\nHierarchy: {path}\nSection context: {self.context_summary(hierarchy)}\nCandidate:\n'
        spans=list(re.finditer(r'\S+',body or '(blank)'));out=[];start=0
        while start<len(spans):
            end=min(start+160,len(spans))
            while end>start:
                text=prefix+(body or '(blank)')[spans[start].start():spans[end-1].end()]
                if self.engine.encoded_length(text,tasks)<=512:break
                end-=1
            if end<=start:raise ValueError('Hierarchy and task do not fit the GLiNER encoder')
            out.append(text)
            if end==len(spans):break
            start=max(start+1,end-24)
        return out,tasks
    def binary_many(self,q,instructions,options):
        texts=[];owners=[];tasks=None
        for key,body in options.items():
            chunks,tasks=self.chunks(q,instructions,key,body);texts+=chunks;owners += [key]*len(chunks)
        lengths=[self.engine.encoded_length(t,tasks) for t in texts]
        scores=self.engine.score(texts,tasks);best={key:0. for key in options}
        for key,s in zip(owners,scores):best[key]=max(best[key],s)
        return best,sum(lengths),len(texts)
    def categorical(self,q,instructions,options):
        # Use semantic label names, as in the model's described-label API.
        # Opaque PageIndex IDs are returned to the traversal after inference.
        aliases={f"{str(body).split('. ',1)[0][:100]} [candidate {i}]":key
                 for i,(key,body) in enumerate(options.items())}
        labels={label:options[key] for label,key in aliases.items()}
        tasks={'pick':{'labels':labels,'prompt':instructions,'multi_label':True,'cls_threshold':0.,'class_act':'softmax'}}
        hierarchy=self.common_path([self.path_for(k) for k in options])
        state=f"Question: {q}\nDocument: {self.doc}\nCurrent section: {' > '.join(hierarchy)}\nSection context: {self.context_summary(hierarchy)}"
        n=self.engine.encoded_length(state,tasks)
        # DeBERTa's relative positions permit longer inputs. The configured
        # GPU budget is explicit; it is not a claimed 512-token hard limit.
        if n>self.max_context:return None
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            result=self.engine.model.batch_classify_text([state],tasks,batch_size=1,include_confidence=True,max_len=None)[0]
        torch.cuda.synchronize();probs={aliases[r['label']]:float(r['confidence']) for r in result['pick']}
        self.validate(probs,options);return probs,n,1
    @staticmethod
    def validate(probs,options):
        if set(probs)!=set(options) or any(not math.isfinite(p) or p<0 or p>1 for p in probs.values()) or abs(sum(probs.values())-1)>.01:raise ValueError('Invalid categorical probabilities')
    def system_one(self,*,state,questions):
        with self.lock:
            started=time.perf_counter();answers={};used=0
            for name,task in questions.items():
                q=state['question']
                if isinstance(task,Choice):
                    native=self.categorical(q,task.instructions,task.criteria)
                    if native is None:
                        scores,n,chunks=self.binary_many(q,task.instructions,task.criteria)
                        logits=np.array([math.log(max(min(p,1-1e-6),1e-6)/(1-max(min(p,1-1e-6),1e-6))) for p in scores.values()]);weights=np.exp(logits-logits.max());probs=dict(zip(scores,(weights/weights.sum()).tolist()));mode='chunked_binary_odds'
                    else:probs,n,chunks=native;mode='native_categorical'
                    self.validate(probs,task.criteria);answers[name]=types.SimpleNamespace(probabilities=probs)
                else:
                    page=self.page_lookup.get(hashlib.sha256(state['page'].encode()).hexdigest(),0)
                    scores,n,chunks=self.binary_many(q,task.instructions,{'p'+str(page):state['page']})
                    answers[name]=types.SimpleNamespace(noul=next(iter(scores.values())));mode='chunked_binary_verify'
                used+=n;self.events.append({'mode':mode,'inputs':chunks,'positions':n,'sec':time.perf_counter()-started})
            return types.SimpleNamespace(answers=answers,usage=types.SimpleNamespace(input_tokens=used))
