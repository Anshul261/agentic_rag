"use client"

import { Bot, FileText, Loader2, CheckCircle2, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"

export interface AgentTraceStep {
  type: 'tool_call' | 'agent_start' | 'agent_end' | 'progress'
  title: string
  description?: string
  timestamp: string
  agent?: string
  tool?: string
  status?: 'running' | 'completed' | 'error'
}

interface AgentTraceProps {
  steps: AgentTraceStep[]
  currentProgress?: string
  isLoading?: boolean
  compact?: boolean
}

export function AgentTrace({ steps, currentProgress, isLoading = false, compact = false }: AgentTraceProps) {
  if (steps.length === 0 && !currentProgress) return null

  // In compact mode, only show the last 3 steps
  const displaySteps = compact ? steps.slice(-3) : steps

  return (
    <div className={cn(
      "border border-border/50 rounded-lg bg-card/30 backdrop-blur-sm",
      compact ? "p-2" : "p-3"
    )}>
      <div className="flex items-center gap-2 mb-2">
        <Bot className="w-3.5 h-3.5 text-primary" />
        <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Agent Activity
        </span>
        {isLoading && (
          <Loader2 className="w-3 h-3 text-primary animate-spin ml-auto" />
        )}
      </div>

      {/* Current Progress */}
      {currentProgress && (
        <div className="mb-2 px-2 py-1.5 bg-primary/5 border border-primary/20 rounded text-xs text-foreground flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          {currentProgress}
        </div>
      )}

      {/* Steps List */}
      {displaySteps.length > 0 && (
        <div className="space-y-1.5">
          {displaySteps.map((step, index) => (
            <div
              key={index}
              className={cn(
                "flex items-start gap-2 text-xs transition-all",
                compact && "py-0.5"
              )}
            >
              {/* Step Icon/Status */}
              <div className="mt-0.5 flex-shrink-0">
                {step.status === 'completed' ? (
                  <CheckCircle2 className="w-3 h-3 text-green-500" />
                ) : step.status === 'error' ? (
                  <AlertCircle className="w-3 h-3 text-destructive" />
                ) : step.type === 'tool_call' ? (
                  <FileText className="w-3 h-3 text-blue-500" />
                ) : (
                  <div className={cn(
                    "w-2 h-2 rounded-full mt-0.5",
                    step.type === 'agent_start' ? "bg-green-400" :
                    step.type === 'agent_end' ? "bg-gray-400" :
                    "bg-blue-400"
                  )} />
                )}
              </div>

              {/* Step Content */}
              <div className="flex-1 min-w-0">
                <div className="text-foreground font-medium truncate">
                  {step.title}
                </div>
                {step.description && !compact && (
                  <div className="text-muted-foreground text-[10px] mt-0.5 line-clamp-2">
                    {step.description}
                  </div>
                )}
                {step.agent && (
                  <div className="text-primary text-[10px] mt-0.5">
                    {step.tool ? `${step.agent} • ${step.tool}` : step.agent}
                  </div>
                )}
              </div>

              {/* Timestamp */}
              {!compact && (
                <div className="text-muted-foreground text-[10px] whitespace-nowrap flex-shrink-0">
                  {step.timestamp}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Show collapsed indicator in compact mode */}
      {compact && steps.length > 3 && (
        <div className="text-center mt-1.5 pt-1.5 border-t border-border/30">
          <span className="text-[10px] text-muted-foreground font-mono">
            +{steps.length - 3} more steps
          </span>
        </div>
      )}
    </div>
  )
}
