# Retrieval experiments and GLiNER demo

This folder contains the FinanceBench retrieval experiments and a small
GLiNER2.5-Decide GPU demo. Qwen builds PageIndex trees and summaries at ingestion;
GLiNER consumes cached indexes at query time and selects pages for Qwen to answer.
The full hierarchy benchmark remains deferred. See `README_GLINER_DEMO.md` for
the current demo, its exploratory results, and remaining retrieval limitations.

## Setup from a fresh checkout

```bash
uv venv bench/.venv-gpu --python 3.13
uv pip install --python bench/.venv-gpu/bin/python -r bench/requirements-gpu-lock.txt --extra-index-url https://download.pytorch.org/whl/cu130
uv pip install --python bench/.venv-gpu/bin/python -r bench/requirements-jev.txt PyPDF2 pypdfium2 sortedcontainers
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/setup_references.py
```

The setup script fetches public PageIndex and traversal source at pinned commits.
These external checkouts are local dependencies, not embedded Git repositories
in this project. Installed runtimes, model weights, document data, generated
results, and API caches are excluded from Git. No credentials are committed.

Use the existing Hugging Face CLI login for Qwen API authentication and follow
`README_GPU_BENCH.md` to acquire the bucket snapshot and its PDFs. The GPU demo
and new indexing runners do not read `.env`. Jev is an optional reference backend;
the default GLiNER route does not call its service.

```bash
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python -m unittest discover -s bench -p 'test_*.py' -v
```

`README_GPU_BENCH.md` describes the completed earlier flat-retrieval experiment.
`README_JEV_BENCH.md` documents the optional Jev reference runner. Generated
reports referenced by these guides are local artifacts and are not part of the
source-only push.
