/**
 * API Client — routes all calls through the BFF proxy at /api/agentOS
 * The BFF attaches JWT Bearer tokens from the encrypted session cookie.
 * The browser never sees or handles JWTs directly.
 */

const BFF_BASE = "/api/agentOS";

// ============================================================================
// Team Discovery
// ============================================================================

export interface TeamInfo {
    id: string;
    name: string;
    description?: string | null;
    model?: {
        name: string | null;
        model: string | null;
        provider: string | null;
    } | null;
    members?: TeamMemberInfo[];
}

export interface TeamMemberInfo {
    id: string;
    name: string;
    model?: {
        name: string | null;
        model: string | null;
        provider: string | null;
    } | null;
}

export async function listTeams(): Promise<TeamInfo[]> {
    try {
        const response = await fetch(`${BFF_BASE}/teams`);
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list teams:", error);
        return [];
    }
}

export async function getDefaultTeam(): Promise<TeamInfo | null> {
    const teams = await listTeams();
    return teams.length > 0 ? teams[0] : null;
}

export interface AgentResponse {
    content: string;
    run_id?: string;
    session_id?: string;
    error?: string;
}

export async function sendMessageToTeam(
    teamId: string,
    message: string,
    files?: File[],
    sessionId?: string,
): Promise<AgentResponse> {
    try {
        const formData = new FormData();
        formData.append("message", message);
        formData.append("stream", "false");

        if (sessionId) {
            formData.append("session_id", sessionId);
        }

        if (files && files.length > 0) {
            files.forEach((file) => {
                formData.append("files", file);
            });
        }

        const response = await fetch(`${BFF_BASE}/teams/${teamId}/runs`, {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(
                errorData.detail || `API Error: ${response.status}`,
            );
        }

        const data = await response.json();
        return {
            content: data.content || data.message || "No response from agent",
            run_id: data.run_id,
            session_id: data.session_id,
        };
    } catch (error) {
        console.error("Error calling team API:", error);
        return {
            content: "",
            error:
                error instanceof Error
                    ? error.message
                    : "Failed to get response from team",
        };
    }
}

export async function checkAPIHealth(): Promise<boolean> {
    try {
        const response = await fetch(`${BFF_BASE}/teams`);
        return response.ok;
    } catch (error) {
        console.error("API health check failed:", error);
        return false;
    }
}

// ============================================================================
// Session Management
// ============================================================================

export interface Session {
    session_id: string;
    session_name: string;
    session_state?: any;
    created_at: string;
    updated_at: string;
}

export interface SessionsResponse {
    data: Session[];
    meta: {
        page: number;
        limit: number;
        total_pages: number;
        total_count: number;
    };
}

export interface SessionRun {
    run_id: string;
    run_input: string;
    content: string;
    created_at: string;
    metrics?: any;
}

export async function listSessions(
    page: number = 1,
    limit: number = 20,
): Promise<SessionsResponse | null> {
    try {
        const response = await fetch(
            `${BFF_BASE}/sessions?type=team&page=${page}&limit=${limit}&sort_by=updated_at&sort_order=desc`,
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to list sessions:", error);
        return null;
    }
}

export async function getSession(sessionId: string): Promise<any> {
    try {
        const response = await fetch(
            `${BFF_BASE}/sessions/${sessionId}?type=team`,
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get session:", error);
        return null;
    }
}

export async function getSessionRuns(sessionId: string): Promise<SessionRun[]> {
    try {
        const response = await fetch(
            `${BFF_BASE}/sessions/${sessionId}/runs?type=team`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to get session runs:", error);
        return [];
    }
}

export async function createSession(
    teamId: string,
    sessionName?: string,
): Promise<string | null> {
    try {
        const sessionId = `session_${Date.now()}`;
        const response = await fetch(`${BFF_BASE}/sessions?type=team`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                session_id: sessionId,
                session_name:
                    sessionName || `Chat ${new Date().toLocaleString()}`,
                team_id: teamId,
            }),
        });

        if (!response.ok) {
            return sessionId;
        }

        const data = await response.json();
        return data.session_id || sessionId;
    } catch (error) {
        console.error("Failed to create session:", error);
        return `session_${Date.now()}`;
    }
}

export async function getTeamDetails(teamId: string): Promise<TeamInfo | null> {
    try {
        const response = await fetch(`${BFF_BASE}/teams/${teamId}`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get team details:", error);
        return null;
    }
}

// ============================================================================
// Project Management
// ============================================================================

export interface ProjectInfo {
    id: string;
    user_id: string;
    name: string;
    description: string;
    created_at?: string;
    file_count?: number;
}

export interface ProjectFileInfo {
    id: string;
    filename: string;
    file_type: string;
    size: number;
    created_at?: string;
}

export interface ProjectDetail extends ProjectInfo {
    files: ProjectFileInfo[];
}

/**
 * Create a new project. userId is injected by the BFF from the session.
 */
export async function createProject(
    name: string,
    description: string = "",
): Promise<ProjectInfo | null> {
    try {
        const response = await fetch(`${BFF_BASE}/projects`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, description }),
        });
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to create project:", error);
        return null;
    }
}

/**
 * List all projects for the authenticated user. userId is injected by the BFF.
 */
export async function listProjects(): Promise<ProjectInfo[]> {
    try {
        const response = await fetch(`${BFF_BASE}/projects`);
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list projects:", error);
        return [];
    }
}

export async function getProject(
    projectId: string,
): Promise<ProjectDetail | null> {
    try {
        const response = await fetch(`${BFF_BASE}/projects/${projectId}`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get project:", error);
        return null;
    }
}

export async function deleteProject(projectId: string): Promise<boolean> {
    try {
        const response = await fetch(`${BFF_BASE}/projects/${projectId}`, {
            method: "DELETE",
        });
        return response.ok;
    } catch (error) {
        console.error("Failed to delete project:", error);
        return false;
    }
}

export async function uploadProjectFiles(
    projectId: string,
    files: File[],
): Promise<{ uploaded: ProjectFileInfo[]; ingested: number } | null> {
    try {
        const formData = new FormData();
        files.forEach((file) => formData.append("files", file));

        const response = await fetch(
            `${BFF_BASE}/projects/${projectId}/files`,
            {
                method: "POST",
                body: formData,
            },
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to upload project files:", error);
        return null;
    }
}

export async function deleteProjectFile(
    projectId: string,
    fileId: string,
): Promise<boolean> {
    try {
        const response = await fetch(
            `${BFF_BASE}/projects/${projectId}/files/${fileId}`,
            { method: "DELETE" },
        );
        return response.ok;
    } catch (error) {
        console.error("Failed to delete project file:", error);
        return false;
    }
}

// ============================================================================
// Project Session Management
// ============================================================================

export interface ProjectSession {
    session_id: string;
    project_id: string;
    session_name: string;
    created_at: string;
    updated_at: string;
}

export async function listProjectSessions(
    projectId: string,
): Promise<ProjectSession[]> {
    try {
        const response = await fetch(
            `${BFF_BASE}/projects/${projectId}/sessions`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list project sessions:", error);
        return [];
    }
}

export async function getProjectSessionRuns(
    projectId: string,
    sessionId: string,
): Promise<SessionRun[]> {
    try {
        const response = await fetch(
            `${BFF_BASE}/projects/${projectId}/sessions/${sessionId}/runs`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to get project session runs:", error);
        return [];
    }
}

export async function queryProject(
    projectId: string,
    message: string,
    sessionId?: string,
): Promise<Response> {
    const formData = new FormData();
    formData.append("message", message);
    formData.append("stream", "true");
    if (sessionId) {
        formData.append("session_id", sessionId);
    }

    return fetch(`${BFF_BASE}/projects/${projectId}/query`, {
        method: "POST",
        body: formData,
    });
}

// ============================================================================
// Sandbox
// ============================================================================

export async function querySandbox(
    message: string,
    sessionId?: string,
    files?: File[],
): Promise<Response> {
    const formData = new FormData();
    formData.append("message", message);
    formData.append("stream", "true");
    if (sessionId) {
        formData.append("session_id", sessionId);
    }
    if (files && files.length > 0) {
        for (const file of files) {
            formData.append("files", file);
        }
    }

    return fetch(`${BFF_BASE}/sandbox/query`, {
        method: "POST",
        body: formData,
    });
}

export async function closeSandbox(): Promise<boolean> {
    try {
        const response = await fetch(`${BFF_BASE}/sandbox/close`, {
            method: "POST",
        });
        return response.ok;
    } catch (error) {
        console.error("Failed to close sandbox:", error);
        return false;
    }
}

// ============================================================================
// PageIndex (reasoning-based tree RAG)
// ============================================================================

export interface PageIndexCollection {
    name: string;
    n_docs: number;
}

export interface PageIndexRun {
    run_id: string;
    question: string;
    collection: string;
}

export interface TraceNode {
    node_id: string;
    title: string;
    pages: string;
    kind?: string;
}

export type TraceEvent =
    | { kind: "catalog"; n_docs: number }
    | {
          kind: "search";
          query: string;
          hits: (TraceNode & { doc_id: string; doc_title: string })[];
      }
    | {
          kind: "open_doc";
          doc_id: string;
          doc_title: string;
          n_pages: number;
          branches: TraceNode[];
      }
    | {
          kind: "read";
          nodes: (TraceNode & {
              doc_id: string;
              doc_title: string;
              path: TraceNode[];
          })[];
      }
    | (TraceNode & {
          kind: "figure";
          doc_id: string;
          doc_title: string;
          path: TraceNode[];
      });

export interface PageIndexCitation {
    doc_id: string;
    doc_title: string;
    node_id: string;
    pages: string;
}

export interface PageIndexStats {
    seconds: number;
    cost_usd: number;
    model_calls: number;
    tool_calls: number;
    run_id?: string;
}

export interface PageIndexHandlers {
    onTrace: (e: TraceEvent) => void;
    onAnswer: (a: { answer: string; citations: PageIndexCitation[] }) => void;
    onStats: (s: PageIndexStats) => void;
    onError: (message: string) => void;
}

export async function listPageIndexCollections(): Promise<PageIndexCollection[]> {
    try {
        const response = await fetch(`${BFF_BASE}/pageindex/collections`);
        return response.ok ? await response.json() : [];
    } catch {
        return [];
    }
}

export async function listPageIndexRuns(): Promise<PageIndexRun[]> {
    try {
        const response = await fetch(`${BFF_BASE}/pageindex/runs`);
        return response.ok ? await response.json() : [];
    } catch {
        return [];
    }
}

async function consumePageIndexStream(response: Response, h: PageIndexHandlers): Promise<void> {
    if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        h.onError(data.error || `HTTP ${response.status}`);
        return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let event = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
            if (line.startsWith("event: ")) {
                event = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
                let data;
                try {
                    data = JSON.parse(line.slice(6));
                } catch {
                    continue;
                }
                if (event === "Trace") h.onTrace(data);
                else if (event === "Answer") h.onAnswer(data);
                else if (event === "Stats") h.onStats(data);
                else if (event === "Error") h.onError(data.error);
            }
        }
    }
}

export async function queryPageIndex(
    message: string,
    collection: string,
    handlers: PageIndexHandlers,
): Promise<void> {
    const form = new FormData();
    form.append("message", message);
    form.append("collection", collection);
    const response = await fetch(`${BFF_BASE}/pageindex/query`, { method: "POST", body: form });
    await consumePageIndexStream(response, handlers);
}

export async function replayPageIndexRun(
    runId: string,
    handlers: PageIndexHandlers,
    speed = 1.5,
): Promise<void> {
    const form = new FormData();
    form.append("run_id", runId);
    form.append("speed", String(speed));
    const response = await fetch(`${BFF_BASE}/pageindex/replay`, { method: "POST", body: form });
    await consumePageIndexStream(response, handlers);
}
