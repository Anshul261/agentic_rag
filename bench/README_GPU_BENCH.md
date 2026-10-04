# GPU bucket benchmark

The completed results are in `results/bucket_gpu/report.md`. `evaluation.json` contains all 150 questions and five controlled retrieval routes, including the hybrid and gold-page controls. `gliner.json` records local GPU evidence scoring independently of LLM generation. `validation.md` documents the corrected grading protocol and experiment limits. `comparison.png` and `comparison.svg` are shareable figures.

The original question is the only query input; retrieval is global across 84 reports. No gold document filtering is applied. BM25 and BGE-small provide a common 30-page pool. GLiNER2.5-Decide scores yes/no relevance on bounded passages. Qwen3.8-27B either ranks all 30 pages or ranks GLiNER's top ten. A common Qwen reader answers from the selected top three pages. GLiNER itself does not generate answers.

GLiNER runs on the local RTX 5070 Ti, with BF16 and batch size 16. Qwen runs through HF/DeepInfra with thinking disabled. Credentials come from the existing HF CLI login; this runner does not open an environment file. Existing application files are not required for this standalone benchmark.

To recreate the environment:

```bash
uv venv bench/.venv-gpu --python 3.13
uv pip install --python bench/.venv-gpu/bin/python -r bench/requirements-gpu-lock.txt --extra-index-url https://download.pytorch.org/whl/cu130
```

To acquire the current dataset snapshot and its linked reports:

```bash
hf buckets cp hf://buckets/AnshulRaj/financebench-bucket/financebench_merged.jsonl bench/data/fb_bucket_current.jsonl
uv run --project bench --no-env-file --no-sync bench/prepare_bucket.py
```

For an exact repeat, retain the recorded snapshot and PDFs. Their hashes are in `data/bucket_manifest.json` and `results/bucket_gpu/summary.json`. If replacing the dataset, archive the existing results and remove the bucket-specific page/vector/API caches before rerunning; caches are intended to resume the recorded experiment.

Run or resume:

```bash
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/bucket_gpu_bench.py
uv run --project bench --no-env-file --no-sync bench/plot_bucket_bench.py
```

API responses are cached by exact payload. A cached latency is the original measured response time, not a fresh network measurement. Per-route estimates count the requests that would be needed by that route, even if identical requests were reused during this experiment. Offline indexing and judge calls are outside production costs. Ranking format repair requests are counted. Failed questions block final reporting.

Accuracy uses a reference-only GLM-5.3-Flash judgment. Retrieved context is used only in a separate groundedness judgment. Initial context-aware correctness aggregates are explicitly marked invalid and are not used. The strict gold-page labels can miss equivalent evidence elsewhere. No human answer review was performed.

Run the regression checks:

```bash
uv run --project bench --no-env-file --no-sync -m unittest discover -s bench -p 'test_*.py'
```
