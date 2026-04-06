"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

const SIDEBAR_WIDTH = "15.625rem";

type SidebarProviderProps = React.ComponentProps<"div"> & {
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
};

function SidebarProvider({
  className,
  style,
  children,
  ...props
}: SidebarProviderProps) {
  return (
    <div
      data-slot="sidebar-wrapper"
      className={cn("group/sidebar-wrapper flex min-h-screen w-full", className)}
      style={
        {
          "--sidebar-width": SIDEBAR_WIDTH,
          ...style,
        } as React.CSSProperties
      }
      {...props}
    >
      {children}
    </div>
  );
}

type SidebarProps = React.ComponentProps<"aside"> & {
  side?: "left" | "right";
  collapsible?: "offcanvas" | "none";
};

function Sidebar({
  side = "left",
  collapsible = "offcanvas",
  className,
  children,
  ...props
}: SidebarProps) {
  return (
    <div
      data-slot="sidebar-container"
      data-side={side}
      className="relative hidden shrink-0 md:block"
      style={{ width: "var(--sidebar-width)" }}
    >
      <aside
        data-slot="sidebar"
        data-side={side}
        className={cn(
          "absolute inset-y-0 left-0 flex h-screen w-[--sidebar-width] flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-background))] text-[hsl(var(--sidebar-foreground))] transition-transform duration-200 ease-linear",
          className
        )}
        {...props}
      >
        {children}
      </aside>
    </div>
  );
}

function SidebarInset({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sidebar-inset"
      className={cn("relative flex min-h-screen min-w-0 flex-1 flex-col bg-background", className)}
      {...props}
    />
  );
}

function SidebarHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-header" className={cn("flex flex-col gap-2 px-3 py-3", className)} {...props} />;
}

function SidebarFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-footer" className={cn("mt-auto flex flex-col gap-2 px-2 pb-3 pt-2", className)} {...props} />;
}

function SidebarContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-content" className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-2", className)} {...props} />;
}

function SidebarGroup({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-group" className={cn("relative flex flex-col gap-1 py-2", className)} {...props} />;
}

function SidebarGroupLabel({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sidebar-group-label"
      className={cn("px-2 text-[11px] font-medium uppercase tracking-[0.08em] text-zinc-400", className)}
      {...props}
    />
  );
}

function SidebarGroupContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-group-content" className={cn("flex flex-col gap-1", className)} {...props} />;
}

function SidebarMenu({ className, ...props }: React.ComponentProps<"ul">) {
  return <ul data-slot="sidebar-menu" className={cn("m-0 flex list-none flex-col gap-1 p-0", className)} {...props} />;
}

function SidebarMenuItem({ className, ...props }: React.ComponentProps<"li">) {
  return <li data-slot="sidebar-menu-item" className={cn("group/menu-item relative", className)} {...props} />;
}

type SidebarMenuButtonProps = React.ComponentProps<"button"> & {
  asChild?: boolean;
  isActive?: boolean;
};

const SidebarMenuButton = React.forwardRef<HTMLButtonElement, SidebarMenuButtonProps>(
  ({ asChild = false, isActive = false, className, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";

    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : "button"}
        data-slot="sidebar-menu-button"
        data-active={isActive}
        className={cn(
          "peer/menu-button !m-0 !flex !h-9 !min-h-0 !w-full items-center gap-2 overflow-hidden rounded-lg !border-0 !bg-transparent !px-2 !py-0 text-left text-sm text-zinc-700 !shadow-none outline-none transition-colors hover:!bg-black/[0.04] hover:text-zinc-900 data-[active=true]:!bg-zinc-100/90 data-[active=true]:font-medium data-[active=true]:text-zinc-900",
          className
        )}
        {...props}
      />
    );
  }
);
SidebarMenuButton.displayName = "SidebarMenuButton";

function SidebarMenuSub({ className, ...props }: React.ComponentProps<"ul">) {
  return (
    <ul
      data-slot="sidebar-menu-sub"
      className={cn("m-0 mt-1 flex list-none flex-col gap-1 border-l border-[hsl(var(--sidebar-border))] pl-4 pr-1", className)}
      {...props}
    />
  );
}

function SidebarMenuSubItem({ className, ...props }: React.ComponentProps<"li">) {
  return <li data-slot="sidebar-menu-sub-item" className={cn("relative", className)} {...props} />;
}

type SidebarMenuSubButtonProps = React.ComponentProps<"button"> & {
  asChild?: boolean;
  isActive?: boolean;
};

const SidebarMenuSubButton = React.forwardRef<HTMLButtonElement, SidebarMenuSubButtonProps>(
  ({ asChild = false, isActive = false, className, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";

    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : "button"}
        data-slot="sidebar-menu-sub-button"
        data-active={isActive}
        className={cn(
          "flex !h-8 !min-h-0 !w-full items-center justify-between gap-2 overflow-hidden rounded-md !border-0 !bg-transparent !px-3 !py-0 text-left text-[13px] text-zinc-600 !shadow-none outline-none transition-colors hover:!bg-black/[0.04] hover:text-zinc-900 data-[active=true]:!bg-black/[0.05] data-[active=true]:font-medium data-[active=true]:text-zinc-900",
          className
        )}
        {...props}
      />
    );
  }
);
SidebarMenuSubButton.displayName = "SidebarMenuSubButton";

export {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
};
