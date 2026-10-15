"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { Citation, RunStats } from "@/lib/api"

// "[2]" -> a link the renderer turns into a citation button. Leaves real markdown links alone.
const linkCitations = (md: string) => md.replace(/\[(\d{1,3})\](?!\()/g, "[$1](#cite-$1)")

export function AnswerCard({ answer, citations, stats, blocked, onCite }: {
    answer: string
    citations: Citation[]
    stats?: RunStats
    blocked?: boolean
    onCite: (c: Citation) => void
}) {
    return (
        <div className="space-y-3 rounded-sm border border-border bg-card px-4 py-3">
            {blocked && (
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    Blocked by the model provider&apos;s safety filter
                </div>
            )}
            <div className="answer-md text-sm">
                <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                        a: ({ href, children }) => {
                            const m = href?.match(/^#cite-(\d+)$/)
                            const c = m ? citations[Number(m[1]) - 1] : undefined
                            if (m) {
                                return (
                                    <button type="button" onClick={() => c && onCite(c)} disabled={!c}
                                        title={c ? `${c.doc_title} · p${c.pages}` : "citation"}
                                        className="cite-ref">
                                        {children}
                                    </button>
                                )
                            }
                            return <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
                        },
                    }}
                >
                    {linkCitations(answer)}
                </ReactMarkdown>
            </div>
            {citations.length > 0 && (
                <div className="flex flex-wrap gap-1.5 border-t border-border pt-2.5">
                    {citations.map((c, i) => (
                        <button key={i} type="button" onClick={() => onCite(c)}
                            title={`${c.doc_title} · node ${c.node_id}`}
                            className="max-w-full truncate rounded-sm border border-primary/30 bg-primary/5 px-1.5 py-0.5 font-mono text-[10px] text-primary/90 hover:border-primary/70">
                            [{i + 1}] {c.doc_title.length > 38 ? `${c.doc_title.slice(0, 37)}…` : c.doc_title}
                            {c.pages ? ` · p${c.pages}` : ""}
                        </button>
                    ))}
                </div>
            )}
            {stats && (
                <div className="font-mono text-[10px] text-muted-foreground">
                    {stats.seconds}s · {stats.model_calls} model calls · {stats.tool_calls} tool calls · ${stats.cost_usd.toFixed(3)}
                </div>
            )}
        </div>
    )
}
