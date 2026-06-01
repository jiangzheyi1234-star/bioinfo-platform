import type { DatabaseItem } from "./database-page-model";
import { databaseMatchesWorkflowResource, type WorkflowResourceSpec } from "./workflows-page-model";

export function autoBindGeneratedWorkflowResources(
  resourceEntries: Array<[string, WorkflowResourceSpec]>,
  availableResources: DatabaseItem[],
  selectedResourceIds: Record<string, string>
) {
  let next = selectedResourceIds;
  const update = (resourceKey: string, resourceId: string) => {
    if (next === selectedResourceIds) next = { ...selectedResourceIds };
    if (resourceId) {
      next[resourceKey] = resourceId;
    } else {
      delete next[resourceKey];
    }
  };

  const activeKeys = new Set(resourceEntries.map(([key]) => key));
  for (const key of Object.keys(selectedResourceIds)) {
    if (!activeKeys.has(key)) update(key, "");
  }

  for (const [key, spec] of resourceEntries) {
    const currentId = selectedResourceIds[key];
    const current = availableResources.find((database) => database.id === currentId);
    if (current && databaseMatchesWorkflowResource(current, spec)) {
      continue;
    }
    const matching = availableResources.filter((database) => databaseMatchesWorkflowResource(database, spec));
    if (spec.required !== false && matching.length === 1) {
      update(key, matching[0].id);
    } else if (matching.length !== 1 && currentId) {
      update(key, "");
    }
  }

  return next;
}
