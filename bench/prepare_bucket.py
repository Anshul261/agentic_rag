"""Download the entire bucket-linked PDF corpus; preserve the bucket snapshot and checksums."""
import concurrent.futures as cf
import hashlib,json,time,urllib.request
from pathlib import Path
HERE=Path(__file__).parent
source=HERE/'data/fb_bucket_current.jsonl'
rows=[json.loads(line) for line in source.read_text().splitlines()]
docs=sorted({r['doc_name'] for r in rows})

def get(doc):
 path=HERE/f'pdfs/{doc}.pdf'
 if not path.exists():
  for attempt in range(3):
   try:
    urllib.request.urlretrieve(f'https://raw.githubusercontent.com/patronus-ai/financebench/main/pdfs/{doc}.pdf',path)
    break
   except Exception:
    path.unlink(missing_ok=True)
    if attempt==2: raise
    time.sleep(1+attempt)
 import pymupdf
 with pymupdf.open(path) as pdf:
  pages=len(pdf)
 return doc,{'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':pages,'bytes':path.stat().st_size}

if __name__=='__main__':
 out={'bucket':'AnshulRaj/financebench-bucket','snapshot_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'questions':len(rows),'documents':{}}
 with cf.ThreadPoolExecutor(6) as pool:
  for doc,info in pool.map(get,docs):
   out['documents'][doc]=info
   print(f'{len(out["documents"])}/{len(docs)} {doc}: {info["pages"]} pages',flush=True)
 (HERE/'data/bucket_manifest.json').write_text(json.dumps(out,indent=2))
 print('Total pages:',sum(d['pages'] for d in out['documents'].values()),flush=True)
