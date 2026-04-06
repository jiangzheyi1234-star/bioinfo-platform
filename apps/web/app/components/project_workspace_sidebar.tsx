"use client";

import Link from "next/link";
import {
  LinkIcon,
  FolderPlusIcon,
  ChevronDownIcon,
  Cog6ToothIcon,
  FolderIcon,
  Squares2X2Icon,
} from "@heroicons/react/24/outline";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
} from "@/components/ui/sidebar";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import type { Project, Task } from "./detection_workspace_types";

type ProjectWorkspaceSidebarProps = {
  activeView: "workspace" | "results" | "settings" | string;
  projects: Project[];
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
};

const statusText: Record<string, string> = {
  pending: "待处理",
  queued: "排队中",
  in_progress: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function ProjectWorkspaceSidebar({
  activeView,
  projects,
  currentProjectId,
  tasks,
  selectedTaskId,
  onSelectProject,
  onSelectTask,
}: ProjectWorkspaceSidebarProps) {
  return (
    <Sidebar collapsible="none" className="codex-sidebar border-r-0">
      <SidebarHeader className="codex-sidebar-header">
        <SidebarMenu className="pt-1">
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={activeView === "connect"} className="codex-nav-button">
              <Link href="/connect">
                <LinkIcon className="h-4 w-4 shrink-0 text-zinc-500" />
                <span>连接</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={activeView === "workspace"} className="codex-nav-button">
              <Link href="/projects">
                <FolderPlusIcon className="h-4 w-4 shrink-0 text-zinc-500" />
                <span>项目</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={activeView === "results"} className="codex-nav-button">
              <Link href="/results">
                <Squares2X2Icon className="h-4 w-4 shrink-0 text-zinc-500" />
                <span>结果</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="codex-sidebar-content">
        <ScrollArea className="h-full">
          <SidebarGroup className="pb-1 pt-0">
            <SidebarGroupLabel className="codex-section-label">
              <span>项目任务</span>
            </SidebarGroupLabel>

            <SidebarGroupContent className="pt-2">
              {projects.length === 0 ? (
                <div className="codex-empty-panel">
                  <p className="text-[13px] font-medium text-zinc-700">暂无项目</p>
                  <p className="text-[12px] text-zinc-500">创建项目后，这里会显示任务列表。</p>
                </div>
              ) : (
                <div className="codex-thread-groups">
                  {projects.map((project) => {
                    const isActiveProject = project.project_id === currentProjectId;
                    const projectTasks = isActiveProject ? tasks : [];

                    return (
                      <Collapsible key={project.project_id} open={isActiveProject} className="codex-thread-group">
                        <CollapsibleTrigger asChild>
                          <SidebarMenuButton
                            className="codex-thread-group-trigger"
                            isActive={isActiveProject}
                            onClick={() => onSelectProject(project.project_id)}
                          >
                            <FolderIcon className="h-4 w-4 shrink-0 text-zinc-400" />
                            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{project.name}</span>
                            <ChevronDownIcon
                              className={cn(
                                "h-4 w-4 shrink-0 text-zinc-400 transition-transform",
                                !isActiveProject && "-rotate-90"
                              )}
                            />
                          </SidebarMenuButton>
                        </CollapsibleTrigger>

                        <CollapsibleContent className="codex-thread-group-body">
                          {projectTasks.length > 0 ? (
                            <SidebarMenuSub className="codex-thread-submenu">
                              {projectTasks.map((task) => (
                                <li key={task.task_id}>
                                  <SidebarMenuSubButton
                                    isActive={task.task_id === selectedTaskId}
                                    className="codex-thread-item"
                                    onClick={() => onSelectTask(task.task_id)}
                                  >
                                    <span className="truncate">{task.title}</span>
                                    <span className="codex-thread-meta">{statusText[task.status] || task.status}</span>
                                  </SidebarMenuSubButton>
                                </li>
                              ))}
                            </SidebarMenuSub>
                          ) : (
                            <div className="codex-thread-empty">当前项目暂无任务</div>
                          )}
                        </CollapsibleContent>
                      </Collapsible>
                    );
                  })}
                </div>
              )}
            </SidebarGroupContent>
          </SidebarGroup>
        </ScrollArea>
      </SidebarContent>

      <SidebarFooter className="codex-sidebar-footer">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={activeView === "settings"} className="codex-nav-button">
              <Link href="/settings">
                <Cog6ToothIcon className="h-4 w-4 shrink-0 text-zinc-500" />
                <span>设置</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
