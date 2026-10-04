"""Build genuine official PageIndex Flash trees locally, with HF-backed indexing.
Only the credential loader and LLM transport/token counting are replaced.
"""
import argparse,ast,asyncio,concurrent.futures as cf,hashlib,importlib,json,os,sys,threading,time,types,uuid
from pathlib import Path
import httpx,tiktoken
from huggingface_hub import get_token
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'reference/PageIndex/pageindex'
OUT=ROOT/'data/pageindex';OUT.mkdir(exist_ok=True)
MODEL='Qwen/Qwen3.8-27B:deepinfra'

class TextApi:
    def __init__(self):
        self.client=httpx.Client(headers={'Authorization':'Bearer '+get_token()},timeout=180)
        self.gate=threading.BoundedSemaphore(4);self.cache=ROOT/'cache/pageindex_api';self.cache.mkdir(exist_ok=True)
    def call(self,prompt,history=None):
        payload={'model':MODEL,'messages':(history or [])+[{'role':'user','content':prompt}],'temperature':0,'max_tokens':8000,'chat_template_kwargs':{'enable_thinking':False}}
        key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();path=self.cache/f'{key}.json'
        if path.exists():return json.loads(path.read_text())
        with self.gate:
            if path.exists():return json.loads(path.read_text())
            for attempt in range(5):
                t=time.perf_counter()
                try:
                    r=self.client.post('https://router.huggingface.co/v1/chat/completions',json=payload);r.raise_for_status();raw=r.json();ch=raw['choices'][0]
                    if ch['finish_reason']=='length':payload['max_tokens']*=2;continue
                    value={'text':ch['message']['content'],'usage':raw['usage'],'sec':time.perf_counter()-t,'finish_reason':'finished'}
                    if not value['text']:raise ValueError('Empty indexing response')
                    tmp=path.with_suffix(f'.{uuid.uuid4().hex}.tmp');tmp.write_text(json.dumps(value));tmp.replace(path);return value
                except Exception:
                    if attempt==4:raise
                    time.sleep(min(2**attempt,8))
            raise ValueError('Indexing completion exceeded output limit')

_API=None

def runtime():
    global _API
    if 'pageindex.utils' in sys.modules:return
    package=types.ModuleType('pageindex');package.__path__=[str(SOURCE)];sys.modules['pageindex']=package
    path=SOURCE/'utils.py';parsed=ast.parse(path.read_text())
    # Never execute the upstream automatic .env read.
    parsed.body=[n for n in parsed.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='load_dotenv')]
    mod=types.ModuleType('pageindex.utils');mod.__file__=str(path);mod.__package__='pageindex';sys.modules[mod.__name__]=mod
    exec(compile(parsed,str(path),'exec'),mod.__dict__)
    _API=TextApi();enc=tiktoken.get_encoding('o200k_base')
    mod.count_tokens=lambda text,model=None:len(enc.encode(text or ''))
    async def acompletion(model,prompt):return (await asyncio.to_thread(_API.call,prompt))['text']
    def completion(model,prompt,chat_history=None,return_finish_reason=False):
        r=_API.call(prompt,chat_history);return (r['text'],r['finish_reason']) if return_finish_reason else r['text']
    mod.llm_acompletion=acompletion;mod.llm_completion=completion
    # Parser output is identical with one worker. The AST namespace cannot be
    # imported by Flash's spawned children, so use its documented serial path.
    from pageindex.flash import api as flash_api
    extract = flash_api.extract_toc
    def extract_serial(pdf, **kwargs):
        return extract(pdf, workers=1, **kwargs)
    flash_api.extract_toc = extract_serial


def build(doc,index_mode='flash'):
    directory=OUT if index_mode=='flash' else ROOT/'data/pageindex_classic'
    directory.mkdir(exist_ok=True)
    path=directory/f'{doc}.json';pdf=ROOT/f'pdfs/{doc}.pdf';digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
    if path.exists():
        old=json.loads(path.read_text())
        if old['metadata']['pdf_sha256']!=digest:raise ValueError('Stale PageIndex file')
        return doc,'cached'
    runtime()
    from pageindex.flash import page_index_flash
    from pageindex.flash.api import flash_rejection_reason
    start=time.perf_counter()
    if index_mode=='classic':
        result=None;reason='Explicit model-built classic PageIndex'
    else:
        result=page_index_flash(str(pdf),summary=True,optimize='full',summary_model=MODEL,optimize_model=MODEL,summary_max_words=60,summary_concurrency=4)
        reason=flash_rejection_reason(result)
    if reason:
        from pageindex import page_index_classic as classic
        from pageindex.utils import ConfigLoader
        # Upstream otherwise adds a None page offset and crashes before its
        # existing no-page-number fallback can run. Do not invent an offset.
        if not getattr(classic,'_benchmark_offset_guard',False):
            class MissingOffset(ValueError):pass
            original_offset=classic.calculate_page_offset
            original_process=classic.process_toc_with_page_numbers
            def checked_offset(pairs):
                offset=original_offset(pairs)
                if offset is None:raise MissingOffset('No reliable physical-page offset')
                return offset
            def guarded_process(toc_content,toc_page_list,page_list,toc_check_page_num=None,model=None,logger=None):
                try:return original_process(toc_content,toc_page_list,page_list,toc_check_page_num,model,logger)
                except MissingOffset:
                    logger.info({'fallback':'No physical-page offset; use official no-page-number indexing'})
                    return classic.process_toc_no_page_numbers(toc_content,toc_page_list,page_list,model=model,logger=logger)
            classic.calculate_page_offset=checked_offset
            classic.process_toc_with_page_numbers=guarded_process
            classic._benchmark_offset_guard=True
        opt=ConfigLoader().load({'model':MODEL,'index_model':MODEL,'summary_model':MODEL,'if_add_node_summary':'yes','if_add_node_id':'yes'})
        result=classic.page_index_main(str(pdf),opt);mode='standard'
    else:mode='flash'
    result['metadata']={'pdf_sha256':digest,'pageindex_revision':'6d23caf416858f2ca136840305d1f479a86f6ef7','index_model':MODEL,'mode':mode,'sec':time.perf_counter()-start,'summary_words':60 if mode=='flash' else None,'question_independent':True}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2));tmp.replace(path)
    return doc,{'sec':result['metadata']['sec'],'roots':len(result['structure']),'mode':mode}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--docs',type=int);ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--mode',choices=['flash','classic'],default='flash')
    ap.add_argument('--documents',nargs='+',help='Explicit demo document names')
    args=ap.parse_args()
    qs=[json.loads(l) for l in (ROOT/'data/fb_bucket_current.jsonl').read_text().splitlines()];docs=sorted({q['doc_name'] for q in qs})[:args.docs]
    if args.documents:
        if not set(args.documents)<=set(docs):raise ValueError('Unknown document name')
        docs=list(dict.fromkeys(args.documents))
    with cf.ProcessPoolExecutor(args.workers) as ex:
        futures={ex.submit(build,d,args.mode):d for d in docs}
        for i,f in enumerate(cf.as_completed(futures),1):
            try:print(i,len(docs),f.result(),flush=True)
            except Exception as exc:print('FAILED',futures[f],repr(exc),flush=True);raise
# Flash's PDF parser also spawns workers. Initialize the safe namespace when
# multiprocessing re-imports this entrypoint before unpickling their targets.
runtime()
if __name__=='__main__':main()
