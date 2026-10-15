/**
 * PageIndex API client. Talks to the FastAPI server directly (CORS-enabled).
 * There is no auth today; when an auth service is added, attach its credentials
 * in `request()` and the server's `get_principal` hook validates them.
 */

export const API_BASE = (process.env.NEXT_PUBLIC_PAGEINDEX_API || "http://localhost:7777").replace(/\/$/, "")
const BASE = `${API_BASE}/pageindex`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${BASE}${path}`, init)
    if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        const detail = typeof body.detail === "string" ? body.detail : body.detail?.message
        throw new Error(detail || `HTTP ${response.status}`)
    }
    return response.json()
}

// ---------------------------------------------------------------- types

export interface Collection {
    name: string
    n_docs: number
}

export interface DocumentInfo {
    doc_id: string
    title: string
    filename: string
    n_pages: number
    summary: string | null
    n_figures: number
    n_tables: number
}

export interface TreeNodeInfo {
    node_id: string
    kind: "section" | "figure" | "table"
    title: string
    pages: string
    summary: string | null
    children: TreeNodeInfo[]
}

export interface DocumentTree {
    doc_id: string
    title: string
    filename: string
    n_pages: number
    summary: string | null
    nodes: TreeNodeInfo[]
}

export interface NodeDetail {
    doc_id: string
    doc_title: string
    node_id: string
    kind: string
    title: string
    pages: string
    summary: string | null
    text: string
    truncated: boolean
    image_url: string | null
    path: { node_id: string; title: string }[]
}

export interface RecordedRun {
    run_id: string
    question: string
    collection: string
}

export interface TraceNode {
    node_id: string
    title: string
    pages: string
    kind?: string
}

export type TraceEvent =
    | { kind: "catalog"; n_docs: number }
    | { kind: "search"; query: string; hits: (TraceNode & { doc_id: string; doc_title: string })[] }
    | { kind: "open_doc"; doc_id: string; doc_title: string; n_pages: number; branches: TraceNode[] }
    | { kind: "read"; nodes: (TraceNode & { doc_id: string; doc_title: string; path: TraceNode[] })[] }
    | (TraceNode & { kind: "figure"; doc_id: string; doc_title: string; path: TraceNode[] })

export interface Citation {
    doc_id: string
    doc_title: string
    node_id: string
    pages: string
}

export interface RunStats {
    seconds: number
    cost_usd: number
    model_calls: number
    tool_calls: number
    run_id?: string
}

export interface UploadJob {
    job_id: string
    collection: string
    state: "running" | "done" | "failed"
    summary: string
    elapsed: number
    files: { filename: string; status: string; message: string; doc_id?: string | null }[]
    rejected: { filename: string; message: string }[]
}

export interface StreamHandlers {
    onTrace: (e: TraceEvent) => void
    onAnswer: (a: { answer: string; citations: Citation[]; blocked?: boolean }) => void
    onStats: (s: RunStats) => void
    onError: (message: string) => void
}

// ---------------------------------------------------------------- browse

export const listCollections = () => request<Collection[]>("/collections")
export const listDocuments = (c: string) => request<DocumentInfo[]>(`/collections/${c}/documents`)
export const getDocument = (c: string, docId: string) => request<DocumentTree>(`/collections/${c}/documents/${docId}`)
export const getNode = (c: string, docId: string, nodeId: string) =>
    request<NodeDetail>(`/collections/${c}/documents/${docId}/nodes/${nodeId}`)
export const deleteDocument = (c: string, docId: string) =>
    request<{ deleted: string }>(`/collections/${c}/documents/${docId}`, { method: "DELETE" })
export const listRuns = () => request<RecordedRun[]>("/runs")
export const figureUrl = (imageUrl: string) => `${API_BASE}${imageUrl}`

// ---------------------------------------------------------------- ingest

export async function uploadDocuments(collection: string, files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append("files", f))
    return request<{ job_id: string; files: number; rejected: { filename: string; message: string }[] }>(
        `/collections/${collection}/documents`, { method: "POST", body: form })
}

export const getJob = (jobId: string) => request<UploadJob>(`/jobs/${jobId}`)

// ---------------------------------------------------------------- ask (server-sent events)

async function consume(response: Response, h: StreamHandlers): Promise<void> {
    if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({}))
        h.onError((typeof body.detail === "string" && body.detail) || `HTTP ${response.status}`)
        return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    let event = ""
    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""
        for (const line of lines) {
            if (line.startsWith("event: ")) event = line.slice(7).trim()
            else if (line.startsWith("data: ")) {
                let data
                try {
                    data = JSON.parse(line.slice(6))
                } catch {
                    continue
                }
                if (event === "Trace") h.onTrace(data)
                else if (event === "Answer") h.onAnswer(data)
                else if (event === "Stats") h.onStats(data)
                else if (event === "Error") h.onError(data.error)
            }
        }
    }
}

export async function ask(message: string, collection: string, threadId: string, h: StreamHandlers) {
    const form = new FormData()
    form.append("message", message)
    form.append("collection", collection)
    form.append("thread_id", threadId)
    await consume(await fetch(`${BASE}/query`, { method: "POST", body: form }), h)
}

export async function replay(runId: string, h: StreamHandlers, speed = 1.5) {
    const form = new FormData()
    form.append("run_id", runId)
    form.append("speed", String(speed))
    await consume(await fetch(`${BASE}/replay`, { method: "POST", body: form }), h)
}
