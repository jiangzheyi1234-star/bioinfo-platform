"use client";

import Link from "next/link";
import { ArchiveBoxIcon, Cog6ToothIcon, EllipsisHorizontalIcon, LinkIcon } from "@heroicons/react/24/outline";
import type { ReactNode, RefObject } from "react";

import type { TabId } from "./detection_workspace_types";

type WorkspaceShellSidebarProps = {
  activeTab: TabId;
  resolvedSshConnected: boolean;
  isEditingConnection: boolean;
  connectionMenuOpen: boolean;
  settingsMenuOpen: boolean;
  connectionMenuRef: RefObject<HTMLDivElement | null>;
  settingsMenuRef: RefObject<HTMLDivElement | null>;
  sidebarContent?: ReactNode;
  sidebarWidth: number;
  onToggleConnectionMenu: () => void;
  onToggleSettingsMenu: () => void;
  onOpenConnectionEditor?: () => void;
  onOpenSettings: () => void;
  onBeginResize: (clientX: number) => void;
};

export function WorkspaceShellSidebar({
  activeTab,
  resolvedSshConnected,
  isEditingConnection,
  connectionMenuOpen,
  settingsMenuOpen,
  connectionMenuRef,
  settingsMenuRef,
  sidebarContent,
  sidebarWidth,
  onToggleConnectionMenu,
  onToggleSettingsMenu,
  onOpenConnectionEditor,
  onOpenSettings,
  onBeginResize,
}: WorkspaceShellSidebarProps) {
  return (
    <aside className="app-sidebar" aria-label="主导航">
      <nav className="sidebar-nav sidebar-nav--top">
        <div className="sidebar-nav-row" ref={connectionMenuRef}>
          <Link
            className={`sidebar-nav-link sidebar-nav-link--connect${activeTab === "connect" ? " active" : ""}${resolvedSshConnected ? " connected" : ""}`}
            href="/connect"
          >
            <LinkIcon className="sidebar-nav-icon" />
            <span className="sidebar-nav-title">连接</span>
          </Link>
          {resolvedSshConnected && !isEditingConnection && onOpenConnectionEditor ? (
            <div className="sidebar-nav-menu-wrap">
              <button
                type="button"
                className="sidebar-nav-menu-trigger"
                aria-label="连接菜单"
                aria-expanded={connectionMenuOpen}
                onClick={onToggleConnectionMenu}
              >
                <EllipsisHorizontalIcon className="sidebar-nav-menu-icon" />
              </button>
              {connectionMenuOpen ? (
                <div className="sidebar-nav-menu">
                  <button
                    type="button"
                    className="sidebar-nav-menu-item"
                    onClick={() => {
                      onToggleConnectionMenu();
                      onOpenConnectionEditor();
                    }}
                  >
                    修改连接
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </nav>
      {sidebarContent ? <div className="sidebar-content-slot">{sidebarContent}</div> : null}
      <div className="sidebar-footer sidebar-footer--nav">
        {resolvedSshConnected ? (
          <div className="sidebar-footer-menu-wrap" ref={settingsMenuRef}>
            <button
              type="button"
              className={`sidebar-nav-link${activeTab === "settings" ? " active" : ""}`}
              aria-expanded={settingsMenuOpen}
              onClick={onToggleSettingsMenu}
            >
              <Cog6ToothIcon className="sidebar-nav-icon" />
              <span className="sidebar-nav-title">设置</span>
            </button>
            {settingsMenuOpen ? (
              <div className="sidebar-footer-menu">
                <button
                  type="button"
                  className="sidebar-footer-menu-item"
                  onClick={() => {
                    onToggleSettingsMenu();
                    onOpenSettings();
                  }}
                >
                  <ArchiveBoxIcon className="sidebar-footer-menu-icon" />
                  <span>查看归档项目</span>
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="sidebar-nav-link sidebar-nav-link--disabled" aria-disabled="true">
            <Cog6ToothIcon className="sidebar-nav-icon" />
            <span className="sidebar-nav-title">设置</span>
          </div>
        )}
      </div>
      <div
        aria-hidden="true"
        className="app-sidebar-resizer"
        data-sidebar-width={sidebarWidth}
        onPointerDown={(event) => {
          event.preventDefault();
          onBeginResize(event.clientX);
        }}
      />
    </aside>
  );
}
