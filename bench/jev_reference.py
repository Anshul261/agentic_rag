"""Run the pinned Jev reference functions without its automatic .env loading."""
import ast
import hashlib
import json
import threading
import time
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tiktoken
from typesafe_sdk import Choice, Noul

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "reference/jev-doc-search/tree_search.py"
REVISION = "7b1008c437c8c9a88da8a427a76052fb0454977a"
MODEL = "jev-1.13.0"
SOURCE_SHA256 = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
PINNED_SHA256 = "31c1d188459e6c04bd75b49c394e591f1140b51f0c5dfce6da2c622205e69a1c"


def reference(client):
    """Compile the original function ASTs unchanged, injecting only dependencies."""
    if SOURCE_SHA256 != PINNED_SHA256:
        raise ValueError("Pinned reference source checksum changed")
    parsed = ast.parse(SOURCE.read_text())
    body = [n for n in parsed.body if isinstance(n, ast.FunctionDef)]
    constants = {}
    for n in parsed.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            target = n.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                constants[target.id] = ast.literal_eval(n.value)
    if constants["MODEL"] != MODEL:
        raise ValueError("Reference model changed; review the pinned benchmark")
    module = types.ModuleType("pinned_jev_reference")
    module.__dict__.update(constants, time=time, ThreadPoolExecutor=ThreadPoolExecutor,
                           Choice=Choice, Noul=Noul, typesafe=client,
                           enc=tiktoken.get_encoding("o200k_base"))
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), module.__dict__)
    return module


class RecordedClient:
    """Cache SDK responses, recording original network latency and token usage.

    Cached requests are marked explicitly. They cannot measure fresh latency.
    Keys exclude credentials. Atomic unique temporary files support concurrency.
    """
    def __init__(self, client, cache=None):
        self.client = client
        self.cache = Path(cache or ROOT / "cache/jev_reference")
        self.cache.mkdir(parents=True, exist_ok=True)
        self.events = []
        self.lock = threading.Lock()

    def system_one(self, *, state, questions):
        payload = {"model": MODEL, "state": state,
                   "questions": {k: v.model_dump(mode="json") for k, v in questions.items()}}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        path = self.cache / f"{digest}.json"
        cached = path.exists()
        if cached:
            item = json.loads(path.read_text())
        else:
            started = time.perf_counter()
            response = self.client.system_one(state=state, questions=questions)
            raw = response.model_dump(mode="json", include={"model", "usage", "answers"})
            if raw["model"] != MODEL:
                raise ValueError(f"Requested {MODEL}, server returned {raw['model']}")
            item = {"response": raw, "network_s": time.perf_counter() - started}
            tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(item)); tmp.replace(path)
        raw = item["response"]
        with self.lock:
            self.events.append({"request_sha256": digest, "cached": cached,
                                "network_s": item["network_s"], "usage": raw["usage"],
                                "kinds": [q.type for q in questions.values()]})
        return types.SimpleNamespace(
            answers={k: types.SimpleNamespace(**v) for k, v in raw["answers"].items()},
            usage=types.SimpleNamespace(**raw["usage"]))


class LocalPages:
    """Official local PageIndex trees plus PDF text; not cloud markdown parity."""
    def __init__(self, trees, pages):
        self.trees = trees
        self.pages = pages

    def get_document_structure(self, doc_id):
        return self.trees[doc_id]

    def get_page_content(self, doc_id, indices):
        return [{"page_index": int(p), "markdown": self.pages[doc_id][int(p)]}
                for p in indices.split(",") if p]


class CloudPages:
    """Map benchmark document names to managed PageIndex IDs."""
    def __init__(self, client, doc_ids):
        self.client, self.doc_ids = client, doc_ids

    def get_document_structure(self, doc_id):
        return self.client.get_document_structure(self.doc_ids[doc_id])

    def get_page_content(self, doc_id, indices):
        return self.client.get_page_content(self.doc_ids[doc_id], indices)


def validate_tree(tree, page_count):
    seen = set()
    def visit(nodes, bounds=None):
        previous = 0
        for n in nodes:
            start, end = n["start_index"], n["end_index"]
            if not 1 <= start <= end <= page_count:
                raise ValueError("Tree page range is outside the PDF")
            if bounds and not bounds[0] <= start <= end <= bounds[1]:
                raise ValueError("Child page range is outside its parent")
            if start < previous:
                raise ValueError("Reference opening-page logic requires ordered children")
            previous = start
            if n["node_id"] in seen:
                raise ValueError("Duplicate node ID")
            seen.add(n["node_id"])
            if not n.get("title") or not n.get("summary"):
                raise ValueError("Missing PageIndex title/summary")
            visit(n.get("nodes") or [], (start, end))
    if not tree:
        raise ValueError("Empty PageIndex tree")
    visit(tree)


def bucket_documents(ref, question, descriptions, count=3):
    """Explicit extension: Jev chooses documents before the unchanged search.

    Window large document menus using the reference token/option limits, then
    compare window winners together. This is separate from the upstream flow.
    """
    labels = list(descriptions)
    windows = ref.windows(labels, descriptions)
    winners, used = [], 0
    for window in windows:
        probs, tokens = ref.ask_choice(question, "Which document most likely contains the answer to the question?",
                                       {k: descriptions[k] for k in window})
        winners.extend(sorted(probs, key=probs.get, reverse=True)[:count])
        used += tokens
    if len(windows) > 1:
        costs = sum(len(ref.enc.encode(descriptions[k])) for k in winners)
        if len(winners) > ref.MAX_OPTIONS or costs > ref.MAX_TOKENS:
            raise ValueError("Document finalist menu exceeds reference limits")
        probs, tokens = ref.ask_choice(question, "Which document most likely contains the answer to the question?",
                                       {k: descriptions[k] for k in winners})
        winners = sorted(probs, key=probs.get, reverse=True)
        used += tokens
    return winners[:count], used
