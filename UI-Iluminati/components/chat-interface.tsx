"use client";

import type React from "react";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
    sendMessageToTeam,
    listSessions,
    getSessionRuns,
    createSession,
    listTeams,
    getDefaultTeam,
    listProjects,
    createProject as apiCreateProject,
    getProject as apiGetProject,
    deleteProject as apiDeleteProject,
    uploadProjectFiles,
    deleteProjectFile,
    queryProject,
    querySandbox,
    type Session,
    type SessionRun,
    type TeamInfo,
    type ProjectInfo,
    type ProjectFileInfo,
    type ProjectSession,
    listProjectSessions,
    getProjectSessionRuns,
} from "@/lib/api";
import { useAuthStore } from "@/lib/store/auth-store";
import {
    Send,
    Sparkles,
    ArrowRight,
    MessageSquare,
    Plus,
    Clock,
    ChevronLeft,
    ChevronRight,
    Sun,
    Moon,
    Paperclip,
    FolderOpen,
    X,
    Upload,
    FileText,
    Trash2,
    ChevronDown,
    LogOut,
    Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AgentTrace, type AgentTraceStep } from "@/components/agent-trace";

interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    agentSteps?: AgentTraceStep[];
}

interface ChatHistory {
    id: string;
    title: string;
    timestamp: string;
    preview: string;
    projectId?: string;
}

interface Project {
    id: string;
    name: string;
    description: string;
    file_count: number;
    files: UploadedFile[];
}

interface UploadedFile {
    id: string;
    name: string;
    size: number;
    type: string;
}

export function ChatInterface() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [isDark, setIsDark] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [sessionId, setSessionId] = useState<string>(
        () => `session_${Date.now()}`,
    );
    const [uploadedFiles, setUploadedFiles] = useState<File[]>([]); // Files for general chat

    const [activeTab, setActiveTab] = useState<"chats" | "projects" | "sandbox">("chats");
    const [showNewProjectModal, setShowNewProjectModal] = useState(false);
    const [newProjectName, setNewProjectName] = useState("");
    const [newProjectDescription, setNewProjectDescription] = useState("");
    const [selectedProject, setSelectedProject] = useState<Project | null>(
        null,
    );
    const [projects, setProjects] = useState<Project[]>([]);
    const logout = useAuthStore((s) => s.logout);
    const [uploadingFiles, setUploadingFiles] = useState(false);
    const [showProjectFiles, setShowProjectFiles] = useState(true);
    const [projectSessions, setProjectSessions] = useState<ProjectSession[]>(
        [],
    );
    const [loadingProjectSessions, setLoadingProjectSessions] = useState(false);

    const [sessions, setSessions] = useState<Session[]>([]);
    const [loadingSessions, setLoadingSessions] = useState(false);

    // Team state
    const [availableTeams, setAvailableTeams] = useState<TeamInfo[]>([]);
    const [currentTeam, setCurrentTeam] = useState<TeamInfo | null>(null);
    const [loadingTeams, setLoadingTeams] = useState(true);

    // Agent trace state
    const [currentAgentSteps, setCurrentAgentSteps] = useState<
        AgentTraceStep[]
    >([]);
    const [currentProgress, setCurrentProgress] = useState<string>("");

    useEffect(() => {
        if (isDark) {
            document.documentElement.classList.add("dark");
        } else {
            document.documentElement.classList.remove("dark");
        }
    }, [isDark]);

    // Load projects from API
    const loadProjects = async () => {
        try {
            const data = await listProjects();
            setProjects(
                data.map((p) => ({
                    id: p.id,
                    name: p.name,
                    description: p.description,
                    file_count: p.file_count || 0,
                    files: [],
                })),
            );
        } catch (error) {
            console.error("Failed to load projects:", error);
        }
    };

    // Load project details (with file list)
    const loadProjectDetails = async (projectId: string) => {
        try {
            const detail = await apiGetProject(projectId);
            if (detail) {
                const proj: Project = {
                    id: detail.id,
                    name: detail.name,
                    description: detail.description,
                    file_count: detail.files?.length || 0,
                    files: (detail.files || []).map((f) => ({
                        id: f.id,
                        name: f.filename,
                        size: f.size,
                        type: f.file_type,
                    })),
                };
                setSelectedProject(proj);
                // Update in list too
                setProjects((prev) =>
                    prev.map((p) => (p.id === proj.id ? proj : p)),
                );
            }
        } catch (error) {
            console.error("Failed to load project details:", error);
        }
    };

    const loadProjectSessions = async (projectId: string) => {
        setLoadingProjectSessions(true);
        try {
            const data = await listProjectSessions(projectId);
            setProjectSessions(data);
        } catch (error) {
            console.error("Failed to load project sessions:", error);
        } finally {
            setLoadingProjectSessions(false);
        }
    };

    const loadProjectSessionMessages = async (ps: ProjectSession) => {
        if (!selectedProject) return;
        try {
            const runs = await getProjectSessionRuns(
                ps.project_id,
                ps.session_id,
            );
            const loadedMessages: Message[] = [];
            runs.forEach((run) => {
                if (run.run_input) {
                    loadedMessages.push({
                        id: `${run.run_id}-input`,
                        role: "user",
                        content: run.run_input,
                    });
                }
                if (run.content) {
                    loadedMessages.push({
                        id: run.run_id,
                        role: "assistant",
                        content: run.content,
                    });
                }
            });
            setMessages(loadedMessages);
            setSessionId(ps.session_id);
        } catch (error) {
            console.error("Failed to load project session messages:", error);
        }
    };

    useEffect(() => {
        loadProjects();
    }, []);

    // Load teams on component mount
    useEffect(() => {
        const loadTeams = async () => {
            setLoadingTeams(true);
            try {
                const teams = await listTeams();
                setAvailableTeams(teams);
                if (teams.length > 0) {
                    setCurrentTeam(teams[0]);
                    console.log(
                        "[UI] Loaded teams:",
                        teams.map((t) => t.name),
                    );
                    console.log("[UI] Default team:", teams[0].name);
                }
            } catch (error) {
                console.error("Failed to load teams:", error);
            } finally {
                setLoadingTeams(false);
            }
        };
        loadTeams();
    }, []);

    // Load sessions on component mount (after teams are loaded)
    useEffect(() => {
        if (currentTeam) {
            loadSessions();
        }
    }, [currentTeam]);

    const loadSessions = async () => {
        setLoadingSessions(true);
        try {
            const response = await listSessions(1, 50);
            if (response && response.data) {
                setSessions(response.data);
            }
        } catch (error) {
            console.error("Failed to load sessions:", error);
        } finally {
            setLoadingSessions(false);
        }
    };

    const loadSessionMessages = async (session: Session) => {
        try {
            console.log("[UI] Loading session:", session.session_id);
            const runs = await getSessionRuns(session.session_id);

            // Convert runs to messages
            const loadedMessages: Message[] = [];
            runs.forEach((run) => {
                // Add user message
                if (run.run_input) {
                    loadedMessages.push({
                        id: `${run.run_id}-input`,
                        role: "user",
                        content: run.run_input,
                    });
                }
                // Add assistant message
                if (run.content) {
                    loadedMessages.push({
                        id: run.run_id,
                        role: "assistant",
                        content: run.content,
                    });
                }
            });

            setMessages(loadedMessages);
            setSessionId(session.session_id);
            console.log(
                `[UI] Loaded ${loadedMessages.length} messages from session`,
            );
        } catch (error) {
            console.error("Failed to load session messages:", error);
        }
    };

    const handleNewChat = async () => {
        setMessages([]);
        setUploadedFiles([]);

        if (selectedProject) {
            // In project mode: create a new project session
            const newSessionId = `proj_${selectedProject.id.slice(0, 8)}_${Date.now()}`;
            setSessionId(newSessionId);
            console.log(
                "[UI] Created new project session:",
                newSessionId,
                "for project:",
                selectedProject.name,
            );
            return;
        }

        if (!currentTeam) {
            console.error("[UI] No team selected");
            return;
        }

        setSelectedProject(null);

        // Create a new session with the current team
        const newSessionId = await createSession(currentTeam.id);
        if (newSessionId) {
            setSessionId(newSessionId);
            console.log(
                "[UI] Created new session:",
                newSessionId,
                "for team:",
                currentTeam.name,
            );
            // Reload sessions list
            loadSessions();
        }
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isLoading) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: "user",
            content: input.trim(),
        };

        setMessages((prev) => [...prev, userMessage]);
        const currentInput = input.trim();
        setInput("");
        setIsLoading(true);
        setCurrentAgentSteps([]);
        setCurrentProgress("");

        // Route by active tab — sandbox check must come first
        if (activeTab === "sandbox") {
            // Sandbox mode - execute Python code via SSE
            const currentFiles = [...uploadedFiles];
            setUploadedFiles([]);
            try {
                const response = await querySandbox(currentInput, sessionId, currentFiles);

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                if (response.body) {
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let accumulatedContent = "";
                    let buffer = "";

                    const aiMessageId = (Date.now() + 1).toString();
                    setMessages((prev) => [
                        ...prev,
                        { id: aiMessageId, role: "assistant", content: "" },
                    ]);

                    try {
                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;

                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split("\n");
                            buffer = lines.pop() || "";

                            let currentEvent = "";
                            for (const line of lines) {
                                if (line.startsWith("event: ")) {
                                    currentEvent = line.slice(7).trim();
                                } else if (line.startsWith("data: ")) {
                                    try {
                                        const data = JSON.parse(line.slice(6));
                                        if (
                                            currentEvent === "RunContent" &&
                                            data.content
                                        ) {
                                            accumulatedContent += data.content;
                                            setMessages((prev) =>
                                                prev.map((msg) =>
                                                    msg.id === aiMessageId
                                                        ? {
                                                              ...msg,
                                                              content:
                                                                  accumulatedContent,
                                                          }
                                                        : msg,
                                                ),
                                            );
                                        } else if (
                                            currentEvent === "RunError" &&
                                            data.error
                                        ) {
                                            accumulatedContent += `\n\nError: ${data.error}`;
                                            setMessages((prev) =>
                                                prev.map((msg) =>
                                                    msg.id === aiMessageId
                                                        ? {
                                                              ...msg,
                                                              content:
                                                                  accumulatedContent,
                                                          }
                                                        : msg,
                                                ),
                                            );
                                        }
                                    } catch {
                                        // skip parse errors
                                    }
                                }
                            }
                        }
                    } finally {
                        reader.releaseLock();
                    }
                }
            } catch (error) {
                console.error("Error querying sandbox:", error);
                const errorMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: `Error: ${error instanceof Error ? error.message : "Unknown error"}. Please make sure the sandbox is running.`,
                };
                setMessages((prev) => [...prev, errorMessage]);
            } finally {
                setIsLoading(false);
            }
        } else if (selectedProject) {
            // Project mode - query project knowledge base via SSE
            try {
                const response = await queryProject(
                    selectedProject.id,
                    currentInput,
                    sessionId,
                );

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                if (response.body) {
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let accumulatedContent = "";
                    let buffer = "";

                    const aiMessageId = (Date.now() + 1).toString();
                    setMessages((prev) => [
                        ...prev,
                        { id: aiMessageId, role: "assistant", content: "" },
                    ]);

                    try {
                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;

                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split("\n");
                            buffer = lines.pop() || "";

                            let currentEvent = "";
                            for (const line of lines) {
                                if (line.startsWith("event: ")) {
                                    currentEvent = line.slice(7).trim();
                                } else if (line.startsWith("data: ")) {
                                    try {
                                        const data = JSON.parse(line.slice(6));
                                        if (
                                            currentEvent === "RunContent" &&
                                            data.content
                                        ) {
                                            accumulatedContent += data.content;
                                            setMessages((prev) =>
                                                prev.map((msg) =>
                                                    msg.id === aiMessageId
                                                        ? {
                                                              ...msg,
                                                              content:
                                                                  accumulatedContent,
                                                          }
                                                        : msg,
                                                ),
                                            );
                                        } else if (
                                            currentEvent === "RunError" &&
                                            data.error
                                        ) {
                                            accumulatedContent += `\n\nError: ${data.error}`;
                                            setMessages((prev) =>
                                                prev.map((msg) =>
                                                    msg.id === aiMessageId
                                                        ? {
                                                              ...msg,
                                                              content:
                                                                  accumulatedContent,
                                                          }
                                                        : msg,
                                                ),
                                            );
                                        }
                                    } catch {
                                        // skip parse errors
                                    }
                                }
                            }
                        }
                    } finally {
                        reader.releaseLock();
                    }
                }
            } catch (error) {
                console.error("Error querying project:", error);
                const errorMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: `Error querying project: ${error instanceof Error ? error.message : "Unknown error"}`,
                };
                setMessages((prev) => [...prev, errorMessage]);
            } finally {
                setIsLoading(false);
                // Reload project sessions so new session appears in sidebar
                loadProjectSessions(selectedProject.id);
            }
        } else if (!selectedProject && currentTeam) {
            // General chat mode - team API
            try {
                console.log("[UI] Submitting to team:", {
                    team: currentTeam.name,
                    teamId: currentTeam.id,
                    message: currentInput,
                    filesCount: uploadedFiles.length,
                    sessionId,
                });

                const formData = new FormData();
                formData.append("message", currentInput);
                formData.append("stream", "true");
                formData.append("monitor", "true");

                if (sessionId) {
                    formData.append("session_id", sessionId);
                }

                if (uploadedFiles.length > 0) {
                    uploadedFiles.forEach((file) => {
                        formData.append("files", file);
                    });
                }

                const response = await fetch(
                    `/api/agentOS/teams/${currentTeam.id}/runs`,
                    {
                        method: "POST",
                        body: formData,
                    },
                );

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                if (response.body) {
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let accumulatedContent = "";
                    let buffer = "";

                    const aiMessageId = (Date.now() + 1).toString();
                    const initialAiMessage: Message = {
                        id: aiMessageId,
                        role: "assistant",
                        content: "",
                    };
                    setMessages((prev) => [...prev, initialAiMessage]);

                    try {
                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;

                            const chunk = decoder.decode(value, {
                                stream: true,
                            });
                            buffer += chunk;

                            const lines = buffer.split("\n");
                            buffer = lines.pop() || "";

                            let currentEvent = "";
                            for (const line of lines) {
                                if (line.startsWith("event: ")) {
                                    currentEvent = line.slice(7).trim();
                                } else if (line.startsWith("data: ")) {
                                    try {
                                        const data = JSON.parse(line.slice(6));

                                        if (
                                            currentEvent === "RunContent" &&
                                            data.content
                                        ) {
                                            accumulatedContent += data.content;
                                            setMessages((prev) =>
                                                prev.map((msg) =>
                                                    msg.id === aiMessageId
                                                        ? {
                                                              ...msg,
                                                              content:
                                                                  accumulatedContent,
                                                          }
                                                        : msg,
                                                ),
                                            );
                                        } else if (
                                            currentEvent === "ToolCallStarted"
                                        ) {
                                            const agentName =
                                                data.agent?.name ||
                                                data.agent?.id ||
                                                currentTeam?.name ||
                                                "Team";
                                            const step: AgentTraceStep = {
                                                type: "tool_call",
                                                title: `Using ${data.tool?.tool_name || "tool"}`,
                                                description:
                                                    data.tool?.tool_name ===
                                                    "delegate_task_to_member"
                                                        ? "Delegating task to team member"
                                                        : "Processing request",
                                                timestamp:
                                                    new Date().toLocaleTimeString(),
                                                tool: data.tool?.tool_name,
                                                agent: agentName,
                                                status: "running",
                                            };
                                            setCurrentAgentSteps((prev) => [
                                                ...prev,
                                                step,
                                            ]);
                                            setCurrentProgress(
                                                `Using ${data.tool?.tool_name || "tool"}...`,
                                            );
                                        } else if (
                                            currentEvent === "ToolCallCompleted"
                                        ) {
                                            const agentName =
                                                data.agent?.name ||
                                                data.agent?.id ||
                                                currentTeam?.name ||
                                                "Team";
                                            const step: AgentTraceStep = {
                                                type: "tool_call",
                                                title: `Completed ${data.tool?.tool_name || "tool"}`,
                                                description: data.tool?.metrics
                                                    ?.duration
                                                    ? `Finished in ${data.tool.metrics.duration.toFixed(2)}s`
                                                    : "Completed successfully",
                                                timestamp:
                                                    new Date().toLocaleTimeString(),
                                                tool: data.tool?.tool_name,
                                                agent: agentName,
                                                status: "completed",
                                            };
                                            setCurrentAgentSteps((prev) => [
                                                ...prev,
                                                step,
                                            ]);
                                            setCurrentProgress("");
                                        } else if (
                                            currentEvent === "RunStarted"
                                        ) {
                                            const agentName =
                                                data.agent?.name ||
                                                data.agent?.id ||
                                                currentTeam?.name ||
                                                "Team";
                                            const step: AgentTraceStep = {
                                                type: "agent_start",
                                                title: "Team started processing",
                                                description: `${currentTeam?.name || "Team"} is analyzing your request`,
                                                timestamp:
                                                    new Date().toLocaleTimeString(),
                                                agent: agentName,
                                                status: "running",
                                            };
                                            setCurrentAgentSteps((prev) => [
                                                ...prev,
                                                step,
                                            ]);
                                            setCurrentProgress("Processing...");
                                        }
                                    } catch (parseError) {
                                        console.debug(
                                            "Parse error:",
                                            parseError,
                                        );
                                    }
                                }
                            }
                        }

                        setMessages((prev) =>
                            prev.map((msg) =>
                                msg.id === aiMessageId
                                    ? {
                                          ...msg,
                                          agentSteps: [...currentAgentSteps],
                                      }
                                    : msg,
                            ),
                        );
                    } finally {
                        reader.releaseLock();
                        setCurrentAgentSteps([]);
                        setCurrentProgress("");
                    }
                } else {
                    const data = await response.json();
                    const assistantMessage: Message = {
                        id: (Date.now() + 1).toString(),
                        role: "assistant",
                        content:
                            data.content ||
                            data.message ||
                            "No response received",
                    };
                    setMessages((prev) => [...prev, assistantMessage]);
                }

                setUploadedFiles([]);
            } catch (error) {
                console.error("Error sending message:", error);
                const errorMessage: Message = {
                    id: (Date.now() + 1).toString(),
                    role: "assistant",
                    content: `Error: ${error instanceof Error ? error.message : "Unknown error"}. Please make sure the API is running.`,
                };
                setMessages((prev) => [...prev, errorMessage]);
            } finally {
                setIsLoading(false);
                setCurrentAgentSteps([]);
                setCurrentProgress("");
            }
        } else if (!currentTeam) {
            // No team available
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: "assistant",
                content:
                    "No team available. Please check if the API is running and has teams configured.",
            };
            setMessages((prev) => [...prev, errorMessage]);
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
        }
    };

    const handleFileUpload = () => {
        fileInputRef.current?.click();
    };

    const handleCreateProject = async () => {
        if (!newProjectName.trim()) return;

        const result = await apiCreateProject(
            newProjectName,
            newProjectDescription,
        );
        if (result) {
            const newProject: Project = {
                id: result.id,
                name: result.name,
                description: result.description,
                file_count: 0,
                files: [],
            };
            setProjects((prev) => [newProject, ...prev]);
            setSelectedProject(newProject);
        }
        setNewProjectName("");
        setNewProjectDescription("");
        setShowNewProjectModal(false);
    };

    const handleProjectFileUpload = async (
        e: React.ChangeEvent<HTMLInputElement>,
    ) => {
        if (!selectedProject || !e.target.files) return;

        const files = Array.from(e.target.files);
        setUploadingFiles(true);

        try {
            const result = await uploadProjectFiles(selectedProject.id, files);
            if (result && result.uploaded) {
                const newFiles: UploadedFile[] = result.uploaded.map((f) => ({
                    id: f.id,
                    name: f.filename,
                    size: f.size,
                    type: f.file_type,
                }));

                setSelectedProject((prev) =>
                    prev
                        ? {
                              ...prev,
                              files: [...prev.files, ...newFiles],
                              file_count: prev.file_count + newFiles.length,
                          }
                        : null,
                );
                setProjects((prev) =>
                    prev.map((p) =>
                        p.id === selectedProject.id
                            ? {
                                  ...p,
                                  files: [...p.files, ...newFiles],
                                  file_count: p.file_count + newFiles.length,
                              }
                            : p,
                    ),
                );
                console.log(
                    `[UI] Uploaded ${result.uploaded.length} files, ingested ${result.ingested} into knowledge base`,
                );
            }
        } catch (error) {
            console.error("Failed to upload project files:", error);
        } finally {
            setUploadingFiles(false);
        }
    };

    const handleRemoveFile = async (fileId: string) => {
        if (!selectedProject) return;

        await deleteProjectFile(selectedProject.id, fileId);

        setProjects((prev) =>
            prev.map((p) =>
                p.id === selectedProject.id
                    ? {
                          ...p,
                          files: p.files.filter((f) => f.id !== fileId),
                          file_count: Math.max(0, p.file_count - 1),
                      }
                    : p,
            ),
        );

        setSelectedProject((prev) =>
            prev
                ? {
                      ...prev,
                      files: prev.files.filter((f) => f.id !== fileId),
                      file_count: Math.max(0, prev.file_count - 1),
                  }
                : null,
        );
    };

    const handleDeleteProject = async (projectId: string) => {
        await apiDeleteProject(projectId);
        setProjects((prev) => prev.filter((p) => p.id !== projectId));
        if (selectedProject?.id === projectId) {
            setSelectedProject(null);
        }
    };

    const formatFileSize = (bytes: number) => {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    };

    return (
        <div className="flex h-screen">
            <aside
                className={cn(
                    "bg-sidebar border-r border-sidebar-border flex flex-col transition-all duration-300 shrink-0",
                    sidebarOpen ? "w-72" : "w-0 overflow-hidden",
                )}
            >
                <div className="p-4 border-b border-sidebar-border space-y-3">
                    <Button
                        variant="outline"
                        onClick={handleNewChat}
                        className="w-full justify-start gap-2 font-mono text-xs uppercase tracking-wider rounded-sm bg-transparent border-border hover:bg-sidebar-accent hover:border-primary/40 transition-colors"
                    >
                        <Plus className="w-4 h-4 text-primary" />
                        New Chat
                    </Button>

                    <div className="flex gap-0.5 p-0.5 bg-sidebar-accent rounded-sm border border-sidebar-border">
                        <button
                            onClick={() => setActiveTab("chats")}
                            className={cn(
                                "flex-1 font-mono text-[10px] uppercase tracking-widest py-2 rounded-sm transition-all duration-200",
                                activeTab === "chats"
                                    ? "bg-card border border-border text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground/70",
                            )}
                        >
                            Chats
                        </button>
                        <button
                            onClick={() => setActiveTab("projects")}
                            className={cn(
                                "flex-1 font-mono text-[10px] uppercase tracking-widest py-2 rounded-sm transition-all duration-200",
                                activeTab === "projects"
                                    ? "bg-card border border-border text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground/70",
                            )}
                        >
                            Projects
                        </button>
                        <button
                            onClick={() => {
                                setActiveTab("sandbox");
                                setSelectedProject(null);
                                setMessages([]);
                                setSessionId(`sandbox_${Date.now()}`);
                            }}
                            className={cn(
                                "flex-1 font-mono text-[10px] uppercase tracking-widest py-2 rounded-sm transition-all duration-200",
                                activeTab === "sandbox"
                                    ? "bg-card border border-border text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground/70",
                            )}
                            title="Sandbox - Execute Python code"
                        >
                            <Terminal className="w-3 h-3 inline mr-1" />
                            Run
                        </button>
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4">
                    {activeTab === "sandbox" ? (
                        <>
                            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">
                                Sandbox
                            </h3>
                            <div className="text-center py-8">
                                <Terminal className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                <p className="font-mono text-xs text-muted-foreground">
                                    Python execution environment
                                </p>
                                <p className="font-mono text-xs text-muted-foreground mt-1">
                                    Upload files or write code to get started
                                </p>
                            </div>
                        </>
                    ) : activeTab === "chats" ? (
                        <>
                            {selectedProject && (
                                <button
                                    onClick={() => {
                                        setSelectedProject(null);
                                        setProjectSessions([]);
                                        setMessages([]);
                                        setSessionId(
                                            `session_${Date.now()}`,
                                        );
                                    }}
                                    className="flex items-center gap-2 mb-3 p-2 w-full rounded-sm hover:bg-sidebar-accent transition-colors text-muted-foreground hover:text-foreground"
                                >
                                    <ChevronLeft className="w-4 h-4" />
                                    <span className="font-mono text-xs uppercase tracking-wider">
                                        Back to all chats
                                    </span>
                                </button>
                            )}
                            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">
                                {selectedProject
                                    ? `${selectedProject.name} Chats`
                                    : "Recent Conversations"}
                            </h3>
                            {selectedProject ? (
                                // Project sessions
                                loadingProjectSessions ? (
                                    <div className="text-center py-8">
                                        <p className="font-mono text-xs text-muted-foreground">
                                            Loading project chats...
                                        </p>
                                    </div>
                                ) : projectSessions.length === 0 ? (
                                    <div className="text-center py-8">
                                        <MessageSquare className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                        <p className="font-mono text-xs text-muted-foreground">
                                            No project chats yet
                                        </p>
                                        <p className="font-mono text-xs text-muted-foreground mt-1">
                                            Ask a question to start
                                        </p>
                                    </div>
                                ) : (
                                    <div className="space-y-2">
                                        {projectSessions.map((ps) => {
                                            const isActive =
                                                ps.session_id === sessionId;
                                            const sessionDate = new Date(
                                                ps.updated_at,
                                            );
                                            const now = new Date();
                                            const diffHours =
                                                (now.getTime() -
                                                    sessionDate.getTime()) /
                                                (1000 * 60 * 60);
                                            const timeLabel =
                                                diffHours < 1
                                                    ? "Just now"
                                                    : diffHours < 24
                                                      ? "Today"
                                                      : diffHours < 48
                                                        ? "Yesterday"
                                                        : sessionDate.toLocaleDateString();

                                            return (
                                                <button
                                                    key={ps.session_id}
                                                    onClick={() =>
                                                        loadProjectSessionMessages(
                                                            ps,
                                                        )
                                                    }
                                                    className={cn(
                                                        "w-full text-left p-3 rounded-sm border transition-colors group",
                                                        isActive
                                                            ? "bg-sidebar-accent border-primary"
                                                            : "border-transparent hover:bg-sidebar-accent hover:border-sidebar-border",
                                                    )}
                                                >
                                                    <div className="flex items-start gap-3">
                                                        <FolderOpen
                                                            className={cn(
                                                                "w-4 h-4 mt-0.5 shrink-0",
                                                                isActive
                                                                    ? "text-primary"
                                                                    : "text-muted-foreground",
                                                            )}
                                                        />
                                                        <div className="flex-1 min-w-0">
                                                            <p className="font-mono text-xs font-medium text-sidebar-foreground truncate">
                                                                {
                                                                    ps.session_name
                                                                }
                                                            </p>
                                                            <div className="flex items-center gap-1 mt-2">
                                                                <Clock className="w-3 h-3 text-muted-foreground" />
                                                                <span className="font-mono text-xs text-muted-foreground">
                                                                    {timeLabel}
                                                                </span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )
                            ) : loadingSessions ? (
                                <div className="text-center py-8">
                                    <p className="font-mono text-xs text-muted-foreground">
                                        Loading sessions...
                                    </p>
                                </div>
                            ) : sessions.length === 0 ? (
                                <div className="text-center py-8">
                                    <MessageSquare className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                    <p className="font-mono text-xs text-muted-foreground">
                                        No conversations yet
                                    </p>
                                    <p className="font-mono text-xs text-muted-foreground mt-1">
                                        Start a new chat to begin
                                    </p>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    {sessions.map((session) => {
                                        const isActive =
                                            session.session_id === sessionId;
                                        const sessionDate = new Date(
                                            session.updated_at,
                                        );
                                        const now = new Date();
                                        const diffHours =
                                            (now.getTime() -
                                                sessionDate.getTime()) /
                                            (1000 * 60 * 60);
                                        const timeLabel =
                                            diffHours < 1
                                                ? "Just now"
                                                : diffHours < 24
                                                  ? "Today"
                                                  : diffHours < 48
                                                    ? "Yesterday"
                                                    : sessionDate.toLocaleDateString();

                                        return (
                                            <button
                                                key={session.session_id}
                                                onClick={() =>
                                                    loadSessionMessages(session)
                                                }
                                                className={cn(
                                                    "w-full text-left p-3 rounded-sm border transition-colors group",
                                                    isActive
                                                        ? "bg-sidebar-accent border-primary"
                                                        : "border-transparent hover:bg-sidebar-accent hover:border-sidebar-border",
                                                )}
                                            >
                                                <div className="flex items-start gap-3">
                                                    <MessageSquare
                                                        className={cn(
                                                            "w-4 h-4 mt-0.5 shrink-0",
                                                            isActive
                                                                ? "text-primary"
                                                                : "text-muted-foreground",
                                                        )}
                                                    />
                                                    <div className="flex-1 min-w-0">
                                                        <p className="font-mono text-xs font-medium text-sidebar-foreground truncate">
                                                            {
                                                                session.session_name
                                                            }
                                                        </p>
                                                        <div className="flex items-center gap-1 mt-2">
                                                            <Clock className="w-3 h-3 text-muted-foreground" />
                                                            <span className="font-mono text-xs text-muted-foreground">
                                                                {timeLabel}
                                                            </span>
                                                        </div>
                                                    </div>
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </>
                    ) : (
                        <>
                            <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground mb-4">
                                Your Projects
                            </h3>
                            <div className="space-y-2">
                                <button
                                    onClick={() => setShowNewProjectModal(true)}
                                    className="w-full p-3 rounded-sm border border-dashed border-border hover:bg-sidebar-accent hover:border-primary/30 transition-colors"
                                >
                                    <div className="flex items-center gap-3 justify-center">
                                        <Plus className="w-4 h-4 text-primary" />
                                        <span className="font-mono text-xs uppercase tracking-wider text-primary">
                                            New Project
                                        </span>
                                    </div>
                                </button>

                                {projects.map((project) => (
                                    <div
                                        key={project.id}
                                        className={cn(
                                            "w-full text-left p-3 rounded-sm border transition-colors group relative",
                                            selectedProject?.id === project.id
                                                ? "bg-sidebar-accent border-primary"
                                                : "border-transparent hover:bg-sidebar-accent hover:border-sidebar-border",
                                        )}
                                    >
                                        <button
                                            onClick={() => {
                                                loadProjectDetails(project.id);
                                                loadProjectSessions(project.id);
                                                setMessages([]);
                                                setSessionId(
                                                    `proj_${project.id.slice(0, 8)}_${Date.now()}`,
                                                );
                                                setActiveTab("chats");
                                            }}
                                            className="w-full text-left"
                                        >
                                            <div className="flex items-start gap-3">
                                                <FolderOpen className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                                                <div className="flex-1 min-w-0">
                                                    <p className="font-mono text-xs font-medium text-sidebar-foreground truncate">
                                                        {project.name}
                                                    </p>
                                                    <p className="font-mono text-xs text-muted-foreground truncate mt-1">
                                                        {project.description}
                                                    </p>
                                                    <div className="flex items-center gap-3 mt-2">
                                                        <span className="font-mono text-xs text-muted-foreground">
                                                            {project.file_count}{" "}
                                                            files
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleDeleteProject(project.id);
                                            }}
                                            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1 hover:bg-destructive/10 rounded-sm transition-opacity"
                                            aria-label="Delete project"
                                        >
                                            <Trash2 className="w-3 h-3 text-destructive" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </div>

                <div className="p-4 border-t border-sidebar-border">
                    <div className="font-mono text-xs text-muted-foreground uppercase tracking-wider text-center">
                        {activeTab === "sandbox"
                            ? "Sandbox Mode"
                            : activeTab === "chats"
                              ? selectedProject
                                  ? `${projectSessions.length} Project Chats`
                                  : `${sessions.length} Conversations`
                              : `${projects.length} Projects`}
                    </div>
                </div>
            </aside>

            <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-card border border-border rounded-r-sm p-1.5 hover:bg-secondary transition-colors"
                style={{ left: sidebarOpen ? "18rem" : "0" }}
            >
                {sidebarOpen ? (
                    <ChevronLeft className="w-4 h-4 text-muted-foreground" />
                ) : (
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                )}
                <span className="sr-only">Toggle sidebar</span>
            </button>

            <div className="flex flex-col flex-1 min-w-0">
                <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-background">
                    <div className="flex items-center gap-3">
                        {selectedProject && activeTab !== "sandbox" ? (
                            <>
                                <button
                                    onClick={() => {
                                        setSelectedProject(null);
                                        setProjectSessions([]);
                                        setMessages([]);
                                        setSessionId(
                                            `session_${Date.now()}`,
                                        );
                                    }}
                                    className="p-2 rounded-sm hover:bg-secondary transition-colors"
                                    aria-label="Back to all chats"
                                >
                                    <ChevronLeft className="w-4 h-4 text-muted-foreground" />
                                </button>
                                <div>
                                    <h1 className="font-mono text-lg font-semibold text-foreground tracking-tight">
                                        {selectedProject.name}
                                    </h1>
                                    <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
                                        {selectedProject.description}
                                    </p>
                                </div>
                            </>
                        ) : activeTab === "sandbox" ? (
                            <>
                                <div className="w-7 h-7 rounded-sm border border-primary/40 flex items-center justify-center">
                                    <Terminal className="w-3.5 h-3.5 text-primary" />
                                </div>
                                <div>
                                    <h1 className="font-mono text-lg font-semibold text-foreground tracking-tight">
                                        Sandbox
                                    </h1>
                                    <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
                                        Execute Python code
                                    </p>
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="w-7 h-7 rounded-sm border border-primary/40 flex items-center justify-center">
                                    <Sparkles className="w-3.5 h-3.5 text-primary" />
                                </div>
                                <div>
                                    <h1 className="font-mono text-lg font-semibold text-foreground tracking-tight">
                                        {currentTeam?.name || "UI-Illuminati"}
                                    </h1>
                                    {currentTeam && (
                                        <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
                                            {currentTeam.members?.length || 0}{" "}
                                            team members
                                        </p>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setIsDark(!isDark)}
                            className="p-2 rounded-sm border border-border hover:bg-secondary hover:border-border/80 transition-colors"
                            aria-label="Toggle theme"
                        >
                            {isDark ? (
                                <Sun className="w-3.5 h-3.5 text-muted-foreground" />
                            ) : (
                                <Moon className="w-3.5 h-3.5 text-muted-foreground" />
                            )}
                        </button>
                        <button
                            onClick={() => logout().then(() => window.location.href = "/login")}
                            className="p-2 rounded-sm border border-border hover:bg-secondary hover:border-border/80 transition-colors"
                            aria-label="Sign out"
                            title="Sign out"
                        >
                            <LogOut className="w-3.5 h-3.5 text-muted-foreground" />
                        </button>
                        <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest ml-1">
                            v1.0
                        </span>
                    </div>
                </header>

                {selectedProject && activeTab === "projects" && (
                    <div className="border-b border-border bg-card">
                        <div className="max-w-4xl mx-auto">
                            <button
                                onClick={() =>
                                    setShowProjectFiles(!showProjectFiles)
                                }
                                className="w-full flex items-center justify-between px-4 py-3 hover:bg-secondary/50 transition-colors"
                            >
                                <div className="flex items-center gap-2">
                                    <h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                                        Project Files
                                    </h3>
                                    <span className="font-mono text-xs text-muted-foreground">
                                        ({selectedProject.files.length})
                                    </span>
                                </div>
                                <ChevronDown
                                    className={cn(
                                        "w-4 h-4 text-muted-foreground transition-transform",
                                        !showProjectFiles && "-rotate-90",
                                    )}
                                />
                            </button>

                            {showProjectFiles && (
                                <div className="px-4 pb-4">
                                    <div className="flex justify-end mb-3">
                                        <label
                                            className={cn(
                                                "cursor-pointer",
                                                uploadingFiles &&
                                                    "pointer-events-none opacity-50",
                                            )}
                                        >
                                            <input
                                                type="file"
                                                multiple
                                                className="hidden"
                                                onChange={
                                                    handleProjectFileUpload
                                                }
                                            />
                                            <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm border border-border hover:bg-secondary transition-colors">
                                                <Upload className="w-3 h-3 text-primary" />
                                                <span className="font-mono text-xs uppercase tracking-wider text-primary">
                                                    {uploadingFiles
                                                        ? "Uploading..."
                                                        : "Upload"}
                                                </span>
                                            </div>
                                        </label>
                                    </div>

                                    {selectedProject.files.length > 0 ? (
                                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                                            {selectedProject.files.map(
                                                (file) => (
                                                    <div
                                                        key={file.id}
                                                        className="p-3 rounded-sm border border-border bg-background group hover:border-primary/30 transition-colors"
                                                    >
                                                        <div className="flex items-start justify-between gap-2">
                                                            <FileText className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                                                            <button
                                                                onClick={() =>
                                                                    handleRemoveFile(
                                                                        file.id,
                                                                    )
                                                                }
                                                                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-destructive/10 rounded-sm"
                                                                aria-label="Remove file"
                                                            >
                                                                <Trash2 className="w-3 h-3 text-destructive" />
                                                            </button>
                                                        </div>
                                                        <p
                                                            className="font-mono text-xs text-foreground truncate mt-2"
                                                            title={file.name}
                                                        >
                                                            {file.name}
                                                        </p>
                                                        <p className="font-mono text-xs text-muted-foreground mt-1">
                                                            {formatFileSize(
                                                                file.size,
                                                            )}
                                                        </p>
                                                    </div>
                                                ),
                                            )}
                                        </div>
                                    ) : (
                                        <div className="text-center py-8 border border-dashed border-border rounded-sm">
                                            <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                                            <p className="font-mono text-xs text-muted-foreground uppercase tracking-wider">
                                                No files uploaded yet
                                            </p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                <div className="flex-1 overflow-y-auto px-6 py-8">
                    {messages.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                            <div className="w-14 h-14 rounded-sm border border-primary/30 flex items-center justify-center mb-6">
                                {activeTab === "sandbox" ? (
                                    <Terminal className="w-6 h-6 text-primary" />
                                ) : (
                                    <Sparkles className="w-6 h-6 text-primary" />
                                )}
                            </div>
                            <h2 className="font-sans text-3xl font-semibold text-foreground mb-3 tracking-tight leading-tight">
                                {activeTab === "sandbox"
                                    ? "Sandbox"
                                    : currentTeam?.name || "UI-Illuminati"}
                            </h2>
                            <p className="font-mono text-xs text-muted-foreground uppercase tracking-widest max-w-md leading-relaxed">
                                {activeTab === "sandbox"
                                    ? "Execute Python code, upload files for analysis, and install packages."
                                    : loadingTeams
                                      ? "Loading teams..."
                                      : currentTeam
                                        ? `Team with ${currentTeam.members?.length || 0} specialized agents. Ask me anything to get started.`
                                        : "Autonomous AI agents at your command. Ask anything to begin."}
                            </p>
                            <div className="mt-8 flex flex-wrap gap-3 justify-center">
                                {(activeTab === "sandbox"
                                    ? [
                                          "Analyze an uploaded file",
                                          "Run a Python script",
                                          "Install a package",
                                      ]
                                    : [
                                          "Explain a concept",
                                          "Write some code",
                                          "Help me brainstorm",
                                      ]
                                ).map((suggestion) => (
                                    <button
                                        key={suggestion}
                                        onClick={() => setInput(suggestion)}
                                        className="font-mono text-[11px] uppercase tracking-wider px-4 py-2.5 border border-border rounded-sm hover:bg-secondary hover:border-primary/30 transition-all duration-200 flex items-center gap-2 group text-muted-foreground hover:text-foreground"
                                    >
                                        {suggestion}
                                        <ArrowRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-primary" />
                                    </button>
                                ))}
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-6">
                            {messages.map((message) => (
                                <div
                                    key={message.id}
                                    className={cn(
                                        "flex gap-4",
                                        message.role === "user"
                                            ? "justify-end"
                                            : "justify-start",
                                    )}
                                >
                                    {message.role === "assistant" && (
                                        <div className="w-7 h-7 rounded-sm border border-primary/30 flex items-center justify-center shrink-0 mt-0.5">
                                            <Sparkles className="w-3.5 h-3.5 text-primary" />
                                        </div>
                                    )}
                                    <div className="max-w-[70%] space-y-2">
                                        <div
                                            className={cn(
                                                "px-4 py-3 rounded-sm",
                                                message.role === "user"
                                                    ? "bg-secondary border border-border text-foreground"
                                                    : "bg-card border border-border",
                                            )}
                                        >
                                            {message.role === "assistant" ? (
                                                <div className="prose prose-sm dark:prose-invert max-w-none">
                                                    <ReactMarkdown
                                                        remarkPlugins={[
                                                            remarkGfm,
                                                        ]}
                                                    >
                                                        {message.content}
                                                    </ReactMarkdown>
                                                </div>
                                            ) : (
                                                <p className="text-sm leading-relaxed font-sans">
                                                    {message.content}
                                                </p>
                                            )}
                                        </div>
                                        {/* Display agent trace for assistant messages */}
                                        {message.role === "assistant" &&
                                            message.agentSteps &&
                                            message.agentSteps.length > 0 && (
                                                <AgentTrace
                                                    steps={message.agentSteps}
                                                    compact={true}
                                                />
                                            )}
                                    </div>
                                    {message.role === "user" && (
                                        <div className="w-7 h-7 rounded-sm border border-border flex items-center justify-center shrink-0 mt-0.5">
                                            <div className="w-3 h-3 rounded-full bg-primary" />
                                        </div>
                                    )}
                                </div>
                            ))}
                            {isLoading && (
                                <div className="flex gap-4">
                                    <div className="w-7 h-7 rounded-sm border border-primary/30 flex items-center justify-center shrink-0">
                                        <Sparkles className="w-3.5 h-3.5 text-primary" />
                                    </div>
                                    <div className="max-w-[70%] space-y-2">
                                        <div className="px-4 py-3 rounded-sm bg-card border border-border">
                                            <div className="flex gap-1">
                                                <div
                                                    className="w-2 h-2 rounded-full bg-primary animate-bounce"
                                                    style={{
                                                        animationDelay: "0s",
                                                    }}
                                                />
                                                <div
                                                    className="w-2 h-2 rounded-full bg-primary animate-bounce"
                                                    style={{
                                                        animationDelay: "0.2s",
                                                    }}
                                                />
                                                <div
                                                    className="w-2 h-2 rounded-full bg-primary animate-bounce"
                                                    style={{
                                                        animationDelay: "0.4s",
                                                    }}
                                                />
                                            </div>
                                        </div>
                                        {/* Show agent trace during loading */}
                                        {(currentAgentSteps.length > 0 ||
                                            currentProgress) && (
                                            <AgentTrace
                                                steps={currentAgentSteps}
                                                currentProgress={
                                                    currentProgress
                                                }
                                                isLoading={true}
                                                compact={false}
                                            />
                                        )}
                                    </div>
                                </div>
                            )}
                            <div ref={messagesEndRef} />
                        </div>
                    )}
                </div>

                <div className="border-t border-border p-4">
                    <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
                        {/* File Preview Section - Show in General Chat and Sandbox modes */}
                        {(!selectedProject || activeTab === "sandbox") && uploadedFiles.length > 0 && (
                            <div className="mb-3 p-3 bg-card border border-border rounded-sm">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                                        Files to upload ({uploadedFiles.length})
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => setUploadedFiles([])}
                                        className="font-mono text-xs text-destructive hover:underline"
                                    >
                                        Clear all
                                    </button>
                                </div>
                                <div className="space-y-2">
                                    {uploadedFiles.map((file, idx) => (
                                        <div
                                            key={idx}
                                            className="flex items-center justify-between p-2 bg-background rounded-sm border border-border"
                                        >
                                            <div className="flex items-center gap-2 flex-1 min-w-0">
                                                <FileText className="w-4 h-4 text-primary shrink-0" />
                                                <span className="font-mono text-xs text-foreground truncate">
                                                    {file.name}
                                                </span>
                                                <span className="font-mono text-xs text-muted-foreground">
                                                    (
                                                    {(file.size / 1024).toFixed(
                                                        1,
                                                    )}{" "}
                                                    KB)
                                                </span>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    setUploadedFiles((prev) =>
                                                        prev.filter(
                                                            (_, i) => i !== idx,
                                                        ),
                                                    )
                                                }
                                                className="p-1 hover:bg-destructive/10 rounded-sm transition-colors"
                                                aria-label="Remove file"
                                            >
                                                <X className="w-3 h-3 text-destructive" />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="relative bg-card border border-border rounded-sm overflow-hidden focus-within:border-primary transition-colors">
                            <textarea
                                ref={textareaRef}
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder={
                                    uploadedFiles.length > 0
                                        ? `Ask a question about ${uploadedFiles.length} file(s)...`
                                        : "Type your message here..."
                                }
                                className="w-full bg-transparent px-4 py-3 pr-24 font-mono text-sm resize-none focus:outline-none placeholder:text-muted-foreground"
                                rows={1}
                                style={{
                                    minHeight: "52px",
                                    maxHeight: "200px",
                                }}
                            />
                            <div className="absolute right-2 bottom-2 flex items-center gap-2">
                                <input
                                    ref={fileInputRef}
                                    type="file"
                                    multiple
                                    className="hidden"
                                    onChange={(e) => {
                                        // In general chat mode, store files for API upload
                                        if (
                                            !selectedProject &&
                                            e.target.files
                                        ) {
                                            const files = Array.from(
                                                e.target.files,
                                            );
                                            setUploadedFiles((prev) => [
                                                ...prev,
                                                ...files,
                                            ]);
                                            console.log(
                                                "[UI] Files selected:",
                                                files.map(
                                                    (f) =>
                                                        `${f.name} (${(f.size / 1024).toFixed(2)} KB)`,
                                                ),
                                            );
                                            console.log(
                                                "[UI] Total files queued:",
                                                files.length,
                                            );
                                        } else if (selectedProject) {
                                            console.log(
                                                "[UI] In project mode - files not sent to agent",
                                            );
                                        }
                                    }}
                                />
                                <button
                                    type="button"
                                    onClick={handleFileUpload}
                                    className={cn(
                                        "p-2 rounded-sm hover:bg-secondary transition-colors relative",
                                        uploadedFiles.length > 0 &&
                                            "bg-primary/10",
                                    )}
                                    aria-label="Attach file"
                                    title={
                                        uploadedFiles.length > 0
                                            ? `${uploadedFiles.length} file(s) attached`
                                            : "Attach file"
                                    }
                                >
                                    <Paperclip
                                        className={cn(
                                            "w-4 h-4",
                                            uploadedFiles.length > 0
                                                ? "text-primary"
                                                : "text-muted-foreground",
                                        )}
                                    />
                                    {uploadedFiles.length > 0 && (
                                        <span className="absolute -top-1 -right-1 w-4 h-4 bg-primary text-primary-foreground text-xs font-mono rounded-full flex items-center justify-center">
                                            {uploadedFiles.length}
                                        </span>
                                    )}
                                </button>
                                <Button
                                    type="submit"
                                    size="sm"
                                    disabled={
                                        !input.trim() ||
                                        isLoading ||
                                        (loadingTeams || (!currentTeam && activeTab !== "sandbox"))
                                    }
                                    className="font-mono text-xs uppercase tracking-wider rounded-sm bg-primary hover:bg-primary/90 disabled:opacity-50"
                                    title={
                                        !currentTeam && activeTab !== "sandbox"
                                            ? "No team available"
                                            : undefined
                                    }
                                >
                                    <Send className="w-4 h-4" />
                                </Button>
                            </div>
                        </div>
                        <p className="font-mono text-xs text-muted-foreground text-center mt-3 uppercase tracking-widest">
                            {activeTab === "sandbox"
                                ? "Press Enter to execute Python code"
                                : "Press Enter to send • Shift + Enter for new line"}
                        </p>
                    </form>
                </div>
            </div>

            {showNewProjectModal && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-card border border-border rounded-sm max-w-md w-full p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="font-mono text-base font-semibold text-foreground">
                                Create New Project
                            </h2>
                            <button
                                onClick={() => {
                                    setShowNewProjectModal(false);
                                    setNewProjectName("");
                                    setNewProjectDescription("");
                                }}
                                className="p-1 rounded-sm hover:bg-secondary transition-colors"
                                aria-label="Close modal"
                            >
                                <X className="w-4 h-4 text-muted-foreground" />
                            </button>
                        </div>

                        <div className="space-y-4">
                            <div>
                                <label
                                    htmlFor="project-name"
                                    className="block font-mono text-xs uppercase tracking-wider text-muted-foreground mb-2"
                                >
                                    Project Name
                                </label>
                                <input
                                    id="project-name"
                                    type="text"
                                    value={newProjectName}
                                    onChange={(e) =>
                                        setNewProjectName(e.target.value)
                                    }
                                    placeholder="Enter project name..."
                                    className="w-full px-3 py-2 bg-background border border-border rounded-sm font-mono text-sm focus:outline-none focus:border-primary transition-colors"
                                    autoFocus
                                />
                            </div>

                            <div>
                                <label
                                    htmlFor="project-description"
                                    className="block font-mono text-xs uppercase tracking-wider text-muted-foreground mb-2"
                                >
                                    Description
                                </label>
                                <textarea
                                    id="project-description"
                                    value={newProjectDescription}
                                    onChange={(e) =>
                                        setNewProjectDescription(e.target.value)
                                    }
                                    placeholder="Enter project description..."
                                    className="w-full px-3 py-2 bg-background border border-border rounded-sm font-mono text-sm resize-none focus:outline-none focus:border-primary transition-colors"
                                    rows={3}
                                />
                            </div>

                            <div className="flex gap-3 pt-2">
                                <Button
                                    onClick={() => {
                                        setShowNewProjectModal(false);
                                        setNewProjectName("");
                                        setNewProjectDescription("");
                                    }}
                                    variant="outline"
                                    className="flex-1 font-mono text-xs uppercase tracking-wider rounded-sm"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    onClick={handleCreateProject}
                                    disabled={!newProjectName.trim()}
                                    className="flex-1 font-mono text-xs uppercase tracking-wider rounded-sm bg-primary hover:bg-primary/90 disabled:opacity-50"
                                >
                                    Create Project
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
