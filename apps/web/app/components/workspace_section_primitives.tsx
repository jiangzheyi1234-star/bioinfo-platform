"use client";

import type { ElementType, ReactNode } from "react";

type WorkspaceSectionHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  titleAs?: ElementType;
  className?: string;
};

type WorkspaceEmptyStateProps = {
  label: ReactNode;
  hint?: ReactNode;
  mark?: string;
  compact?: boolean;
  className?: string;
};

function joinClasses(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function WorkspaceSectionHeader({
  title,
  description,
  aside,
  titleAs: TitleTag = "h3",
  className,
}: WorkspaceSectionHeaderProps) {
  return (
    <div className={joinClasses("workspace-section-header", className)}>
      <div className="workspace-section-copy">
        <TitleTag className="workspace-section-title">{title}</TitleTag>
        {description ? <p className="workspace-section-description">{description}</p> : null}
      </div>
      {aside ? <div className="workspace-section-aside">{aside}</div> : null}
    </div>
  );
}

export function WorkspaceEmptyState({
  label,
  hint,
  mark = "Empty",
  compact = false,
  className,
}: WorkspaceEmptyStateProps) {
  return (
    <div className={joinClasses("workspace-empty-state", compact && "workspace-empty-state--compact", className)}>
      <div className="placeholder-mark">{mark}</div>
      <div className="workspace-empty-copy">
        <p className="workspace-empty-label">{label}</p>
        {hint ? <p className="workspace-empty-hint">{hint}</p> : null}
      </div>
    </div>
  );
}
