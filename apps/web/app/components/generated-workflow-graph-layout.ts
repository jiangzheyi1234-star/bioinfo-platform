import type { GeneratedWorkflowGraphEdge, GeneratedWorkflowGraphNode } from "./generated-workflow-model";

const GRAPH_VIEWBOX_SIZE = 1000;
const DEFAULT_MAX_COLUMNS = 4;
const MAX_PORT_SPAN = 210;
const MIN_PORT_SPAN = 70;
const PORT_SPAN_RATIO = 0.42;

export type GeneratedWorkflowGraphNodePosition = {
  centerY: number;
  column: number;
  inputX: number;
  layer: number;
  node: GeneratedWorkflowGraphNode;
  outputX: number;
  rank: number;
  row: number;
};

export type GeneratedWorkflowGraphLayout = {
  columnCount: number;
  cycleBreakNodeIds: string[];
  items: GeneratedWorkflowGraphNodePosition[];
  missingEdgeIds: string[];
  orderedNodeIds: string[];
  positions: Map<string, GeneratedWorkflowGraphNodePosition>;
  rowCount: number;
};

export function layoutGeneratedWorkflowGraph({
  edges,
  maxColumns = DEFAULT_MAX_COLUMNS,
  nodes,
}: {
  edges: GeneratedWorkflowGraphEdge[];
  maxColumns?: number;
  nodes: GeneratedWorkflowGraphNode[];
}): GeneratedWorkflowGraphLayout {
  const nodeIds = uniqueNodeIds(nodes);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const nodeIndex = new Map(nodeIds.map((nodeId, index) => [nodeId, index]));
  const incomingCount = new Map(nodeIds.map((nodeId): [string, number] => [nodeId, 0]));
  const outgoing = new Map(nodeIds.map((nodeId): [string, Set<string>] => [nodeId, new Set()]));
  const rank = new Map(nodeIds.map((nodeId): [string, number] => [nodeId, 0]));
  const missingEdgeIds: string[] = [];

  edges.forEach((edge, index) => {
    if (!nodeIndex.has(edge.from.nodeId) || !nodeIndex.has(edge.to.nodeId)) {
      missingEdgeIds.push(edgeLayoutId(edge, index));
      return;
    }
    const targets = outgoing.get(edge.from.nodeId);
    if (!targets || targets.has(edge.to.nodeId)) return;
    targets.add(edge.to.nodeId);
    incomingCount.set(edge.to.nodeId, (incomingCount.get(edge.to.nodeId) || 0) + 1);
  });

  const remainingIncoming = new Map(incomingCount);
  const unprocessed = new Set(nodeIds);
  const queue = nodeIds.filter((nodeId) => (remainingIncoming.get(nodeId) || 0) === 0);
  const orderedIds: string[] = [];
  const cycleBreakNodeIds: string[] = [];
  const compareNodeIds = (left: string, right: string) =>
    (nodeIndex.get(left) ?? 0) - (nodeIndex.get(right) ?? 0) || left.localeCompare(right);

  while (orderedIds.length < nodeIds.length) {
    if (queue.length === 0) {
      const fallbackId = nodeIds.find((nodeId) => unprocessed.has(nodeId));
      if (!fallbackId) break;
      cycleBreakNodeIds.push(fallbackId);
      queue.push(fallbackId);
    }
    queue.sort(compareNodeIds);
    const current = queue.shift();
    if (!current || !unprocessed.has(current)) continue;
    unprocessed.delete(current);
    orderedIds.push(current);
    const nextIds = [...(outgoing.get(current) || [])].sort(compareNodeIds);
    for (const nextId of nextIds) {
      if (!unprocessed.has(nextId)) continue;
      rank.set(nextId, Math.max(rank.get(nextId) || 0, (rank.get(current) || 0) + 1));
      const nextIncoming = (remainingIncoming.get(nextId) || 0) - 1;
      remainingIncoming.set(nextId, nextIncoming);
      if (nextIncoming <= 0) queue.push(nextId);
    }
  }

  const orderedNodeIds = orderedIds;
  const orderedNodes = orderedIds
    .map((nodeId) => nodeById.get(nodeId))
    .filter((node): node is GeneratedWorkflowGraphNode => Boolean(node));
  const { columnCount, items, positions, rowCount } = graphNodePositions(orderedNodes, rank, maxColumns);
  return {
    columnCount,
    cycleBreakNodeIds,
    items,
    missingEdgeIds,
    orderedNodeIds,
    positions,
    rowCount,
  };
}

function uniqueNodeIds(nodes: GeneratedWorkflowGraphNode[]) {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const node of nodes) {
    if (seen.has(node.id)) continue;
    seen.add(node.id);
    ids.push(node.id);
  }
  return ids;
}

function graphNodePositions(nodes: GeneratedWorkflowGraphNode[], rank: Map<string, number>, maxColumns: number) {
  const layerCount = Math.max(1, Math.max(...nodes.map((node) => rank.get(node.id) || 0), 0) + 1);
  const columnCount = graphColumnCount({ layerCount, maxColumns, nodeCount: nodes.length });
  const grouped = new Map<number, Array<{ layer: number; node: GeneratedWorkflowGraphNode }>>();

  nodes.forEach((node, index) => {
    const layer = rank.get(node.id) || 0;
    const column = graphColumn({ columnCount, index, layer, layerCount });
    const group = grouped.get(column) || [];
    group.push({ layer, node });
    grouped.set(column, group);
  });

  const rowCount = Math.max(1, ...[...grouped.values()].map((group) => group.length));
  const positions = new Map<string, GeneratedWorkflowGraphNodePosition>();
  for (const [column, group] of [...grouped.entries()].sort(([left], [right]) => left - right)) {
    const rowOffset = Math.floor((rowCount - group.length) / 2);
    group.forEach(({ layer, node }, index) => {
      positions.set(node.id, graphPosition({ column, columnCount, layer, node, row: rowOffset + index, rowCount }));
    });
  }

  const items = nodes
    .map((node) => positions.get(node.id))
    .filter((item): item is GeneratedWorkflowGraphNodePosition => Boolean(item));
  return {
    columnCount,
    items,
    positions,
    rowCount,
  };
}

function graphColumnCount({ layerCount, maxColumns, nodeCount }: { layerCount: number; maxColumns: number; nodeCount: number }) {
  if (nodeCount <= 1) return 1;
  if (layerCount <= 1) return 2;
  return Math.max(1, Math.min(layerCount, Math.max(1, Math.floor(maxColumns))));
}

function graphColumn({
  columnCount,
  index,
  layer,
  layerCount,
}: {
  columnCount: number;
  index: number;
  layer: number;
  layerCount: number;
}) {
  if (layerCount <= 1) return index % columnCount;
  if (layerCount <= columnCount) return layer;
  return Math.min(columnCount - 1, Math.floor((layer / Math.max(1, layerCount - 1)) * columnCount));
}

function graphPosition({
  column,
  columnCount,
  layer,
  node,
  row,
  rowCount,
}: {
  column: number;
  columnCount: number;
  layer: number;
  node: GeneratedWorkflowGraphNode;
  row: number;
  rowCount: number;
}): GeneratedWorkflowGraphNodePosition {
  const columnWidth = GRAPH_VIEWBOX_SIZE / columnCount;
  const centerX = ((column + 0.5) / columnCount) * GRAPH_VIEWBOX_SIZE;
  const portSpan = Math.min(MAX_PORT_SPAN, Math.max(MIN_PORT_SPAN, columnWidth * PORT_SPAN_RATIO));
  return {
    centerY: ((row + 0.5) / rowCount) * GRAPH_VIEWBOX_SIZE,
    column,
    inputX: Math.max(40, centerX - portSpan),
    layer,
    node,
    outputX: Math.min(960, centerX + portSpan),
    rank: layer,
    row,
  };
}

function edgeLayoutId(edge: GeneratedWorkflowGraphEdge, index: number) {
  return edge.id || `${edge.from.nodeId}.${edge.from.port}->${edge.to.nodeId}.${edge.to.port}:${index}`;
}
