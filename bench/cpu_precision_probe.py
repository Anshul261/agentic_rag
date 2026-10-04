"""Small CPU speed/precision probe. Does not score gold answers or tune retrieval."""
import os,time,json
os.environ['CUDA_VISIBLE_DEVICES']=''
import torch
from gliner_cpu import CpuReranker,positive_score
from common import load_subset,load_doc
r=CpuReranker(4,4)
q=load_subset(10,1)[0]; texts,_=load_doc(q['doc'])
passages=[r.passages(t,q['question'],'snippet')[0] for t in texts[30:34]]
tasks=r.tasks(q['question'])
out=[]
for precision in ['fp32','bf16','int8']:
 r.precision=precision
 if precision=='int8':
  r.model=torch.ao.quantization.quantize_dynamic(r.model,{torch.nn.Linear},dtype=torch.qint8)
 t=time.perf_counter()
 with torch.inference_mode(),torch.autocast('cpu',dtype=torch.bfloat16,enabled=precision=='bf16'):
  scores=r.score(passages,tasks)
 out.append({'precision':precision,'seconds':time.perf_counter()-t,'scores':scores})
 print(out[-1],flush=True)
from pathlib import Path
Path('bench/results/gliner_precision_probe.json').write_text(json.dumps(out,indent=2))
