"""Postgres storage for trees.

`documents` keeps the whole tree as JSONB (what get_tree returns); `nodes` is a
flat copy for reading node text and for keyword search across a collection
(full-text index now, embedding column added in the embeddings step).
A collection maps to a project in the app.
"""

from __future__ import annotations

import re

import psycopg
from psycopg.types.json import Jsonb

from .config import settings
from .models import DocTree

SCHEMA = """
create table if not exists documents (
    collection   text not null,
    doc_id       text not null,
    filename     text not null,
    title        text not null,
    title_key    text not null,
    n_pages      int  not null,
    summary      text,
    parser_version text not null,
    tree         jsonb not null,
    indexed_at   timestamptz not null default now(),
    primary key (collection, doc_id)
);
create unique index if not exists documents_title_key on documents (collection, title_key);

create table if not exists nodes (
    collection  text not null,
    doc_id      text not null,
    node_id     text not null,
    kind        text not null,
    title       text not null,
    summary     text,
    text        text not null,
    page_start  int  not null,
    page_end    int  not null,
    image_path  text,
    tsv tsvector generated always as (
        setweight(to_tsvector('english', title), 'A') ||
        setweight(to_tsvector('english', coalesce(summary, '')), 'B') ||
        setweight(to_tsvector('english', left(text, 100000)), 'C')) stored,
    primary key (collection, doc_id, node_id),
    foreign key (collection, doc_id) references documents on delete cascade
);
create index if not exists nodes_tsv on nodes using gin (tsv);
"""


def title_key(title: str) -> str:
    """Normalized title used to catch the same paper saved as different files."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:200]


class Store:
    def __init__(self, url: str = settings.db_url):
        self.conn = psycopg.connect(url, autocommit=True)
        self.conn.execute(SCHEMA)

    def delete(self, collection: str, doc_id: str) -> None:
        self.conn.execute("delete from documents where collection=%s and doc_id=%s", (collection, doc_id))

    def find_duplicate(self, collection: str, tree: DocTree) -> str | None:
        row = self.conn.execute(
            "select doc_id from documents where collection=%s and title_key=%s and doc_id<>%s",
            (collection, title_key(tree.title), tree.doc_id)).fetchone()
        return row[0] if row else None

    def has(self, collection: str, doc_id: str) -> bool:
        return self.conn.execute("select 1 from documents where collection=%s and doc_id=%s",
                                 (collection, doc_id)).fetchone() is not None

    def upsert(self, collection: str, tree: DocTree) -> None:
        with self.conn.transaction():
            self.conn.execute("delete from documents where collection=%s and doc_id=%s",
                              (collection, tree.doc_id))
            self.conn.execute(
                "insert into documents (collection, doc_id, filename, title, title_key, n_pages, summary,"
                " parser_version, tree) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (collection, tree.doc_id, tree.filename, tree.title, title_key(tree.title), tree.n_pages,
                 tree.summary, tree.parser_version, Jsonb(tree.model_dump(mode="json"))))
            with self.conn.cursor() as cur:
                cur.executemany(
                    "insert into nodes (collection, doc_id, node_id, kind, title, summary, text,"
                    " page_start, page_end, image_path) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(collection, tree.doc_id, n.node_id, n.kind, n.title, n.summary, n.text,
                      n.page_start, n.page_end, n.image_path) for n in tree.walk()])

    def load(self, collection: str, doc_id: str) -> DocTree | None:
        row = self.conn.execute("select tree from documents where collection=%s and doc_id=%s",
                                (collection, doc_id)).fetchone()
        return DocTree.model_validate(row[0]) if row else None

    def list_documents(self, collection: str) -> list[tuple[str, str, int, str | None]]:
        return self.conn.execute(
            "select doc_id, title, n_pages, summary from documents where collection=%s order by title",
            (collection,)).fetchall()
