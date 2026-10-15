"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { ArrowLeft, Network, Play, Send } from "lucide-react"
import { SearchTrace } from "@/components/pageindex/search-trace"
import {
    listPageIndexCollections,
    listPageIndexRuns,
    queryPageIndex,
    replayPageIndexRun,
    type PageIndexCitation,
    type PageIndexCollection,
    type PageIndexHandlers,
    type PageIndexRun,
    type PageIndexStats,
    type TraceEvent,
} from "@/lib/api"

interface Turn {
    id: string
    question: string
    events: TraceEvent[]
    answer?: string
    citations: PageIndexCitation[]
    stats?: PageIndexStats
    error?: string
    done: boolean
    replay?: boolean
}

export default function PageIndexChat() {
    const [collections, setCollections] = useState<PageIndexCollection[]>([])
    const [collection, setCollection] = useState("litreview")
    const [runs, setRuns] = useState<PageIndexRun[]>([])
    const [turns, setTurns] = useState<Turn[]>([])
    const [input, setInput] = useState("")
    const busy = turns.some((t) => !t.done)
    const bottom = useRef<HTMLDivElement>(null)

    useEffect(() => {
        listPageIndexCollections().then((c) => {
            setCollections(c)
            if (c.length && !c.some((x) => x.name === "litreview")) setCollection(c[0].name)
        })
        listPageIndexRuns().then(setRuns)
    }, [])

    useEffect(() => {
        bottom.current?.scrollIntoView({ behavior: "smooth" })
    }, [turns])

    const update = (id: string, f: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? f(t) : t)))

    const handlersFor = (id: string): PageIndexHandlers => ({
        onTrace: (e) => update(id, (t) => ({ ...t, events: [...t.events, e] })),
        onAnswer: (a) => update(id, (t) => ({ ...t, answer: a.answer, citations: a.citations })),
        onStats: (s) => update(id, (t) => ({ ...t, stats: s })),
        onError: (message) => update(id, (t) => ({ ...t, error: message })),
    })

    async function start(question: string, run: (h: PageIndexHandlers) => Promise<void>, replay = false) {
        const id = `${Date.now()}`
        setTurns((ts) => [...ts, { id, question, events: [], citations: [], done: false, replay }])
        try {
            await run(handlersFor(id))
        } catch (e) {
            update(id, (t) => ({ ...t, error: String(e) }))
        } finally {
            update(id, (t) => ({ ...t, done: true }))
            if (!replay) listPageIndexRuns().then(setRuns)
        }
    }

    const ask = () => {
        const q = input.trim()
        if (!q || busy) return
        setInput("")
        start(q, (h) => queryPageIndex(q, collection, h))
    }

    const replay = (runId: string) => {
        const r = runs.find((x) => x.run_id === runId)
        if (r && !busy) start(r.question, (h) => replayPageIndexRun(runId, h), true)
    }

    return (
        <div className="flex h-screen flex-col bg-background text-foreground">
            <header className="flex items-center gap-3 border-b border-border px-4 py-2.5 font-mono">
                <Link href="/" className="text-muted-foreground hover:text-foreground" aria-label="Back to chat">
                    <ArrowLeft className="w-4 h-4" />
                </Link>
                <Network className="w-4 h-4 text-primary" />
                <span className="text-xs uppercase tracking-widest">PageIndex</span>
                <span className="text-[10px] text-muted-foreground hidden sm:inline">reasoning-based tree search</span>
                <div className="ml-auto flex items-center gap-2">
                    <select value={collection} onChange={(e) => setCollection(e.target.value)} disabled={busy}
                        className="bg-card border border-border rounded-sm text-[11px] px-2 py-1">
                        {(collections.length ? collections : [{ name: collection, n_docs: 0 }]).map((c) => (
                            <option key={c.name} value={c.name}>{c.name}{c.n_docs ? ` · ${c.n_docs} docs` : ""}</option>
                        ))}
                    </select>
                    {runs.length > 0 && (
                        <select value="" onChange={(e) => e.target.value && replay(e.target.value)} disabled={busy}
                            className="bg-card border border-border rounded-sm text-[11px] px-2 py-1 max-w-[180px]"
                            aria-label="Replay a saved run">
                            <option value="">▶ Replay saved run…</option>
                            {runs.map((r) => (
                                <option key={r.run_id} value={r.run_id}>{r.question.slice(0, 60)}</option>
                            ))}
                        </select>
                    )}
                </div>
            </header>

            <main className="flex-1 overflow-y-auto px-4 py-6">
                <div className="mx-auto max-w-3xl space-y-6">
                    {turns.length === 0 && (
                        <div className="text-center text-muted-foreground font-mono text-xs pt-24 space-y-2">
                            <Network className="w-6 h-6 mx-auto text-primary/70" />
                            <p>Ask about the documents. You&apos;ll see which trees the agent opens and which sections it reads.</p>
                        </div>
                    )}
                    {turns.map((t) => (
                        <div key={t.id} className="space-y-2.5">
                            <div className="flex justify-end">
                                <div className="max-w-[80%] bg-secondary border border-border rounded-sm px-3 py-2 text-sm">
                                    {t.question}
                                </div>
                            </div>
                            {t.replay && (
                                <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                                    <Play className="w-3 h-3" /> Replay of a saved run · no LLM calls
                                </div>
                            )}
                            <SearchTrace events={t.events} done={t.done || !!t.answer} error={t.error} />
                            {t.answer && (
                                <div className="bg-card border border-border rounded-sm px-4 py-3 space-y-3">
                                    <div className="prose prose-sm dark:prose-invert max-w-none">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.answer}</ReactMarkdown>
                                    </div>
                                    {t.citations.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5 border-t border-border pt-2.5">
                                            {t.citations.map((c, i) => (
                                                <span key={i} title={`${c.doc_title} · node ${c.node_id}`}
                                                    className="font-mono text-[10px] border border-primary/30 bg-primary/5 text-primary/90 rounded-sm px-1.5 py-0.5">
                                                    [{i + 1}] {c.doc_title.length > 38 ? `${c.doc_title.slice(0, 37)}…` : c.doc_title} · p{c.pages}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {t.stats && (
                                        <div className="font-mono text-[10px] text-muted-foreground">
                                            {t.stats.seconds}s · {t.stats.model_calls} model calls · {t.stats.tool_calls} tool calls · ${t.stats.cost_usd.toFixed(3)}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                    <div ref={bottom} />
                </div>
            </main>

            <footer className="border-t border-border px-4 py-3">
                <form className="mx-auto flex max-w-3xl gap-2" onSubmit={(e) => { e.preventDefault(); ask() }}>
                    <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy}
                        placeholder={`Ask about ${collection}…`}
                        className="flex-1 bg-card border border-border rounded-sm px-3 py-2 text-sm font-mono focus:outline-none focus:border-primary/60" />
                    <button type="submit" disabled={busy || !input.trim()} aria-label="Send"
                        className="bg-primary text-primary-foreground rounded-sm px-3 disabled:opacity-40">
                        <Send className="w-4 h-4" />
                    </button>
                </form>
            </footer>
        </div>
    )
}
