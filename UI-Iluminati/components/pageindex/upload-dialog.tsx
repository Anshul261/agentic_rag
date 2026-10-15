"use client"

import { useEffect, useRef, useState } from "react"
import { CheckCircle2, CircleAlert, Loader2, Upload, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { getJob, uploadDocuments, type UploadJob } from "@/lib/api"

const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.png,.jpg,.jpeg,.tiff"
const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/

const STATUS_LABEL: Record<string, string> = {
    queued: "queued", parsing: "parsing", parsed: "parsed", cached: "already parsed", summarizing: "summarizing",
    titled: "summarizing", stored: "indexed", skipped: "already indexed", duplicate: "duplicate", failed: "failed",
}

export function UploadDialog({ collection, onClose, onIndexed }: {
    collection: string
    onClose: () => void
    onIndexed: (collection: string) => void
}) {
    const [target, setTarget] = useState(collection)
    const [files, setFiles] = useState<File[]>([])
    const [job, setJob] = useState<UploadJob | null>(null)
    const [error, setError] = useState<string>()
    const [busy, setBusy] = useState(false)
    const input = useRef<HTMLInputElement>(null)
    const validName = NAME_RE.test(target)

    useEffect(() => {
        if (!job || job.state !== "running") return
        const t = setInterval(async () => {
            try {
                const next = await getJob(job.job_id)
                setJob(next)
                if (next.state !== "running") onIndexed(next.collection)
            } catch (e) {
                setError(String((e as Error).message))
            }
        }, 1500)
        return () => clearInterval(t)
    }, [job, onIndexed])

    async function start() {
        setError(undefined)
        setBusy(true)
        try {
            const { job_id } = await uploadDocuments(target, files)
            const first = await getJob(job_id)
            setJob(first)
            // Cached files can finish before the first poll; refresh the app either way.
            if (first.state !== "running") onIndexed(first.collection)
        } catch (e) {
            setError(String((e as Error).message))
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
            <div className="w-full max-w-lg rounded-sm border border-border bg-card p-4 font-mono" onClick={(e) => e.stopPropagation()}>
                <div className="mb-3 flex items-center">
                    <span className="text-xs uppercase tracking-widest">Add documents</span>
                    <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground" aria-label="Close">
                        <X className="w-4 h-4" />
                    </button>
                </div>

                {!job && (
                    <div className="space-y-3">
                        <label className="block text-[10px] uppercase tracking-wider text-muted-foreground">
                            Collection
                            <input value={target} onChange={(e) => setTarget(e.target.value.trim().toLowerCase())}
                                className={cn("mt-1 w-full rounded-sm border bg-background px-2 py-1.5 text-xs normal-case tracking-normal text-foreground",
                                    validName ? "border-border" : "border-destructive")} />
                            <span className="normal-case tracking-normal">A new name creates a new collection.</span>
                        </label>
                        <button onClick={() => input.current?.click()}
                            className="flex w-full flex-col items-center gap-1.5 rounded-sm border border-dashed border-border py-6 text-xs text-muted-foreground hover:border-primary/60 hover:text-foreground">
                            <Upload className="w-5 h-5 text-primary" />
                            {files.length ? `${files.length} file${files.length === 1 ? "" : "s"} selected` : "Choose files"}
                            <span className="text-[10px]">PDF, DOCX, PPTX, XLSX, HTML, Markdown, images</span>
                        </button>
                        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden"
                            onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
                        {files.length > 0 && (
                            <ul className="max-h-32 overflow-y-auto text-[11px] text-foreground/80">
                                {files.map((f) => <li key={f.name} className="truncate">· {f.name}</li>)}
                            </ul>
                        )}
                        <p className="text-[10px] text-muted-foreground">
                            Each file is parsed into a section tree, then summarized by the cheap model (about $0.005 per paper).
                        </p>
                        <button onClick={start} disabled={!files.length || !validName || busy}
                            className="w-full rounded-sm bg-primary py-2 text-xs uppercase tracking-widest text-primary-foreground disabled:opacity-40">
                            {busy ? "Uploading…" : "Upload and index"}
                        </button>
                    </div>
                )}

                {job && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-xs">
                            {job.state === "running" ? <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
                                : job.state === "done" ? <CheckCircle2 className="w-3.5 h-3.5 text-primary" />
                                : <CircleAlert className="w-3.5 h-3.5 text-destructive" />}
                            <span>{job.state === "running" ? `Indexing into “${job.collection}”… ${job.elapsed}s` : job.summary}</span>
                        </div>
                        <ul className="max-h-60 space-y-1 overflow-y-auto text-[11px]">
                            {[...job.files, ...job.rejected.map((r) => ({ ...r, status: "rejected" }))].map((f) => (
                                <li key={f.filename} className="flex gap-2">
                                    <span className={cn("w-28 shrink-0",
                                        f.status === "stored" ? "text-primary" : ["failed", "rejected"].includes(f.status) ? "text-destructive" : "text-muted-foreground")}>
                                        {STATUS_LABEL[f.status] ?? f.status}
                                    </span>
                                    <span className="truncate" title={f.message}>{f.filename}</span>
                                </li>
                            ))}
                        </ul>
                        {job.state !== "running" && (
                            <button onClick={onClose} className="w-full rounded-sm border border-border py-1.5 text-xs uppercase tracking-widest hover:border-primary/60">
                                Done
                            </button>
                        )}
                    </div>
                )}
                {error && <div className="mt-2 text-[11px] text-destructive">{error}</div>}
            </div>
        </div>
    )
}
