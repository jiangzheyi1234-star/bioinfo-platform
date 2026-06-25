"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import {
  graphNodeSubflowLabel,
  type GeneratedWorkflowGraphNode,
} from "./generated-workflow-model";

type SubflowControlNode = Pick<GeneratedWorkflowGraphNode, "id" | "metadata">;

export function GeneratedWorkflowSubflowControls({
  node,
  onChange,
}: {
  node: SubflowControlNode;
  onChange: (nodeId: string, label: string) => void;
}) {
  const currentLabel = graphNodeSubflowLabel(node);
  const [draftLabel, setDraftLabel] = useState(currentLabel);
  const dirty = draftLabel.trim() !== currentLabel.trim();

  useEffect(() => {
    setDraftLabel(currentLabel);
  }, [currentLabel, node.id]);

  const commit = () => {
    const nextLabel = draftLabel.trim();
    if (nextLabel === currentLabel.trim()) {
      setDraftLabel(currentLabel);
      return;
    }
    onChange(node.id, nextLabel);
  };
  const clear = () => {
    setDraftLabel("");
    if (currentLabel.trim()) onChange(node.id, "");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setDraftLabel(currentLabel);
    }
  };

  return (
    <div className="grid gap-1.5 rounded bg-white px-2 py-2" data-testid="workflow-subflow-controls">
      <div className="text-[11px] font-medium text-slate-500">子流程</div>
      <div className="grid grid-cols-[minmax(0,1fr)_32px_32px] gap-1.5">
        <Input
          value={draftLabel}
          onBlur={commit}
          onChange={(event) => setDraftLabel(event.target.value)}
          onKeyDown={onKeyDown}
          className="h-8 bg-white font-mono text-xs"
          placeholder="例如 qc_stage"
          data-testid={`workflow-subflow-label-${node.id}`}
        />
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white p-0"
          disabled={!dirty}
          onMouseDown={(event) => event.preventDefault()}
          onClick={commit}
          aria-label="应用子流程标签"
          title="应用子流程标签"
        >
          <Check strokeWidth={1.5} className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white p-0"
          disabled={!currentLabel.trim() && !draftLabel.trim()}
          onMouseDown={(event) => event.preventDefault()}
          onClick={clear}
          aria-label="清除子流程标签"
          title="清除子流程标签"
        >
          <X strokeWidth={1.5} className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
