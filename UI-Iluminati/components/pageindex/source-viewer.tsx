"use client"

import { useEffect, useMemo, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { ChevronDown, ChevronRight, FileText, Image as ImageIcon, Loader2, Table2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { figureUrl, getDocument, getNode, type DocumentTree, type NodeDetail, type TreeNodeInfo } from "@/lib/api"

export interface SourceTarget {
    docId: string
    nodeId?: string
}

function findPath(nodes: TreeNodeInfo[], id: string, trail: string[] = []): string[] | null {
    for (const n of nodes) {
        if (n.node_id === id) return [...trail, n.node_id]
        const found = findPath(n.children, id, [...trail, n.node_id])
        if (found) return found
    }
    return null
}

const KIND_ICON = { section: FileText, figure: ImageIcon, table: Table2 }

function TreeItem({ node, depth, selected, expanded, onToggle, onSelect }: {
    node: TreeNodeInfo
    depth: number
    selected?: string
    expanded: Set<string>
    onToggle: (id: string) => void
    onSelect: (id: string) => void
}) {
    const Icon = KIND_ICON[node.kind] ?? FileText
    const isOpen = expanded.has(node.node_id)
    const hasKids = node.children.length > 0
    return (
        <li>
            <div
                className={cn(
                    "group flex items-center gap-1 rounded-sm pr-2 text-[11px] leading-6 cursor-pointer",
                    node.node_id === selected ? "bg-primary text-primary-foreground" : "hover:bg-muted text-foreground/85",
                )}
                style={{ paddingLeft: depth * 12 + 2 }}
                onClick={() => onSelect(node.node_id)}
            >
                <button
                    className={cn("w-3.5 h-3.5 shrink-0 flex items-center justify-center", !hasKids && "invisible")}
                    onClick={(e) => { e.stopPropagation(); onToggle(node.node_id) }}
                    aria-label={isOpen ? "Collapse" : "Expand"}
                >
                    {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                </button>
                <Icon className={cn("w-3 h-3 shrink-0", node.node_id === selected ? "" : "text-muted-foreground")} />
                <span className="truncate flex-1">{node.title}</span>
                <span className={cn("text-[10px] shrink-0", node.node_id === selected ? "text-primary-foreground/80" : "text-muted-foreground")}>
                    p{node.pages}
                </span>
            </div>
            {hasKids && isOpen && (
                <ul>
                    {node.children.map((c) => (
                        <TreeItem key={c.node_id} node={c} depth={depth + 1} selected={selected} expanded={expanded}
                            onToggle={onToggle} onSelect={onSelect} />
                    ))}
                </ul>
            )}
        </li>
    )
}

export function SourceViewer({ collection, target, onClose }: {
    collection: string
    target: SourceTarget
    onClose: () => void
}) {
    const [doc, setDoc] = useState<DocumentTree | null>(null)
    const [selected, setSelected] = useState<string | undefined>(target.nodeId)
    const [node, setNode] = useState<NodeDetail | null>(null)
    const [expanded, setExpanded] = useState<Set<string>>(new Set())
    const [error, setError] = useState<string>()
    const [loadingNode, setLoadingNode] = useState(false)

    useEffect(() => {
        setDoc(null)
        setError(undefined)
        getDocument(collection, target.docId).then(setDoc).catch((e) => setError(String(e.message || e)))
    }, [collection, target.docId])

    useEffect(() => setSelected(target.nodeId), [target])

    // Expand the path to the selected node so it is visible in the tree.
    useEffect(() => {
        if (!doc || !selected) return
        const path = findPath(doc.nodes, selected)
        if (path) setExpanded((prev) => new Set([...prev, ...path.slice(0, -1)]))
    }, [doc, selected])

    useEffect(() => {
        if (!selected || selected === "catalog") {
            setNode(null)
            return
        }
        setLoadingNode(true)
        getNode(collection, target.docId, selected)
            .then(setNode)
            .catch(() => setNode(null))
            .finally(() => setLoadingNode(false))
    }, [collection, target.docId, selected])

    const toggle = (id: string) =>
        setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })

    const isTable = node?.kind === "table"
    const counts = useMemo(() => {
        const c = { section: 0, figure: 0, table: 0 }
        const walk = (ns: TreeNodeInfo[]) => ns.forEach((n) => { c[n.kind] += 1; walk(n.children) })
        if (doc) walk(doc.nodes)
        return c
    }, [doc])

    return (
        <aside className="flex h-full w-full flex-col border-l border-border bg-background">
            <div className="flex items-start gap-2 border-b border-border px-4 py-3">
                <div className="min-w-0 flex-1">
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Source</div>
                    <div className="text-sm font-medium leading-snug">{doc?.title ?? (error ? "Not found" : "Loading…")}</div>
                    {doc && (
                        <div className="mt-0.5 text-[10px] text-muted-foreground truncate">
                            {doc.filename} · {doc.n_pages} pages · {counts.section} sections · {counts.figure} figures · {counts.table} tables
                        </div>
                    )}
                </div>
                <button onClick={onClose} className="text-muted-foreground hover:text-foreground" aria-label="Close source viewer">
                    <X className="w-4 h-4" />
                </button>
            </div>

            {error && <div className="p-4 text-xs text-destructive">{error}</div>}

            {doc && (
                <>
                    <div className="max-h-[42%] overflow-y-auto border-b border-border px-2 py-2">
                        <ul>
                            {doc.nodes.map((n) => (
                                <TreeItem key={n.node_id} node={n} depth={0} selected={selected} expanded={expanded}
                                    onToggle={toggle} onSelect={setSelected} />
                            ))}
                        </ul>
                    </div>

                    <div className="flex-1 overflow-y-auto px-4 py-3">
                        {!node && !loadingNode && (
                            <div className="space-y-2">
                                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Document summary</div>
                                <p className="text-xs leading-relaxed text-foreground/85">{doc.summary || "No summary."}</p>
                                <p className="text-[10px] text-muted-foreground">Select a section in the tree to read it.</p>
                            </div>
                        )}
                        {loadingNode && <Loader2 className="w-4 h-4 animate-spin text-primary" />}
                        {node && !loadingNode && (
                            <div className="space-y-3">
                                {node.path.length > 0 && (
                                    <div className="text-[10px] text-muted-foreground leading-relaxed">
                                        {node.path.map((p) => p.title).join("  ›  ")}
                                    </div>
                                )}
                                <div>
                                    <div className="text-sm font-medium leading-snug">{node.title}</div>
                                    <div className="text-[10px] text-muted-foreground">
                                        {node.kind} · p{node.pages} · node {node.node_id}
                                    </div>
                                </div>
                                {node.summary && (
                                    <div className="border-l-2 border-primary/60 pl-2 text-xs text-foreground/80 leading-relaxed">
                                        {node.summary}
                                    </div>
                                )}
                                {node.image_url && (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img src={figureUrl(node.image_url)} alt={node.title}
                                        className="w-full rounded-sm border border-border bg-white" />
                                )}
                                {node.text && (
                                    isTable ? (
                                        <div className="answer-md text-xs overflow-x-auto">
                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{node.text}</ReactMarkdown>
                                        </div>
                                    ) : (
                                        <div className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{node.text}</div>
                                    )
                                )}
                                {node.truncated && <div className="text-[10px] text-muted-foreground">Text truncated.</div>}
                                {!node.text && !node.image_url && (
                                    <div className="text-[11px] text-muted-foreground">This section has no body text of its own; open its subsections in the tree.</div>
                                )}
                            </div>
                        )}
                    </div>
                </>
            )}
        </aside>
    )
}
