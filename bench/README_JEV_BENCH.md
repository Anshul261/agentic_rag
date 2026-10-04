# Jev and PageIndex reference benchmark

The VectifyAI reference uses `jev-1.13.0` with `typesafe-sdk==0.7.2`.
Source revision: `7b1008c437c8c9a88da8a427a76052fb0454977a`.
The runner executes the upstream search function bodies unchanged, checks their
source checksum, and supplies real SDK `Choice` and `Noul` objects. It skips the
upstream import-time `.env` read. There is no K2 or GLiNER substitution.

## Scope and parity

`--scope known_document` measures the upstream algorithm on each question's
specified PDF. Document identity is supplied by the evaluation setup. This must
not be compared directly to the previous whole-bucket results.

`--scope bucket` adds an explicit document-selection stage. Jev chooses three
documents from their names and query-independent PageIndex root summaries,
then the unchanged reference searches each selected document. Pages are merged
by their Noul verification scores. This is an extension, not an upstream claim.
The gold document, gold pages, and gold answers never enter this route.

Local mode uses genuine open-source PageIndex trees, built with Qwen summaries,
and extracted PDF text. Managed PageIndex can produce different trees and
markdown. For the exact managed inputs, pass `--cloud-doc-map path.json`, where
the JSON maps bucket document names to already indexed PageIndex document IDs.
This mode uses the original managed tree and markdown for retrieval and reading.
Document IDs must correspond to these same PDFs and page numbering.

The upstream `pages` field is numerically sorted. Raw results preserve that
field. For the shared top-three-page answer protocol, the runner uses the
verifier's relevance order, explicitly stored as `ranked_pages`.

## Run

### Prepared three-question demo

The demo uses three cached 3M reports: the 2018 and 2022 10-Ks, and the
2023 Q2 10-Q. Both backends now share the same checksum-pinned reference
functions and SDK question types. The manifest contains no gold answers or
evidence pages. Preparing the demo makes no model calls and starts no indexing.
Full-bucket work remains deferred until the GLiNER setup is finished.

```bash
# Prepare only. Safe default; no inference.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/pageindex_demo.py

# Later: run either backend on exactly the same demo inputs.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/pageindex_demo.py --backend gliner --run
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/pageindex_demo.py --backend jev --run
# Add --answer to run the shared Qwen answerer and GLM evaluation too.
```

The GLiNER adapter is experimental. Its chunked binary scoring and normalized
odds differ from Jev's native Choice probabilities. Shared traversal alone
does not establish matching accuracy or calibrated confidence.

Credentials must be available in the runtime environment. `TYPESAFE_API_KEY`
is a TypeSafe credential, not an HF token. Managed mode additionally requires
`PAGEINDEX_API_KEY`. The runner never reads `.env`.

```bash
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --preflight

# Build any missing local trees, resuming previously completed documents.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/pageindex_build.py --workers 2

# Explicit partial pilot; its results are labelled as a subset.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --pilot

# Full cohort, each scope reported independently.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --scope known_document
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --scope bucket

# Original managed PageIndex inputs.
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --cloud-doc-map path.json --scope known_document
```

## Metrics and limits

Outputs live in `bench/results/jev_pageindex`. Metrics include answer correctness
against the FinanceBench gold answer, contextual groundedness, page hit@3,
verified-set hit, section recall, selected-section size, retrieval wall time,
document selection, per-request timings, and Jev token usage. Qwen answers from
three pages using the existing protocol; GLM grades correctness without seeing
retrieved context. Groundedness is graded separately.

Cached SDK responses retain their original request latency and are labelled.
Wall time from a cached run is not fresh-serving latency. The SDK reports tokens,
not billed dollars; cost remains unknown until a verified tariff or billing
export is supplied. Indexing is a separate one-time workload.

Preflight has no model calls. A missing credential or incomplete tree set refuses
a full run instead of silently shrinking the cohort. Unit tests use fixtures
and do not constitute an accuracy benchmark.

```bash
uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python -m unittest discover -s bench -p test_jev_reference.py -v
```
