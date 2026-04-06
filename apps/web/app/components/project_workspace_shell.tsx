"use client";

import Link from "next/link";
import { type ReactNode } from "react";
import { 
  Squares2X2Icon, 
  CircleStackIcon,
  Cog6ToothIcon, 
  FolderIcon, 
  PlusIcon,
  EllipsisHorizontalIcon
} from "@heroicons/react/24/outline";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import type { Project, Task } from "./detection_workspace_types";

type ProjectWorkspaceShellProps = {
  activeView: "workspace" | "results" | "settings" | string;
  projects: Project[];
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  error: string;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
  projectControls?: ReactNode;
  taskToolbar?: ReactNode;
  children: ReactNode;
};

const statusText: Record<string, string> = {
  pending: "等待中",
  queued: "排队中",
  in_progress: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消"
};

export function ProjectWorkspaceShell({
  activeView,
  projects,
  currentProjectId,
  tasks,
  selectedTaskId,
  error,
  onSelectProject,
  onSelectTask,
  projectControls,
  taskToolbar,
  children,
}: ProjectWorkspaceShellProps) {
  return (
    <main className="project-shell grid min-h-screen grid-cols-1 xl:grid-cols-[250px_1fr] bg-white">
      {/* 极简侧边栏 */}
      <aside className="flex flex-col h-screen bg-[#f7f7f9] border-r border-black/[0.06] py-3 px-2 gap-1 text-sm text-zinc-700 select-none" aria-label="侧边栏导航">
        
        {/* 顶部品牌 */}
        <div className="px-2 mb-3 mt-1 flex items-center h-6">
          <span className="font-semibold text-zinc-900 tracking-tight">H2OMeta</span>
        </div>

        {/* 核心导航 */}
        <nav className="flex flex-col gap-0.5">
          <Link
            href="/projects"
            className={cn(
              "flex items-center px-2 h-8 rounded-md hover:bg-black/5 transition-colors cursor-pointer",
              (activeView === "workspace" || activeView === "results") && "bg-black/5 text-zinc-900 font-medium"
            )}
          >
            <Squares2X2Icon className="w-4 h-4 mr-2 text-zinc-500" />
            流程
          </Link>
          <Link
            href="/databases"
            className={cn(
              "flex items-center px-2 h-8 rounded-md hover:bg-black/5 transition-colors cursor-pointer",
              activeView === "databases" && "bg-black/5 text-zinc-900 font-medium"
            )}
          >
            <CircleStackIcon className="w-4 h-4 mr-2 text-zinc-500" />
            数据库管理
          </Link>
        </nav>

        {/* 项目与任务区 */}
        <div className="mt-4 flex flex-col flex-1 min-h-0">
          <div className="px-2 h-7 flex items-center justify-between group mb-1">
            <span className="text-xs text-zinc-400 font-medium">项目</span>
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {projectControls}
              <button className="p-0.5 hover:bg-black/5 rounded text-zinc-400 hover:text-zinc-600 transition-colors" title="添加项目">
                <PlusIcon className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <ScrollArea className="flex-1 -mx-1 px-1">
            <div className="flex flex-col pb-4 gap-0.5">
              {projects.map((project) => {
                const isActiveProject = project.project_id === currentProjectId;
                return (
                  <div key={project.project_id} className="flex flex-col">
                    {/* 项目项 */}
                    <div
                      className={cn(
                        "flex items-center justify-between px-2 h-8 rounded-md group cursor-pointer hover:bg-black/5 transition-colors",
                        isActiveProject && "text-zinc-900 font-medium"
                      )}
                      onClick={() => onSelectProject(project.project_id)}
                    >
                      <div className="flex items-center min-w-0">
                        <FolderIcon className={cn("w-4 h-4 mr-2 shrink-0", isActiveProject ? "text-zinc-700" : "text-zinc-400")} />
                        <span className="truncate">{project.name}</span>
                      </div>
                      
                      {/* 悬浮操作菜单 (添加/删除等) */}
                      <button
                        className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-black/10 rounded text-zinc-400 hover:text-zinc-600 transition-all shrink-0 ml-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          // 预留给后续接入 Dropdown Menu
                        }}
                        title="项目操作"
                      >
                        <EllipsisHorizontalIcon className="w-4 h-4" />
                      </button>
                    </div>

                    {/* 嵌套的任务项 (仅在当前选中项目下展开) */}
                    {isActiveProject && tasks.length > 0 && (
                      <div className="flex flex-col mt-0.5 mb-1.5 gap-0.5">
                        {tasks.map((task) => (
                          <div
                            key={task.task_id}
                            className={cn(
                              "flex items-center justify-between pl-8 pr-2 h-8 rounded-md cursor-pointer hover:bg-black/5 transition-colors group/task",
                              task.task_id === selectedTaskId ? "bg-black/5 text-zinc-900 font-medium" : "text-zinc-600"
                            )}
                            onClick={() => onSelectTask(task.task_id)}
                          >
                            <span className="truncate pr-2">{task.title}</span>
                            
                            {/* 右侧淡色辅助信息 (状态) */}
                            <span className="text-[11px] text-zinc-400 shrink-0 whitespace-nowrap transition-colors group-hover/task:text-zinc-500">
                              {statusText[task.status] || task.status}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        {/* 若有任务工具栏则插入底部 */}
        {taskToolbar && (
          <div className="px-2 pb-2">
            {taskToolbar}
          </div>
        )}

        {/* 底部系统入口 */}
        <div className="mt-auto pt-2 pb-1 flex flex-col gap-0.5">
          <Link
            href="/settings"
            className={cn(
              "flex items-center px-2 h-8 rounded-md hover:bg-black/5 transition-colors cursor-pointer",
              activeView === "settings" && "bg-black/5 text-zinc-900 font-medium"
            )}
          >
            <Cog6ToothIcon className="w-4 h-4 mr-2 text-zinc-500" />
            设置
          </Link>
        </div>
      </aside>

      {/* 主内容区 */}
      <section className="project-shell-main xl:max-h-screen xl:overflow-y-auto bg-white">
        {error ? (
          <div className="mb-6 p-3 rounded-md bg-red-50 border border-red-100 text-red-600 text-sm" role="alert">
            <strong className="font-medium block mb-0.5">API Error</strong>
            <span className="font-mono text-xs">{error}</span>
          </div>
        ) : null}
        {children}
      </section>
    </main>
  );
}
