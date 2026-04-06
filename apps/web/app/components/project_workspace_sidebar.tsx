"use client";

import Link from "next/link";
import {
  ChevronDownIcon,
  CircleStackIcon,
  Cog8ToothIcon,
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
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
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
  pending: "等待中",
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
    <Sidebar collapsible="none" className="border-r border-black/[0.06] bg-[#f7f7f9]">
      <SidebarHeader className="px-3 pb-2 pt-3">
        <div className="flex h-8 items-center px-2">
          <span className="font-semibold tracking-tight text-zinc-900">H2OMeta</span>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-2 pb-3">
        <SidebarGroup className="pt-1">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={activeView === "workspace" || activeView === "results"}>
                  <Link href="/projects">
                    <Squares2X2Icon className="h-4 w-4 shrink-0 text-zinc-500" />
                    <span>流程</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={activeView === "databases"}>
                  <Link href="/databases">
                    <CircleStackIcon className="h-4 w-4 shrink-0 text-zinc-500" />
                    <span>数据库管理</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-3 pt-2">
          <SidebarGroupLabel className="px-2 text-zinc-400">项目</SidebarGroupLabel>

          <SidebarGroupContent className="mt-1">
            <SidebarMenu>
              {projects.map((project) => {
                const isActiveProject = project.project_id === currentProjectId;

                return (
                  <SidebarMenuItem key={project.project_id}>
                    <SidebarMenuButton
                      isActive={isActiveProject}
                      onClick={() => onSelectProject(project.project_id)}
                    >
                      <ChevronDownIcon
                        className={cn(
                          "h-3.5 w-3.5 shrink-0 transition-transform",
                          isActiveProject ? "text-zinc-700" : "-rotate-90 text-zinc-400"
                        )}
                      />
                      <span className="truncate">{project.name}</span>
                    </SidebarMenuButton>
                    {isActiveProject && tasks.length > 0 ? (
                      <SidebarMenuSub>
                        {tasks.map((task) => (
                          <SidebarMenuSubItem key={task.task_id}>
                            <SidebarMenuSubButton
                              isActive={task.task_id === selectedTaskId}
                              onClick={() => onSelectTask(task.task_id)}
                            >
                              <span className="truncate pr-2">{task.title}</span>
                              <span className="shrink-0 whitespace-nowrap text-[11px] text-zinc-400">
                                {statusText[task.status] || task.status}
                              </span>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    ) : null}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-black/[0.05] px-2 pb-3 pt-2">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={activeView === "settings"}>
              <Link href="/settings">
                <Cog8ToothIcon className="h-4 w-4 shrink-0 text-zinc-600" />
                <span>设置</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
