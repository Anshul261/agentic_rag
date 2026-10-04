"""Pinned Jev benchmark. Preflight is offline; run requires TYPESAFE_API_KEY.

uv run --no-project --no-env-file --python bench/.venv-gpu/bin/python bench/jev_pageindex_bench.py --preflight
"""
import argparse
import hashlib
import json
import os
import statistics
import time
from pathlib import Path

from jev_reference import (MODEL, REVISION, SOURCE_SHA256, ROOT, LocalPages, CloudPages,
                           RecordedClient, bucket_documents, reference, validate_tree)

OUT = ROOT / "results/jev_pageindex"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2)); tmp.replace(path)


def dataset(tree_dir=None):
    qs = [json.loads(l) for l in (ROOT / "data/fb_bucket_current.jsonl").read_text().splitlines()]
    pages = json.loads((ROOT / "cache/bucket_pages.json").read_text())
    by_doc = {}
    for p in pages:
        by_doc.setdefault(p["doc"], {})[p["page"] + 1] = p["text"]
    trees, missing, invalid = {}, [], {}
    for doc in sorted({q["doc_name"] for q in qs}):
        path = (Path(tree_dir) if tree_dir else ROOT / "data/pageindex") / f"{doc}.json"
        if not path.exists():
            missing.append(doc); continue
        try:
            raw = json.loads(path.read_text())
            digest = hashlib.sha256((ROOT / f"pdfs/{doc}.pdf").read_bytes()).hexdigest()
            if raw["metadata"]["pdf_sha256"] != digest:
                raise ValueError("PDF checksum changed")
            validate_tree(raw["structure"], len(by_doc[doc]))
            trees[doc] = raw["structure"]
        except (ValueError, KeyError) as exc:
            invalid[doc] = str(exc)
    return qs, pages, by_doc, trees, missing, invalid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--pilot", action="store_true", help="Explicit subset using available valid trees")
    parser.add_argument("--scope", choices=["known_document", "bucket"], default="known_document")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--cloud-doc-map", type=Path, help="JSON {bucket_doc_name: managed_PageIndex_doc_id}; use original managed tree and markdown")
    args = parser.parse_args()
    qs, pages, by_doc, trees, missing, invalid = dataset()
    doc_ids = json.loads(args.cloud_doc_map.read_text()) if args.cloud_doc_map else None
    if doc_ids is not None:
        if not isinstance(doc_ids, dict) or any(not isinstance(v, str) or not v for v in doc_ids.values()):
            raise SystemExit("Cloud document map must contain nonempty string IDs")
        missing = sorted(set(by_doc) - set(doc_ids))
        invalid = {}
        cohort = [q for q in qs if q["doc_name"] in doc_ids] if args.pilot else qs
    else:
        cohort = [q for q in qs if q["doc_name"] in trees] if args.pilot else qs
    metadata = {"model": MODEL, "sdk": "0.7.2", "reference_revision": REVISION,
                "reference_source_sha256": SOURCE_SHA256, "scope": args.scope,
                "total_questions": len(qs), "cohort_questions": len(cohort),
                "documents": len(by_doc), "valid_trees": len(trees), "missing_trees": missing,
                "invalid_trees": invalid, "typesafe_key_available": bool(os.environ.get("TYPESAFE_API_KEY")),
                "pilot": args.pilot, "pages": "one-based PDF indices; local extracted PDF text, not cloud markdown",
                "cost_usd": None, "cost_note": "SDK reports tokens, not billed USD. No fabricated zero cost.",
                "status": "preflight_only"}
    metadata["pageindex_mode"] = "cloud" if doc_ids is not None else "local"
    metadata["pageindex_key_available"] = bool(os.environ.get("PAGEINDEX_API_KEY"))
    if doc_ids is not None:
        metadata["pages"] = "original managed PageIndex tree and markdown; one-based PDF indices"
        metadata["cloud_doc_map_sha256"] = hashlib.sha256(args.cloud_doc_map.read_bytes()).hexdigest()
    save(OUT / "preflight.json", metadata)
    print(json.dumps({k: v for k, v in metadata.items() if k not in ["missing_trees", "invalid_trees"]}, indent=2))
    if args.preflight:
        return
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("Live Jev evaluation needs TYPESAFE_API_KEY in the runtime environment. No .env is read.")
    if not cohort or ((missing or invalid) and (not args.pilot or args.scope == "bucket")):
        raise SystemExit("Full coverage requires all valid trees. Use --pilot only for a labelled known-document subset.")
    from typesafe_sdk import RetryPolicy, TypeSafeClient
    client = TypeSafeClient(model=MODEL, retry=RetryPolicy(max_retries=5, backoff_initial=1., backoff_max=20.))
    recorded = RecordedClient(client)
    ref = reference(recorded)
    if doc_ids is not None:
        if not os.environ.get("PAGEINDEX_API_KEY"):
            raise SystemExit("Managed PageIndex mode requires PAGEINDEX_API_KEY in the runtime environment")
        from pageindex import PageIndexClient
        local = CloudPages(PageIndexClient(api_key=os.environ["PAGEINDEX_API_KEY"]), doc_ids)
        wanted_docs = set(doc_ids) & set(by_doc)
        trees = {d: local.get_document_structure(d) for d in sorted(wanted_docs)}
        for d, tree in trees.items():
            validate_tree(tree, len(by_doc[d]))
    else:
        local = LocalPages(trees, by_doc)
    # Descriptions are query-independent; gold metadata never enters bucket selection.
    descriptions = {doc: (doc.replace("_", " ") + "\n" + "\n".join(
        f"{n['title']}. {n['summary']}" for n in tree))[:ref.MAX_PAGE_CHARS] for doc, tree in trees.items()}
    metadata["experiment_sha256"] = hashlib.sha256(json.dumps(
        {"trees": trees, "questions": cohort, "source": SOURCE_SHA256,
         "scope": args.scope, "mode": metadata["pageindex_mode"]}, sort_keys=True).encode()).hexdigest()
    path = OUT / f"{metadata['pageindex_mode']}_{args.scope}{'_pilot' if args.pilot else ''}{'_retrieval' if args.retrieval_only else ''}.json"
    result = json.loads(path.read_text()) if path.exists() else {"metadata": metadata, "rows": {}, "errors": {}}
    if result["metadata"].get("experiment_sha256") != metadata["experiment_sha256"]:
        raise SystemExit("Existing results belong to different trees, questions, or reference source")
    evaluator = None
    if not args.retrieval_only:
        import bucket_gpu_bench as evaluator
        evaluator.PAGES = pages
        answer_api = evaluator.Api()
        lookup = {(p["doc"], p["page"] + 1): i for i, p in enumerate(pages)}
    for q in cohort:
        qid = q["financebench_id"]
        if qid in result["rows"]:
            continue
        event_start, started = len(recorded.events), time.perf_counter()
        try:
            docs, document_tokens = ([q["doc_name"]], 0) if args.scope == "known_document" else bucket_documents(ref, q["question"], descriptions)
            searches = {d: ref.locate(local, d, q["question"]) for d in docs}
            # Upstream returns kept pages in numerical order. Preserve those;
            # the shared top-three reader uses the verifier's relevance order.
            ranked = sorted(((d, p, r["page_scores"][p]) for d, r in searches.items()
                             for p in r["pages"]), key=lambda v: -v[2])
            top = [(d, p) for d, p, _ in ranked[:3]]
            gold = {(e["doc_name"], e["evidence_page_num"] + 1) for e in q["evidence"]}
            covered = {(d, p) for d, r in searches.items() for s in r["sections"]
                       for p in range(s["start"], s["end"] + 1)}
            selected = {(d, p) for d, r in searches.items() for p in r["pages"]}
            row = {"selected_documents": docs, "ranked_pages": ranked,
                   "section_recall": bool(gold & covered), "section_pages": len(covered),
                   "hit_at_3": bool(gold & set(top)), "verified_set_hit": bool(gold & selected),
                   "document_hit": any(d == q["doc_name"] for d in docs),
                   "retrieval_wall_s": time.perf_counter() - started,
                   "input_tokens": document_tokens + sum(r["jev_tokens"] for r in searches.values()),
                   "requests": recorded.events[event_start:],
                   "searches": {d: {k: v for k, v in r.items() if k != "text"} for d, r in searches.items()}}
            if evaluator:
                # Feed managed markdown to the reader in cloud mode as well.
                if doc_ids is not None:
                    for d, p in top:
                        evaluator.PAGES[lookup[(d, p)]]["text"] = searches[d]["text"][p]
                row["evaluation"] = evaluator.read_and_judge(answer_api, q, [lookup[(d, p)] for d, p in top])
            result["rows"][qid] = row
            result["errors"].pop(qid, None)
            print(f"Completed {len(result['rows'])}/{len(cohort)}", flush=True)
        except Exception as exc:
            # Do not persist exception bodies that could contain auth headers.
            result["errors"][qid] = type(exc).__name__
            save(path, result)
            raise RuntimeError(f"Jev question failed: {qid}; {type(exc).__name__}") from None
        save(path, result)
    rows = list(result["rows"].values())
    summary = {"n": len(rows), "scope": args.scope, "pilot": args.pilot,
               "hit_at_3_pct": 100 * statistics.mean(r["hit_at_3"] for r in rows),
               "section_recall_pct": 100 * statistics.mean(r["section_recall"] for r in rows),
               "verified_set_hit_pct": 100 * statistics.mean(r["verified_set_hit"] for r in rows),
               "section_pages_mean": statistics.mean(r["section_pages"] for r in rows),
               "retrieval_wall_median_s": statistics.median(r["retrieval_wall_s"] for r in rows),
               "cached_requests": sum(e["cached"] for r in rows for e in r["requests"]),
               "input_tokens": sum(r["input_tokens"] for r in rows), "cost_usd": None,
               "document_hit_pct": 100 * statistics.mean(r["document_hit"] for r in rows),
               "retrieval_wall_p95_s": sorted(r["retrieval_wall_s"] for r in rows)[max(0, int(.95 * len(rows)) - 1)],
               "requests": sum(len(r["requests"]) for r in rows)}
    if evaluator:
        summary["answer_correct_pct"] = 100 * statistics.mean(r["evaluation"]["correctness_judge"]["value"]["correct"] for r in rows)
        summary["grounded_pct"] = 100 * statistics.mean(r["evaluation"]["context_judge"]["value"]["grounded"] for r in rows)
        summary["answer_correct_wilson_95_pct"] = evaluator.wilson([r["evaluation"]["correctness_judge"]["value"]["correct"] for r in rows])
        summary["context_words_mean"] = statistics.mean(r["evaluation"]["context_words"] for r in rows)
    result["summary"] = summary
    result["metadata"]["status"] = "complete_pilot" if args.pilot else "complete"
    save(path, result)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
