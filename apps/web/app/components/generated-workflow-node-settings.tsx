import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type { AddedTool } from "./tools-page-model";

type GeneratedWorkflowNodeSettingsProps =
  | {
      node: { id: string; toolId: string };
      onStepIdChange: (stepId: string, nextId: string) => void;
      onStepToolChange: (stepId: string, toolId: string) => void;
      tools: AddedTool[];
    }
  | {
      nodeId: string;
      onStepIdChange: (value: string) => void;
      onStepToolChange: (toolId: string) => void;
      toolId: string;
      tools: AddedTool[];
    };

export function GeneratedWorkflowNodeSettings(props: GeneratedWorkflowNodeSettingsProps) {
  const nodeId = "node" in props ? props.node.id : props.nodeId;
  const toolId = "node" in props ? props.node.toolId : props.toolId;
  const tools = props.tools;
  const onNodeIdChange = (value: string) => {
    if ("node" in props) {
      props.onStepIdChange(props.node.id, value);
    } else {
      props.onStepIdChange(value);
    }
  };
  const onToolChange = (value: string) => {
    if ("node" in props) {
      props.onStepToolChange(props.node.id, value);
    } else {
      props.onStepToolChange(value);
    }
  };
  return (
    <div className="rounded-md bg-white px-3 py-2">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">节点设置</div>
      <div className="grid gap-2">
        <div>
          <Label className="text-[11px] text-slate-500" htmlFor="generated-node-id">
            节点 ID
          </Label>
          <Input
            id="generated-node-id"
            value={nodeId}
            onChange={(event) => onNodeIdChange(event.target.value)}
            className="mt-1 h-8 font-mono text-xs"
          />
        </div>
        <div>
          <Label className="text-[11px] text-slate-500">工具</Label>
          <Select value={toolId} onValueChange={onToolChange}>
            <SelectTrigger className="mt-1 h-8 bg-white text-xs">
              <SelectValue placeholder="选择工具" />
            </SelectTrigger>
            <SelectContent>
              {tools.map((tool) => (
                <SelectItem key={tool.id} value={tool.id}>
                  {tool.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
