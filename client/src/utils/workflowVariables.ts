import type { AvailableVariable } from "../components/workflow/VariablePicker";
import type { WorkflowEdge, WorkflowNode } from "../types/workflow";

/** Returns an ordered list of node ids (topological order) or [] if a cycle exists. */
export function topologicalOrder(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): string[] {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const indegree = new Map<string, number>();
  nodes.forEach((node) => indegree.set(node.id, 0));
  const outgoing = new Map<string, string[]>();

  for (const node of nodes) outgoing.set(node.id, []);

  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    outgoing.get(edge.source)?.push(edge.target);
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
  }

  const queue: string[] = [];
  for (const [id, deg] of indegree) {
    if (deg === 0) queue.push(id);
  }

  const order: string[] = [];
  while (queue.length > 0) {
    const id = queue.shift()!;
    order.push(id);
    for (const target of outgoing.get(id) ?? []) {
      indegree.set(target, (indegree.get(target) ?? 0) - 1);
      if (indegree.get(target) === 0) queue.push(target);
    }
  }

  return order.length === nodes.length ? order : [];
}

/** Assign layered coordinates so the graph flows left-to-right by depth. */
export function autoLayout(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): Record<string, { x: number; y: number }> {
  const order = topologicalOrder(nodes, edges);
  const positions: Record<string, { x: number; y: number }> = {};

  // Nodes not in the order (cycle) fall back to a grid.
  const inOrder = new Set(order);
  const fallback = nodes
    .filter((node) => !inOrder.has(node.id))
    .map((node) => node.id);

  // Compute depth (layer) of each node via BFS from roots.
  const depth = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const node of nodes) outgoing.set(node.id, []);
  for (const edge of edges) {
    if (outgoing.has(edge.source)) outgoing.get(edge.source)!.push(edge.target);
  }
  const roots = order.filter((id) => !edges.some((e) => e.target === id));
  const queue = [...roots];
  for (const root of roots) depth.set(root, 0);
  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const target of outgoing.get(id) ?? []) {
      const nextDepth = (depth.get(id) ?? 0) + 1;
      if (!depth.has(target) || nextDepth > (depth.get(target) ?? -1)) {
        depth.set(target, nextDepth);
        queue.push(target);
      }
    }
  }

  // Group nodes by depth; stack them vertically within each layer.
  const byDepth = new Map<number, string[]>();
  for (const id of order) {
    const d = depth.get(id) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(id);
  }

  const X_GAP = 320;
  const Y_GAP = 120;
  const maxDepth = Math.max(0, ...Array.from(byDepth.keys()));
  for (let d = 0; d <= maxDepth; d += 1) {
    const layer = byDepth.get(d) ?? [];
    const midY = ((layer.length - 1) * Y_GAP) / 2;
    layer.forEach((id, index) => {
      positions[id] = { x: d * X_GAP, y: index * Y_GAP - midY };
    });
  }

  // Place fallback (cycle) nodes to the right.
  fallback.forEach((id, index) => {
    if (!positions[id]) {
      positions[id] = { x: (maxDepth + 1) * X_GAP, y: index * Y_GAP };
    }
  });

  return positions;
}

/**
 * Collect every variable that a node declares as an output.
 * - input nodes declare via `variableName`
 * - all other nodes declare via `outputVariable`
 */
export function collectAvailableVariables(
  nodes: WorkflowNode[],
): AvailableVariable[] {
  const variables: AvailableVariable[] = [];
  const seen = new Set<string>();

  for (const node of nodes) {
    const data = node.data;
    const title = String(data.title ?? node.id);

    if (data.kind === "input") {
      const name = String(data.variableName ?? "user_input").trim();
      if (name && !seen.has(name)) {
        seen.add(name);
        variables.push({ name, sourceNodeId: node.id, sourceNodeTitle: title });
      }
      continue;
    }

    if (data.kind === "variable_assign") {
      const name = String(data.variableName ?? "").trim();
      if (name && !seen.has(name)) {
        seen.add(name);
        variables.push({ name, sourceNodeId: node.id, sourceNodeTitle: title });
      }
      continue;
    }

    const name = String(data.outputVariable ?? "").trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      variables.push({ name, sourceNodeId: node.id, sourceNodeTitle: title });
    }
  }

  return variables;
}
