"use client"

import { useMemo, useState, type ReactElement } from "react"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Citation, TraceEvent, TraceNode } from "@/lib/api"

/**
 * Compact visualization of a PageIndex search: collection -> documents opened ->
 * top-level branches -> sections actually read. The read path is highlighted;
 * sibling branches the agent saw but skipped are dimmed. Answers that came from
 * the catalog alone show the cited documents instead.
 */

const MAX_DOCS = 3
const MAX_LEAVES = 3
const MAX_DIM_BRANCHES = 2
const ROW = 30
const NODE_H = 24
const COLS = [
    { x: 0, w: 118 },
    { x: 150, w: 178 },
    { x: 360, w: 178 },
    { x: 570, w: 190 },
]
const WIDTH = 760

const STAGES = ["Catalog", "Search", "Open trees", "Read", "Answer"] as const
type StageState = "done" | "active" | "skipped" | "pending"

// Boilerplate sections make poor context when shown as skipped siblings.
const BOILERPLATE = /^(front matter|abstract|references|bibliography|acknowledg|keywords|article info|declaration|data availability|funding)/i

interface Leaf extends TraceNode {
    figure: boolean
}
interface Branch extends TraceNode {
    onPath: boolean
    leaves: Leaf[]
}
interface DocModel {
    doc_id: string
    title: string
    branches: Map<string, Branch>
    nRead: number
    fromCatalog?: boolean
}

function buildModel(events: TraceEvent[], citations: Citation[]) {
    const docs = new Map<string, DocModel>()
    let nDocs = 0
    const doc = (id: string, title: string) => {
        if (!docs.has(id)) docs.set(id, { doc_id: id, title, branches: new Map(), nRead: 0 })
        return docs.get(id)!
    }
    const addRead = (n: { doc_id: string; doc_title: string; path: TraceNode[] } & TraceNode, figure: boolean) => {
        const d = doc(n.doc_id, n.doc_title)
        const top = n.path[0] ?? n
        let b = d.branches.get(top.node_id)
        if (!b) {
            b = { ...top, onPath: true, leaves: [] }
            d.branches.set(top.node_id, b)
        }
        b.onPath = true
        // Middle levels are skipped in the compact view: top-level branch -> section read.
        if (n.path.length > 0 && !b.leaves.some((l) => l.node_id === n.node_id)) b.leaves.push({ ...n, figure })
        d.nRead += 1
    }
    for (const e of events) {
        if (e.kind === "catalog") nDocs = e.n_docs
        else if (e.kind === "open_doc") {
            const d = doc(e.doc_id, e.doc_title)
            for (const br of e.branches) {
                if (BOILERPLATE.test(br.title)) continue
                if (!d.branches.has(br.node_id)) d.branches.set(br.node_id, { ...br, onPath: false, leaves: [] })
            }
        } else if (e.kind === "read") e.nodes.forEach((n) => addRead(n, n.kind === "figure"))
        else if (e.kind === "figure") addRead(e, true)
    }
    const fromCatalog = ![...docs.values()].some((d) => d.nRead > 0)
    if (fromCatalog) {
        // Answered from catalog summaries: the cited documents are the result.
        for (const c of citations) {
            const d = doc(c.doc_id, c.doc_title)
            d.fromCatalog = true
        }
    }
    return { docs: [...docs.values()], nDocs, fromCatalog: fromCatalog && citations.length > 0 }
}

function stageStates(events: TraceEvent[], done: boolean, answered: boolean): StageState[] {
    const seen = [
        events.some((e) => e.kind === "catalog"),
        events.some((e) => e.kind === "search"),
        events.some((e) => e.kind === "open_doc"),
        events.some((e) => e.kind === "read" || e.kind === "figure"),
        answered,
    ]
    const last = seen.lastIndexOf(true)
    return seen.map((s, i) => {
        if (s) return "done"
        if (done) return "skipped"
        if (i === last + 1) return "active"
        return i < last ? "skipped" : "pending"
    })
}

function latestAction(events: TraceEvent[]): string {
    const e = events[events.length - 1]
    if (!e) return "Starting…"
    switch (e.kind) {
        case "catalog":
            return `Reading catalog of ${e.n_docs} documents`
        case "search":
            return `Searching “${e.query}” · ${e.hits.length} hits`
        case "open_doc":
            return `Opening tree · ${e.doc_title}`
        case "read":
            return `Reading ${e.nodes.length} section${e.nodes.length === 1 ? "" : "s"}`
        case "figure":
            return `Inspecting figure · ${e.title}`
    }
}

const clip = (s: string, w: number) => {
    const max = Math.floor((w - 14) / 6.2)
    return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function edge(x1: number, y1: number, x2: number, y2: number) {
    const mx = (x1 + x2) / 2
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
}

type Variant = "root" | "doc" | "path" | "dim" | "leaf"

const VARIANTS: Record<Variant, { fill: string; stroke: string; text: string; sub: string }> = {
    root: { fill: "var(--card)", stroke: "var(--border)", text: "var(--foreground)", sub: "var(--muted-foreground)" },
    doc: { fill: "rgba(224,122,58,0.08)", stroke: "rgba(224,122,58,0.55)", text: "var(--foreground)", sub: "var(--muted-foreground)" },
    path: { fill: "rgba(224,122,58,0.14)", stroke: "rgba(224,122,58,0.75)", text: "var(--foreground)", sub: "#b58a6c" },
    dim: { fill: "var(--card)", stroke: "var(--border)", text: "#5a5a5a", sub: "#444" },
    leaf: { fill: "#E07A3A", stroke: "#E07A3A", text: "#fff", sub: "rgba(255,255,255,0.8)" },
}

function Box({ x, y, w, label, sub, variant, title, onClick }: {
    x: number; y: number; w: number; label: string; sub?: string; variant: Variant; title: string; onClick?: () => void
}) {
    const s = VARIANTS[variant]
    return (
        <g className={cn("pi-fade", onClick && "cursor-pointer")} onClick={onClick}>
            <title>{title}</title>
            <rect x={x} y={y - NODE_H / 2} width={w} height={NODE_H} rx={3} fill={s.fill} stroke={s.stroke} />
            <text x={x + 7} y={y + 1} fontSize={10.5} fill={s.text} dominantBaseline="middle"
                fontFamily="var(--font-mono)" fontWeight={variant === "leaf" ? 600 : 400}>
                {clip(label, sub ? w - 46 : w)}
            </text>
            {sub && (
                <text x={x + w - 6} y={y + 1} fontSize={9.5} fill={s.sub} textAnchor="end"
                    dominantBaseline="middle" fontFamily="var(--font-mono)">
                    {sub}
                </text>
            )}
        </g>
    )
}

export function SearchTrace({ events, done, answered, error, citations = [], onOpenNode }: {
    events: TraceEvent[]
    done: boolean
    answered: boolean
    error?: string
    citations?: Citation[]
    onOpenNode?: (docId: string, nodeId?: string) => void
}) {
    const [open, setOpen] = useState(true)
    const { docs, nDocs, fromCatalog } = useMemo(() => buildModel(events, citations), [events, citations])
    const stages = stageStates(events, done, answered)

    const layout = useMemo(() => {
        // Once reading starts, the read path is the story: opened-but-unread documents collapse.
        const reading = docs.some((d) => d.nRead > 0)
        const candidates = reading ? docs.filter((d) => d.nRead > 0) : docs
        const shown = candidates.slice(0, MAX_DOCS)
        const unreadOpened = reading ? docs.length - candidates.length : 0
        let row = 0
        const nodes: ReactElement[] = []
        const edges: { d: string; hot: boolean }[] = []
        const docYs: number[] = []
        for (const d of shown) {
            const onPath = [...d.branches.values()].filter((b) => b.onPath)
            // Fewer skipped siblings when several documents share the view.
            const dimMax = shown.length > 1 ? 1 : MAX_DIM_BRANCHES
            const dim = [...d.branches.values()].filter((b) => !b.onPath).slice(0, dimMax)
            const branches = [...onPath, ...dim]
            const docTop = row
            const branchYs: number[] = []
            if (branches.length === 0) row += 1
            for (const b of branches) {
                // Figures first: they are the most telling part of a search path.
                const leaves = [...b.leaves].sort((x, y) => Number(y.figure) - Number(x.figure)).slice(0, MAX_LEAVES)
                const extra = b.leaves.length - leaves.length
                const span = Math.max(1, leaves.length + (extra > 0 ? 1 : 0))
                const by = (row + span / 2) * ROW
                branchYs.push(by)
                const isLeafItself = b.onPath && b.leaves.length === 0
                nodes.push(<Box key={`${d.doc_id}-${b.node_id}`} x={COLS[2].x} y={by} w={COLS[2].w}
                    label={b.title} sub={`p${b.pages}`} variant={isLeafItself ? "leaf" : b.onPath ? "path" : "dim"}
                    title={`${b.title} (p${b.pages})`} onClick={() => onOpenNode?.(d.doc_id, b.node_id)} />)
                leaves.forEach((l, i) => {
                    const ly = (row + i + 0.5) * ROW
                    edges.push({ d: edge(COLS[2].x + COLS[2].w, by, COLS[3].x, ly), hot: true })
                    nodes.push(<Box key={`${d.doc_id}-${l.node_id}`} x={COLS[3].x} y={ly} w={COLS[3].w}
                        label={`${l.figure ? "▣ " : ""}${l.title}`} sub={`p${l.pages}`} variant="leaf"
                        title={`${l.title} (p${l.pages})`} onClick={() => onOpenNode?.(d.doc_id, l.node_id)} />)
                })
                if (extra > 0) {
                    nodes.push(<text key={`${d.doc_id}-${b.node_id}-more`} x={COLS[3].x + 6} y={(row + leaves.length + 0.5) * ROW}
                        fontSize={9.5} fill="var(--muted-foreground)" dominantBaseline="middle"
                        fontFamily="var(--font-mono)">+{extra} more sections</text>)
                }
                row += span
            }
            const dy = ((docTop + row) / 2) * ROW
            docYs.push(dy)
            branchYs.forEach((by, i) => edges.push({
                d: edge(COLS[1].x + COLS[1].w, dy, COLS[2].x, by), hot: branches[i]?.onPath ?? false,
            }))
            const hot = d.nRead > 0 || d.fromCatalog
            nodes.push(<Box key={d.doc_id} x={COLS[1].x} y={dy} w={COLS[1].w} label={d.title}
                sub={d.nRead ? `${d.nRead}✓` : d.fromCatalog ? "cited" : undefined}
                variant={hot ? "doc" : "dim"} title={d.title} onClick={() => onOpenNode?.(d.doc_id)} />)
            row += 0.35 // gap between documents
        }
        const hidden = candidates.length - shown.length
        const notes = [hidden > 0 && `+${hidden} more documents`, unreadOpened > 0 && `+${unreadOpened} opened, not read`]
            .filter(Boolean).join(" · ")
        if (notes) {
            nodes.push(<text key="more-docs" x={COLS[1].x + 6} y={(row + 0.4) * ROW} fontSize={9.5}
                fill="var(--muted-foreground)" dominantBaseline="middle" fontFamily="var(--font-mono)">
                {notes}</text>)
            row += 0.8
        }
        const height = Math.max(row, 1.2) * ROW
        const rootY = docYs.length ? (docYs[0] + docYs[docYs.length - 1]) / 2 : height / 2
        docYs.forEach((dy, i) => edges.push({
            d: edge(COLS[0].x + COLS[0].w, rootY, COLS[1].x, dy),
            hot: (shown[i]?.nRead ?? 0) > 0 || !!shown[i]?.fromCatalog,
        }))
        nodes.unshift(<Box key="root" x={COLS[0].x} y={rootY} w={COLS[0].w} label={`${nDocs} docs`}
            variant="root" title={`Collection: ${nDocs} documents`} />)
        return { nodes, edges, height }
    }, [docs, nDocs, onOpenNode])

    const nRead = docs.reduce((a, d) => a + d.nRead, 0)
    const summary = fromCatalog
        ? `answered from catalog · ${docs.length} doc${docs.length === 1 ? "" : "s"} cited`
        : `${docs.filter((d) => d.nRead > 0).length || docs.length} doc${docs.length === 1 ? "" : "s"} · ${nRead} section${nRead === 1 ? "" : "s"} read`
    const status = error ? `Error: ${error}` : done ? (answered ? "Done" : "Finished without an answer") : latestAction(events)

    return (
        <div className="border border-border rounded-sm bg-card/60 px-3 py-2 font-mono">
            <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 text-left">
                {open ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
                <span className="text-[10px] uppercase tracking-widest text-muted-foreground">Search path</span>
                <span className="text-[10px] text-muted-foreground truncate">· {summary}</span>
                {!done && <Loader2 className="w-3 h-3 text-primary animate-spin ml-auto shrink-0" />}
            </button>

            {open && (
                <>
                    <div className="mt-2.5 mb-1 flex items-center">
                        {STAGES.map((s, i) => (
                            <div key={s} className={cn("flex items-center", i < STAGES.length - 1 && "flex-1")}>
                                <div className={cn(
                                    "w-2 h-2 rounded-full border transition-colors",
                                    stages[i] === "done" && "bg-primary border-primary",
                                    stages[i] === "active" && "border-primary animate-pulse",
                                    stages[i] === "skipped" && "border-border border-dashed",
                                    stages[i] === "pending" && "border-border",
                                )} />
                                {i < STAGES.length - 1 && (
                                    <div className={cn("h-px flex-1 mx-1",
                                        stages[i + 1] === "done" ? "bg-primary" : "bg-border")} />
                                )}
                            </div>
                        ))}
                    </div>
                    <div className="flex justify-between text-[9px] uppercase tracking-wider mb-2">
                        {STAGES.map((s, i) => (
                            <span key={s} className={cn(
                                stages[i] === "done" && "text-foreground/75",
                                stages[i] === "active" && "text-primary",
                                (stages[i] === "skipped" || stages[i] === "pending") && "text-muted-foreground/60",
                                stages[i] === "skipped" && "line-through decoration-muted-foreground/40",
                            )} title={stages[i] === "skipped" ? "Not needed for this question" : undefined}>{s}</span>
                        ))}
                    </div>

                    {docs.length > 0 && (
                        <svg viewBox={`0 0 ${WIDTH} ${layout.height}`} className="w-full h-auto" role="img"
                            aria-label="Document tree search path">
                            {layout.edges.map((e, i) => (
                                <path key={i} d={e.d} fill="none" className="pi-fade"
                                    stroke={e.hot ? "rgba(224,122,58,0.7)" : "#2f2f2f"} strokeWidth={e.hot ? 1.4 : 1} />
                            ))}
                            {layout.nodes}
                        </svg>
                    )}

                    <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0",
                            error ? "bg-destructive" : done ? "bg-muted-foreground" : "bg-primary animate-pulse")} />
                        <span className={cn("truncate", error && "text-destructive")}>{status}</span>
                    </div>
                </>
            )}
        </div>
    )
}
