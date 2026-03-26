import { create } from "zustand";
import type { Session, TeamInfo, ProjectInfo, ProjectSession } from "@/lib/api";

interface ChatState {
  // Teams
  availableTeams: TeamInfo[];
  currentTeamId: string | null;
  setAvailableTeams: (teams: TeamInfo[]) => void;
  setCurrentTeamId: (id: string | null) => void;

  // Sessions
  sessions: Session[];
  setSessions: (sessions: Session[]) => void;

  // Projects
  projects: ProjectInfo[];
  setProjects: (
    projects: ProjectInfo[] | ((prev: ProjectInfo[]) => ProjectInfo[]),
  ) => void;
  currentProjectId: string | null;
  setCurrentProjectId: (id: string | null) => void;

  // Project sessions
  projectSessions: ProjectSession[];
  setProjectSessions: (sessions: ProjectSession[]) => void;
}

export const useChatStore = create<ChatState>()((set) => ({
  availableTeams: [],
  currentTeamId: null,
  setAvailableTeams: (teams) => set({ availableTeams: teams }),
  setCurrentTeamId: (id) => set({ currentTeamId: id }),

  sessions: [],
  setSessions: (sessions) => set({ sessions }),

  projects: [],
  setProjects: (projects) =>
    set((state) => ({
      projects:
        typeof projects === "function" ? projects(state.projects) : projects,
    })),
  currentProjectId: null,
  setCurrentProjectId: (id) => set({ currentProjectId: id }),

  projectSessions: [],
  setProjectSessions: (sessions) => set({ projectSessions: sessions }),
}));
