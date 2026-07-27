import type { Edge, Node } from "@xyflow/react";
import type { NodeDef, PortDef } from "./api";

export type FlashNodeData = {
  nodeType: string;
  label: string;
  params: Record<string, unknown>;
  code?: string;
  code_locked?: boolean;
  status?: "idle" | "running" | "done" | "error" | "cached";
  highlight?: boolean;
};

export function portsCompatible(source: PortDef, target: PortDef): boolean {
  if (target.type === "any" || source.type === "any") return true;
  return source.type === target.type;
}

export function wouldCreateCycle(edges: Edge[], source: string, target: string): boolean {
  // DFS: can we reach source from target already?
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  }
  if (!adj.has(source)) adj.set(source, []);
  // tentative edge source -> target
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === source) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const n of adj.get(cur) || []) stack.push(n);
  }
  return false;
}

export function cyclePath(edges: Edge[], source: string, target: string): string[] {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  }
  const parent = new Map<string, string>();
  const stack = [target];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === source) {
      const path = [source];
      let p = cur;
      // rebuild from source via reverse... simpler: BFS
      break;
    }
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const n of adj.get(cur) || []) {
      if (!parent.has(n)) parent.set(n, cur);
      stack.push(n);
    }
  }
  // BFS for path target -> source in existing graph, then append source->target
  const q = [target];
  const prev = new Map<string, string | null>([[target, null]]);
  while (q.length) {
    const cur = q.shift()!;
    if (cur === source) {
      const path: string[] = [];
      let c: string | null = source;
      while (c) {
        path.push(c);
        c = prev.get(c) ?? null;
      }
      path.reverse();
      path.push(target);
      return path;
    }
    for (const n of adj.get(cur) || []) {
      if (!prev.has(n)) {
        prev.set(n, cur);
        q.push(n);
      }
    }
  }
  return [source, target];
}

export function toApiGraph(nodes: Node<FlashNodeData>[], edges: Edge[]) {
  return {
    format_version: 2,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      position: n.position,
      data: {
        params: n.data.params,
        code: n.data.code,
        code_locked: n.data.code_locked,
        label: n.data.label,
      },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
    })),
    annotations: [],
  };
}

export function fromApiGraph(
  graph: any,
  registry: Map<string, NodeDef>
): { nodes: Node<FlashNodeData>[]; edges: Edge[] } {
  const nodes: Node<FlashNodeData>[] = (graph?.nodes || []).map((n: any, i: number) => {
    const spec = registry.get(n.type);
    return {
      id: n.id,
      type: "flash",
      position: n.position || { x: 80 + (i % 4) * 220, y: 80 + Math.floor(i / 4) * 140 },
      data: {
        nodeType: n.type,
        label: n.data?.label || spec?.label || n.type,
        params: n.data?.params || {},
        code: n.data?.code,
        code_locked: n.data?.code_locked,
        status: "idle",
      },
    };
  });
  const edges: Edge[] = (graph?.edges || []).map((e: any) => ({
    id: e.id || `${e.source}-${e.sourceHandle}-${e.target}-${e.targetHandle}`,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle,
    targetHandle: e.targetHandle,
  }));
  return { nodes, edges };
}

export function findPort(spec: NodeDef | undefined, handle: string | null | undefined, side: "in" | "out") {
  if (!spec || !handle) return undefined;
  return (side === "in" ? spec.inputs : spec.outputs).find((p) => p.id === handle);
}
