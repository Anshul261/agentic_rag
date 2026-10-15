"use client"

import { useMemo, useState } from "react"
import { FileText, Image as ImageIcon, Network, Play, Plus, Search, Trash2, Upload } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Collection, DocumentInfo, RecordedRun } from "@/lib/api"

export function Sidebar({ collections, collection, onCollection, docs, runs, busy, activeDoc,
    onNewChat, onOpenDoc, onDeleteDoc, onReplay, onUpload }: {
    collections: Collection[]
    collection: string
    onCollection: (c: string) => void
    docs: DocumentInfo[]
    runs: RecordedRun[]
    busy: boolean
    activeDoc?: string
    onNewChat: () => void
    onOpenDoc: (docId: string) => void
    onDeleteDoc: (doc: DocumentInfo) => void
    onReplay: (run: RecordedRun) => void
    onUpload: () => void
}) {
    const [filter, setFilter] = useState("")
    const [tab, setTab] = useState<"docs" | "runs">("docs")
    const shown = useMemo(() => {
        const q = filter.trim().toLowerCase()
        return q ? docs.filter((d) => `${d.title} ${d.filename}`.toLowerCase().includes(q)) : docs
    }, [docs, filter])
    const collectionRuns = runs.filter((r) => r.collection === collection)

    return (
        <nav className="flex h-full flex-col border-r border-sidebar-border bg-sidebar font-mono">
            <div className="flex items-center gap-2 px-4 pt-4 pb-3">
                <Network className="w-4 h-4 text-primary" />
                <span className="text-xs uppercase tracking-[0.2em]">PageIndex</span>
            </div>

            <div className="space-y-2 px-3 pb-3 border-b border-sidebar-border">
                <button onClick={onNewChat} disabled={busy}
                    className="flex w-full items-center gap-2 rounded-sm border border-border bg-card px-3 py-2 text-[11px] uppercase tracking-widest hover:border-primary/60 disabled:opacity-40">
                    <Plus className="w-3.5 h-3.5 text-primary" /> New chat
                </button>
                <div className="flex gap-1.5">
                    <select value={collection} onChange={(e) => onCollection(e.target.value)} disabled={busy}
                        aria-label="Collection"
                        className="min-w-0 flex-1 rounded-sm border border-border bg-card px-2 py-1.5 text-[11px]">
                        {collections.length === 0 && <option value="">no collections</option>}
                        {collections.map((c) => <option key={c.name} value={c.name}>{c.name} · {c.n_docs}</option>)}
                    </select>
                    <button onClick={onUpload} title="Add documents" aria-label="Add documents"
                        className="rounded-sm border border-border bg-card px-2 hover:border-primary/60">
                        <Upload className="w-3.5 h-3.5 text-primary" />
                    </button>
                </div>
            </div>

            <div className="flex border-b border-sidebar-border text-[10px] uppercase tracking-widest">
                {(["docs", "runs"] as const).map((t) => (
                    <button key={t} onClick={() => setTab(t)}
                        className={cn("flex-1 py-2", tab === t ? "text-foreground border-b border-primary" : "text-muted-foreground hover:text-foreground/70")}>
                        {t === "docs" ? `Documents · ${docs.length}` : `Recorded · ${collectionRuns.length}`}
                    </button>
                ))}
            </div>

            {tab === "docs" && (
                <>
                    <div className="relative px-3 pt-2.5 pb-1.5">
                        <Search className="absolute left-5 top-[18px] w-3 h-3 text-muted-foreground" />
                        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter documents"
                            className="w-full rounded-sm border border-border bg-card py-1.5 pl-7 pr-2 text-[11px] focus:outline-none focus:border-primary/60" />
                    </div>
                    <ul className="flex-1 overflow-y-auto px-1.5 pb-3">
                        {shown.map((d) => (
                            <li key={d.doc_id}>
                                <div onClick={() => onOpenDoc(d.doc_id)} title={d.summary ?? d.title}
                                    className={cn("group flex cursor-pointer items-start gap-2 rounded-sm px-2 py-1.5",
                                        activeDoc === d.doc_id ? "bg-muted" : "hover:bg-muted/60")}>
                                    <FileText className="mt-0.5 w-3 h-3 shrink-0 text-muted-foreground" />
                                    <div className="min-w-0 flex-1">
                                        <div className="text-[11px] leading-snug line-clamp-2">{d.title}</div>
                                        <div className="mt-0.5 flex items-center gap-2 text-[9.5px] text-muted-foreground">
                                            {d.n_pages > 0 && <span>{d.n_pages}p</span>}
                                            {d.n_figures > 0 && <span className="flex items-center gap-0.5"><ImageIcon className="w-2.5 h-2.5" />{d.n_figures}</span>}
                                            {d.n_tables > 0 && <span>{d.n_tables} tables</span>}
                                        </div>
                                    </div>
                                    <button onClick={(e) => { e.stopPropagation(); onDeleteDoc(d) }} title="Remove from collection"
                                        aria-label={`Remove ${d.title}`}
                                        className="invisible mt-0.5 text-muted-foreground hover:text-destructive group-hover:visible">
                                        <Trash2 className="w-3 h-3" />
                                    </button>
                                </div>
                            </li>
                        ))}
                        {shown.length === 0 && (
                            <li className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                                {docs.length ? "No matches" : "No documents yet. Use the upload button above."}
                            </li>
                        )}
                    </ul>
                </>
            )}

            {tab === "runs" && (
                <ul className="flex-1 overflow-y-auto px-1.5 py-2">
                    {collectionRuns.map((r) => (
                        <li key={r.run_id}>
                            <button onClick={() => onReplay(r)} disabled={busy} title="Replay without LLM calls"
                                className="flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left hover:bg-muted/60 disabled:opacity-40">
                                <Play className="mt-0.5 w-3 h-3 shrink-0 text-primary" />
                                <span className="text-[11px] leading-snug line-clamp-2">{r.question}</span>
                            </button>
                        </li>
                    ))}
                    {collectionRuns.length === 0 && (
                        <li className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                            Answers you get are recorded here and can be replayed for free.
                        </li>
                    )}
                </ul>
            )}
        </nav>
    )
}
