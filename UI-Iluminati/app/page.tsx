"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Menu, Network, Play, Send } from "lucide-react"
import { cn } from "@/lib/utils"
import {
    ask, deleteDocument, listCollections, listDocuments, listRuns, replay,
    type Citation, type Collection, type DocumentInfo, type RecordedRun, type RunStats,
    type StreamHandlers, type TraceEvent,
} from "@/lib/api"
import { AnswerCard } from "@/components/pageindex/answer"
import { SearchTrace } from "@/components/pageindex/search-trace"
import { Sidebar } from "@/components/pageindex/sidebar"
import { SourceViewer, type SourceTarget } from "@/components/pageindex/source-viewer"
import { UploadDialog } from "@/components/pageindex/upload-dialog"

interface Turn {
    id: string
    question: string
    events: TraceEvent[]
    answer?: string
    citations: Citation[]
    blocked?: boolean
    stats?: RunStats
    error?: string
    done: boolean
    replay?: boolean
}

const SUGGESTIONS: Record<string, string[]> = {
    litreview: [
        "Which GNN architectures are used for financial fraud detection, and which financial area is most studied?",
        "Which papers use SMOTE or SMOTE-based resampling, and what does each report about its effect?",
        "List all the documents related to adversarial machine learning research.",
        "In the GNN systematic review, how many conference and journal papers were published in 2022?",
    ],
}
const GENERIC = ["What is this collection about?", "Group the documents by topic.", "Which documents contain the most figures and what do they show?"]

const newThread = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}`)

function readStored(key: string) {
    try {
        return window.localStorage.getItem(key)
    } catch {
        return null
    }
}

function writeStored(key: string, value: string) {
    try {
        window.localStorage.setItem(key, value)
    } catch {
        /* private mode or blocked storage: the preference just isn't remembered */
    }
}

export default function PageIndexApp() {
    const [collections, setCollections] = useState<Collection[]>([])
    const [collection, setCollection] = useState("")
    const [docs, setDocs] = useState<DocumentInfo[]>([])
    const [runs, setRuns] = useState<RecordedRun[]>([])
    const [turns, setTurns] = useState<Turn[]>([])
    const [threadId, setThreadId] = useState(newThread)
    const [input, setInput] = useState("")
    const [source, setSource] = useState<SourceTarget | null>(null)
    const [uploading, setUploading] = useState(false)
    const [navOpen, setNavOpen] = useState(false)
    const [apiError, setApiError] = useState<string>()
    const bottom = useRef<HTMLDivElement>(null)
    const busy = turns.some((t) => !t.done)

    const refreshCollections = useCallback(async (prefer?: string) => {
        try {
            const cs = await listCollections()
            setCollections(cs)
            setApiError(undefined)
            setCollection((cur) => {
                const want = prefer || cur || readStored("pageindex.collection") || "litreview"
                return cs.some((c) => c.name === want) ? want : cs[0]?.name ?? ""
            })
        } catch {
            setApiError("Can't reach the PageIndex API. Is the server running? (./scripts/run_demo.sh)")
        }
    }, [])

    useEffect(() => {
        refreshCollections()
        listRuns().then(setRuns).catch(() => {})
    }, [refreshCollections])

    useEffect(() => {
        if (!collection) return
        writeStored("pageindex.collection", collection)
        listDocuments(collection).then(setDocs).catch(() => setDocs([]))
    }, [collection])

    useEffect(() => {
        bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" })
    }, [turns])

    const update = (id: string, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)))

    const handlers = (id: string): StreamHandlers => ({
        onTrace: (e) => update(id, (t) => ({ ...t, events: [...t.events, e] })),
        onAnswer: (a) => update(id, (t) => ({ ...t, answer: a.answer, citations: a.citations, blocked: a.blocked })),
        onStats: (s) => update(id, (t) => ({ ...t, stats: s })),
        onError: (message) => update(id, (t) => ({ ...t, error: message })),
    })

    async function run(question: string, go: (h: StreamHandlers) => Promise<void>, isReplay = false) {
        const id = `${Date.now()}`
        setTurns((ts) => [...ts, { id, question, events: [], citations: [], done: false, replay: isReplay }])
        try {
            await go(handlers(id))
        } catch (e) {
            update(id, (t) => ({ ...t, error: String((e as Error).message || e) }))
        } finally {
            update(id, (t) => ({ ...t, done: true }))
            if (!isReplay) listRuns().then(setRuns).catch(() => {})
        }
    }

    const submit = (q = input) => {
        const question = q.trim()
        if (!question || busy || !collection) return
        setInput("")
        run(question, (h) => ask(question, collection, threadId, h))
    }

    const newChat = () => {
        setTurns([])
        setThreadId(newThread())
        setSource(null)
    }

    const changeCollection = (c: string) => {
        setCollection(c)
        newChat()
    }

    const onDeleteDoc = async (d: DocumentInfo) => {
        if (!window.confirm(`Remove “${d.title}” from ${collection}?`)) return
        await deleteDocument(collection, d.doc_id).catch(() => {})
        if (source?.docId === d.doc_id) setSource(null)
        listDocuments(collection).then(setDocs)
        refreshCollections()
    }

    const openNode = useCallback((docId: string, nodeId?: string) => setSource({ docId, nodeId }), [])
    const suggestions = SUGGESTIONS[collection] ?? GENERIC

    return (
        <div className="flex h-dvh bg-background text-foreground">
            <div className={cn("fixed inset-y-0 left-0 z-40 w-72 transition-transform md:static md:translate-x-0",
                navOpen ? "translate-x-0" : "-translate-x-full")}>
                <Sidebar
                    collections={collections} collection={collection} onCollection={changeCollection}
                    docs={docs} runs={runs} busy={busy} activeDoc={source?.docId}
                    onNewChat={newChat} onOpenDoc={(id) => { openNode(id); setNavOpen(false) }} onDeleteDoc={onDeleteDoc}
                    onReplay={(r) => { setNavOpen(false); run(r.question, (h) => replay(r.run_id, h), true) }}
                    onUpload={() => setUploading(true)}
                />
            </div>
            {navOpen && <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setNavOpen(false)} />}

            <div className="flex min-w-0 flex-1 flex-col">
                <header className="flex items-center gap-2 border-b border-border px-4 py-2.5 md:hidden">
                    <button onClick={() => setNavOpen(true)} aria-label="Open sidebar"><Menu className="w-4 h-4" /></button>
                    <Network className="w-4 h-4 text-primary" />
                    <span className="text-xs uppercase tracking-widest">PageIndex</span>
                    <span className="ml-auto truncate text-[10px] text-muted-foreground">{collection}</span>
                </header>

                <main className="flex-1 overflow-y-auto px-4 py-6">
                    <div className="mx-auto max-w-3xl space-y-6">
                        {apiError && (
                            <div className="rounded-sm border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">{apiError}</div>
                        )}
                        {turns.length === 0 && !apiError && (
                            <div className="pt-16 text-center">
                                <Network className="mx-auto w-7 h-7 text-primary/80" />
                                <h1 className="mt-3 text-lg font-sans font-semibold">Ask your documents</h1>
                                <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
                                    The agent reads the catalog, opens each document&apos;s table of contents and reads only the
                                    sections it needs. You see the path it took, and every claim links to its source.
                                </p>
                                <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                                    {suggestions.map((s) => (
                                        <button key={s} onClick={() => submit(s)} disabled={!collection}
                                            className="rounded-sm border border-border bg-card px-3 py-2.5 text-left text-[11px] leading-snug text-foreground/85 hover:border-primary/60">
                                            {s}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                        {turns.map((t) => (
                            <div key={t.id} className="space-y-2.5">
                                <div className="flex justify-end">
                                    <div className="max-w-[85%] rounded-sm border border-border bg-secondary px-3 py-2 text-sm">{t.question}</div>
                                </div>
                                {t.replay && (
                                    <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                                        <Play className="w-3 h-3" /> Replay of a recorded run · no LLM calls
                                    </div>
                                )}
                                <SearchTrace events={t.events} done={t.done || !!t.stats} answered={!!t.answer}
                                    error={t.error} citations={t.citations} onOpenNode={openNode} />
                                {t.answer && (
                                    <AnswerCard answer={t.answer} citations={t.citations} stats={t.stats} blocked={t.blocked}
                                        onCite={(c) => openNode(c.doc_id, c.node_id === "catalog" ? undefined : c.node_id)} />
                                )}
                            </div>
                        ))}
                        <div ref={bottom} />
                    </div>
                </main>

                <footer className="border-t border-border px-4 py-3">
                    <form className="mx-auto flex max-w-3xl gap-2" onSubmit={(e) => { e.preventDefault(); submit() }}>
                        <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy || !collection}
                            placeholder={collection ? (turns.length ? "Ask a follow-up…" : `Ask about ${collection}…`) : "Add documents to start"}
                            className="flex-1 rounded-sm border border-border bg-card px-3 py-2 text-sm focus:border-primary/60 focus:outline-none" />
                        <button type="submit" disabled={busy || !input.trim() || !collection} aria-label="Send"
                            className="rounded-sm bg-primary px-3 text-primary-foreground disabled:opacity-40">
                            <Send className="w-4 h-4" />
                        </button>
                    </form>
                </footer>
            </div>

            {source && collection && (
                <div className="fixed inset-0 z-40 lg:static lg:inset-auto lg:z-auto lg:w-[440px] lg:shrink-0">
                    <SourceViewer collection={collection} target={source} onClose={() => setSource(null)} />
                </div>
            )}

            {uploading && (
                <UploadDialog collection={collection || "documents"} onClose={() => setUploading(false)}
                    onIndexed={(c) => { refreshCollections(c); if (c === collection) listDocuments(c).then(setDocs) }} />
            )}
        </div>
    )
}
