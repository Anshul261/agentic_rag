/**
 * API Configuration for AgentOS Integration
 * Handles dynamic communication with teams from the backend
 */

// API Configuration
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7777";

// Export for use in components
export { API_BASE_URL };

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

/**
 * List all available teams from the backend
 */
export async function listTeams(): Promise<TeamInfo[]> {
    try {
        const response = await fetch(`${API_BASE_URL}/teams`);
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list teams:", error);
        return [];
    }
}

/**
 * Get the default team (first available team)
 */
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

/**
 * Send a message to a team (general chat mode)
 * @param teamId - The team ID to send the message to
 * @param message - User's message
 * @param files - Optional files to upload with the message
 * @param sessionId - Optional session ID for conversation history
 * @returns Team's response
 */
export async function sendMessageToTeam(
    teamId: string,
    message: string,
    files?: File[],
    sessionId?: string,
): Promise<AgentResponse> {
    try {
        const formData = new FormData();
        formData.append("message", message);
        formData.append("stream", "false"); // Non-streaming for simplicity

        if (sessionId) {
            formData.append("session_id", sessionId);
        }

        // Attach files if provided
        if (files && files.length > 0) {
            console.log(
                `[API] Uploading ${files.length} file(s):`,
                files.map((f) => f.name),
            );
            files.forEach((file) => {
                formData.append("files", file);
                console.log(
                    `[API] Added file: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`,
                );
            });
        } else {
            console.log("[API] No files to upload");
        }

        console.log(
            `[API] Sending request to: ${API_BASE_URL}/teams/${teamId}/runs`,
        );
        console.log(`[API] Session ID: ${sessionId || "none"}`);

        const response = await fetch(`${API_BASE_URL}/teams/${teamId}/runs`, {
            method: "POST",
            body: formData,
        });

        console.log(`[API] Response status: ${response.status}`);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(
                errorData.detail || `API Error: ${response.status}`,
            );
        }

        const data = await response.json();

        // Extract content from the response
        // AGNO returns: { content: "...", run_id: "...", ... }
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

/**
 * Check if the API is healthy
 */
export async function checkAPIHealth(): Promise<boolean> {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        return response.ok;
    } catch (error) {
        console.error("API health check failed:", error);
        return false;
    }
}

/**
 * Get API information
 */
export async function getAPIInfo(): Promise<any> {
    try {
        const response = await fetch(`${API_BASE_URL}/info`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get API info:", error);
        return null;
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

/**
 * List all sessions for the team
 */
export async function listSessions(
    page: number = 1,
    limit: number = 20,
): Promise<SessionsResponse | null> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/sessions?type=team&page=${page}&limit=${limit}&sort_by=updated_at&sort_order=desc`,
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to list sessions:", error);
        return null;
    }
}

/**
 * Get session details including chat history
 */
export async function getSession(sessionId: string): Promise<any> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/sessions/${sessionId}?type=team`,
        );
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get session:", error);
        return null;
    }
}

/**
 * Get all runs (messages) for a session
 */
export async function getSessionRuns(sessionId: string): Promise<SessionRun[]> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/sessions/${sessionId}/runs?type=team`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to get session runs:", error);
        return [];
    }
}

/**
 * Create a new session
 * @param teamId - The team ID to associate with the session
 * @param sessionName - Optional custom session name
 */
export async function createSession(
    teamId: string,
    sessionName?: string,
): Promise<string | null> {
    try {
        const sessionId = `session_${Date.now()}`;
        const response = await fetch(`${API_BASE_URL}/sessions?type=team`, {
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
            // Session might auto-create on first run, return the ID anyway
            return sessionId;
        }

        const data = await response.json();
        return data.session_id || sessionId;
    } catch (error) {
        console.error("Failed to create session:", error);
        // Return a new session ID anyway - it will be created on first message
        return `session_${Date.now()}`;
    }
}

/**
 * Get team details including members
 * @param teamId - The team ID to get details for
 */
export async function getTeamDetails(teamId: string): Promise<TeamInfo | null> {
    try {
        const response = await fetch(`${API_BASE_URL}/teams/${teamId}`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get team details:", error);
        return null;
    }
}

// ============================================================================
// User Identity
// ============================================================================

const USER_ID_KEY = "agno_user_id";

/**
 * Get or create a persistent user ID stored in localStorage
 */
export function getUserId(): string {
    if (typeof window === "undefined") return "anonymous";
    let userId = localStorage.getItem(USER_ID_KEY);
    if (!userId) {
        userId = crypto.randomUUID();
        localStorage.setItem(USER_ID_KEY, userId);
    }
    return userId;
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
 * Create a new project
 */
export async function createProject(
    userId: string,
    name: string,
    description: string = "",
): Promise<ProjectInfo | null> {
    try {
        const response = await fetch(`${API_BASE_URL}/projects`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId, name, description }),
        });
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to create project:", error);
        return null;
    }
}

/**
 * List all projects for a user
 */
export async function listProjects(userId: string): Promise<ProjectInfo[]> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/projects?user_id=${encodeURIComponent(userId)}`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list projects:", error);
        return [];
    }
}

/**
 * Get project details including file list
 */
export async function getProject(
    projectId: string,
): Promise<ProjectDetail | null> {
    try {
        const response = await fetch(`${API_BASE_URL}/projects/${projectId}`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.error("Failed to get project:", error);
        return null;
    }
}

/**
 * Delete a project
 */
export async function deleteProject(projectId: string): Promise<boolean> {
    try {
        const response = await fetch(`${API_BASE_URL}/projects/${projectId}`, {
            method: "DELETE",
        });
        return response.ok;
    } catch (error) {
        console.error("Failed to delete project:", error);
        return false;
    }
}

/**
 * Upload files to a project (ingests into PgVector knowledge base)
 */
export async function uploadProjectFiles(
    projectId: string,
    files: File[],
): Promise<{ uploaded: ProjectFileInfo[]; ingested: number } | null> {
    try {
        const formData = new FormData();
        files.forEach((file) => formData.append("files", file));

        const response = await fetch(
            `${API_BASE_URL}/projects/${projectId}/files`,
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

/**
 * Delete a file from a project
 */
export async function deleteProjectFile(
    projectId: string,
    fileId: string,
): Promise<boolean> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/projects/${projectId}/files/${fileId}`,
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

/**
 * List all sessions for a project
 */
export async function listProjectSessions(
    projectId: string,
): Promise<ProjectSession[]> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/projects/${projectId}/sessions`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to list project sessions:", error);
        return [];
    }
}

/**
 * Get all runs (messages) for a project session
 */
export async function getProjectSessionRuns(
    projectId: string,
    sessionId: string,
): Promise<SessionRun[]> {
    try {
        const response = await fetch(
            `${API_BASE_URL}/projects/${projectId}/sessions/${sessionId}/runs`,
        );
        if (!response.ok) return [];
        const data = await response.json();
        return Array.isArray(data) ? data : [];
    } catch (error) {
        console.error("Failed to get project session runs:", error);
        return [];
    }
}

/**
 * Query a project's knowledge base (returns fetch Response for SSE streaming)
 */
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

    return fetch(`${API_BASE_URL}/projects/${projectId}/query`, {
        method: "POST",
        body: formData,
    });
}
