import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type OnConnectStartParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { api, type NodeDef, type Problem, type WorkflowSummary } from "./api";
import FlashNode from "./FlashNode";
import {
  ColumnSelect,
  ColumnsPicker,
  SchemaPanel,
  type SchemaColumn,
} from "./ColumnPicker";
import CustomNodesModal from "./CustomNodesModal";
import { IntentEditor } from "./IntentEditor";
import type { PreviewPayload } from "./OutputPreview";
import {
  cyclePath,
  findPort,
  fromApiGraph,
  portsCompatible,
  toApiGraph,
  wouldCreateCycle,
  type FlashNodeData,
} from "./graph";
import { useI18n, type Locale } from "./i18n";
import { useUndoable } from "./undo";

const OutputPreview = lazy(() => import("./OutputPreview"));

type NodeSchemaInfo = {
  output: { row_count: number; columns: SchemaColumn[] } | null;
  upstream: { row_count: number; columns: SchemaColumn[] } | null;
  inputs: Record<string, { row_count: number; columns: SchemaColumn[] }>;
  columns: SchemaColumn[];
};

function defaultParamsFor(spec: NodeDef): Record<string, unknown> {
  if (spec.type === "join") {
    return { how: "inner", suffixes: "_x,_y", indicator: false, validate: "" };
  }
  if (spec.type === "groupby") {
    return { aggs: ["mean"], dropna: true };
  }
  return {};
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

type GraphState = { nodes: Node<FlashNodeData>[]; edges: Edge[] };

function uid() {
  return crypto.randomUUID();
}

function AppInner() {
  const { locale, setLocale, t } = useI18n();
  const [registry, setRegistry] = useState<NodeDef[]>([]);
  const [query, setQuery] = useState("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [workflowName, setWorkflowName] = useState(() => t("defaultWorkflowName"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<string[]>([]);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [customNodesOpen, setCustomNodesOpen] = useState(false);
  const [loadOpen, setLoadOpen] = useState(false);
  const [workflowList, setWorkflowList] = useState<WorkflowSummary[]>([]);
  const [examples, setExamples] = useState<
    Array<{ id: string; title: string; description: string; dataset?: string }>
  >([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileImportRef = useRef<HTMLInputElement | null>(null);
  const examplesMenuRef = useRef<HTMLDetailsElement | null>(null);
  const [confirm, setConfirm] = useState<null | { title: string; onYes: () => void }>(null);
  const [configured, setConfigured] = useState(true);
  const [maskedKey, setMaskedKey] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState<string | undefined>();
  const [finalOutputs, setFinalOutputs] = useState<Array<{ id: string; label: string }>>([]);
  const [nodeSchema, setNodeSchema] = useState<NodeSchemaInfo | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [dimHandles, setDimHandles] = useState<Set<string>>(new Set());
  const connectStart = useRef<OnConnectStartParams | null>(null);
  const localeMounted = useRef(false);

  const history = useUndoable<GraphState>({ nodes: [], edges: [] });
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<FlashNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const doneNodeIdsRef = useRef<Set<string>>(new Set());
  nodesRef.current = nodes;
  edgesRef.current = edges;

  // Sync RF state from undo present when undo/redo fires
  const skipPush = useRef(false);
  useEffect(() => {
    skipPush.current = true;
    setNodes(history.present.nodes);
    setEdges(history.present.edges);
  }, [history.present, setNodes, setEdges]);

  const pushHistory = useCallback(
    (nextNodes: Node<FlashNodeData>[], nextEdges: Edge[]) => {
      if (skipPush.current) {
        skipPush.current = false;
        return;
      }
      history.commit({ nodes: nextNodes, edges: nextEdges });
      setDirty(true);
    },
    [history]
  );

  const regMap = useMemo(() => new Map(registry.map((n) => [n.type, n])), [registry]);

  const applyWorkflow = useCallback(
    (wf: { id: string; name: string; graph: any }, registryList: NodeDef[]) => {
      const map = new Map(registryList.map((n) => [n.type, n]));
      const { nodes: ns, edges: es } = fromApiGraph(wf.graph, map);
      setWorkflowId(wf.id);
      setWorkflowName(wf.name);
      skipPush.current = true;
      setNodes(ns);
      setEdges(es);
      history.replace({ nodes: ns, edges: es });
      setSelectedId(null);
      setProblems([]);
      setPreview(null);
      setPreviewOpen(false);
      setFinalOutputs([]);
      setNodeSchema(null);
      setDirty(false);
    },
    [history, setNodes, setEdges]
  );

  const saveWorkflow = useCallback(async () => {
    if (!workflowId) {
      setToast(t("noWorkflowToSave"));
      return;
    }
    setSaving(true);
    try {
      const graph = toApiGraph(nodes, edges);
      await api.saveWorkflow(workflowId, workflowName.trim() || t("defaultWorkflowName"), graph);
      setDirty(false);
      setToast(t("workflowSaved"));
    } catch (e) {
      setToast(String(e));
    } finally {
      setSaving(false);
    }
  }, [workflowId, workflowName, nodes, edges, t]);

  const refreshWorkflowList = useCallback(async () => {
    const list = await api.workflows();
    setWorkflowList(list);
    return list;
  }, []);

  const openLoadDialog = useCallback(async () => {
    try {
      await refreshWorkflowList();
      setLoadOpen(true);
    } catch (e) {
      setToast(String(e));
    }
  }, [refreshWorkflowList]);

  const loadWorkflowById = useCallback(
    async (id: string) => {
      const wf = await api.getWorkflow(id);
      const list = registry.length ? registry : await api.nodes();
      if (!registry.length) setRegistry(list);
      applyWorkflow(wf, list);
      setLoadOpen(false);
      setToast(t("loadedWorkflow", { name: wf.name }));
    },
    [applyWorkflow, registry, t]
  );

  const newBlankWorkflow = useCallback(async () => {
    const wf = await api.createWorkflow(t("defaultWorkflowName"));
    applyWorkflow(wf, registry);
    setToast(t("createdBlank"));
  }, [applyWorkflow, registry, t]);

  const exportFlowFile = useCallback(async () => {
    if (!workflowId) return;
    // Persist latest canvas into export payload
    const graph = toApiGraph(nodes, edges);
    await api.saveWorkflow(workflowId, workflowName.trim() || t("defaultWorkflowName"), graph);
    setDirty(false);
    const payload = await api.exportWorkflow(workflowId);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(workflowName || "workflow").replace(/[\\/:*?"<>|]/g, "_")}.flow.json`;
    a.click();
    URL.revokeObjectURL(url);
    setToast(t("exportedFlow"));
  }, [workflowId, workflowName, nodes, edges, t]);

  const importFlowFile = useCallback(
    async (file: File) => {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const graph = parsed.graph ?? parsed;
      const name =
        parsed.name ||
        file.name.replace(/\.flow\.json$/i, "").replace(/\.json$/i, "") ||
        t("defaultWorkflowName");
      const wf = await api.importWorkflow({ name, graph });
      applyWorkflow(wf, registry.length ? registry : await api.nodes().then((n) => {
        setRegistry(n);
        return n;
      }));
      setToast(t("importedWorkflow", { name: wf.name }));
    },
    [applyWorkflow, registry, t]
  );

  const loadTemplate = useCallback(
    async (exampleId = "110-analysis-visualization", registryList?: NodeDef[]) => {
      const list = registryList || registry;
      const result = await api.instantiateExample(exampleId);
      applyWorkflow(result.workflow, list.length ? list : await api.nodes().then((n) => {
        setRegistry(n);
        return n;
      }));
      setToast(t("loadedTemplate", { title: result.title }));
    },
    [applyWorkflow, registry, t]
  );

  useEffect(() => {
    if (!localeMounted.current) {
      localeMounted.current = true;
      return;
    }
    Promise.all([api.nodes(), api.examples()])
      .then(([nodesList, exampleList]) => {
        setRegistry(nodesList);
        setExamples(exampleList);
      })
      .catch((e) => setToast(String(e)));
  }, [locale]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [nodesList, settings, exampleList] = await Promise.all([
          api.nodes(),
          api.settings(),
          api.examples(),
        ]);
        if (cancelled) return;
        setRegistry(nodesList);
        setExamples(exampleList);
        setConfigured(settings.configured);
        setMaskedKey(settings.masked_key);
        setModels(settings.models);
        if (settings.locale === "zh-CN" || settings.locale === "en") {
          if (settings.locale !== locale) setLocale(settings.locale);
        }
        // First open: place the analysis/visualization starter template
        await loadTemplate("110-analysis-visualization", nodesList);
      } catch (e) {
        if (!cancelled) setToast(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickExample = useCallback(
    (example: { id: string; title: string }) => {
      examplesMenuRef.current && (examplesMenuRef.current.open = false);
      setConfirm({
        title: t("confirmLoadExample", { title: example.title }),
        onYes: () => {
          setConfirm(null);
          loadTemplate(example.id).catch((e) => setToast(String(e)));
        },
      });
    },
    [loadTemplate, t]
  );

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const el = examplesMenuRef.current;
      if (!el?.open) return;
      if (event.target instanceof Node && !el.contains(event.target)) {
        el.open = false;
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  // Autosave snapshot every 30s when dirty
  useEffect(() => {
    if (!workflowId || !dirty) return;
    const timer = setInterval(() => {
      const graph = toApiGraph(nodes, edges);
      api
        .saveWorkflow(workflowId, workflowName.trim() || t("defaultWorkflowName"), graph)
        .then(() => setDirty(false))
        .catch(() => undefined);
    }, 30_000);
    return () => clearInterval(timer);
  }, [workflowId, workflowName, nodes, edges, dirty, t]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = !q
      ? registry
      : registry.filter(
          (n) =>
            n.label.toLowerCase().includes(q) ||
            n.type.includes(q) ||
            n.keywords.some((k) => k.toLowerCase().includes(q))
        );
    const groups = new Map<string, NodeDef[]>();
    for (const n of list) {
      if (!groups.has(n.category)) groups.set(n.category, []);
      groups.get(n.category)!.push(n);
    }
    // Prefer custom category near the top so uploaded nodes are easy to find
    const ordered = new Map<string, NodeDef[]>();
    for (const key of ["custom", "CUSTOM"]) {
      if (groups.has(key)) ordered.set(key, groups.get(key)!);
    }
    for (const [key, items] of [...groups.entries()].sort(([a], [b]) =>
      a.localeCompare(b)
    )) {
      if (!ordered.has(key)) ordered.set(key, items);
    }
    return ordered;
  }, [registry, query]);

  const addNode = (spec: NodeDef) => {
    const node: Node<FlashNodeData> = {
      id: uid(),
      type: "flash",
      position: { x: 120 + Math.random() * 160, y: 100 + Math.random() * 120 },
      data: {
        nodeType: spec.type,
        label: spec.label,
        params: defaultParamsFor(spec),
        status: "idle",
      },
    };
    const next = [...nodes, node];
    setNodes(next);
    pushHistory(next, edges);
  };

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) {
        return;
      }
      const srcNode = nodes.find((n) => n.id === connection.source);
      const tgtNode = nodes.find((n) => n.id === connection.target);
      const srcSpec = regMap.get(srcNode?.data.nodeType || "");
      const tgtSpec = regMap.get(tgtNode?.data.nodeType || "");
      const outPort = findPort(srcSpec, connection.sourceHandle, "out");
      const inPort = findPort(tgtSpec, connection.targetHandle, "in");
      if (!outPort || !inPort || !portsCompatible(outPort, inPort)) {
        setToast(t("portIncompatible"));
        return;
      }
      if (wouldCreateCycle(edges, connection.source, connection.target)) {
        const path = cyclePath(edges, connection.source, connection.target);
        setToast(t("cycleFormed", { path: path.join(" → ") }));
        return;
      }
      let nextEdges = edges;
      if (!inPort.multiple) {
        nextEdges = edges.filter(
          (e) => !(e.target === connection.target && e.targetHandle === connection.targetHandle)
        );
      }
      nextEdges = addEdge({ ...connection, id: uid() }, nextEdges);
      setEdges(nextEdges);
      pushHistory(nodes, nextEdges);
    },
    [nodes, edges, regMap, pushHistory, setEdges, t]
  );

  const onConnectStart = useCallback(
    (_: unknown, params: OnConnectStartParams) => {
      connectStart.current = params;
      if (!params.nodeId || !params.handleId || !params.handleType) return;
      const node = nodes.find((n) => n.id === params.nodeId);
      const spec = regMap.get(node?.data.nodeType || "");
      if (!spec) return;
      const dim = new Set<string>();
      if (params.handleType === "source") {
        const out = findPort(spec, params.handleId, "out");
        if (!out) return;
        for (const n of nodes) {
          const s = regMap.get(n.data.nodeType);
          if (!s) continue;
          for (const inp of s.inputs) {
            if (!portsCompatible(out, inp)) dim.add(`in:${inp.id}`);
          }
        }
      } else {
        const inp = findPort(spec, params.handleId, "in");
        if (!inp) return;
        for (const n of nodes) {
          const s = regMap.get(n.data.nodeType);
          if (!s) continue;
          for (const out of s.outputs) {
            if (!portsCompatible(out, inp)) dim.add(`out:${out.id}`);
          }
        }
      }
      setDimHandles(dim);
    },
    [nodes, regMap]
  );

  const onConnectEnd = useCallback(() => {
    connectStart.current = null;
    setDimHandles(new Set());
  }, []);

  const selected = nodes.find((n) => n.id === selectedId) || null;
  const selectedSpec = selected ? regMap.get(selected.data.nodeType) : undefined;

  const updateParam = (key: string, value: unknown) => {
    if (!selected) return;
    const next = nodes.map((n) =>
      n.id === selected.id
        ? { ...n, data: { ...n.data, params: { ...n.data.params, [key]: value } } }
        : n
    );
    setNodes(next);
    pushHistory(next, edges);
  };

  const updateLabel = (id: string, label: string) => {
    const next = nodesRef.current.map((n) =>
      n.id === id ? { ...n, data: { ...n.data, label } } : n
    );
    setNodes(next);
    pushHistory(next, edgesRef.current);
  };

  const refreshSchema = useCallback(
    async (nodeId: string | null) => {
      if (!nodeId) {
        setNodeSchema(null);
        return;
      }
      setSchemaLoading(true);
      try {
        const graph = toApiGraph(nodesRef.current, edgesRef.current);
        const result = await api.resolveSchema({
          graph,
          node_id: nodeId,
          run_id: runId,
        });
        setNodeSchema({
          output: result.output,
          upstream: result.upstream,
          inputs: result.inputs || {},
          columns: result.columns || [],
        });
        // Drop selected columns that no longer exist on their source schema
        const defaultNames = new Set((result.columns || []).map((c) => c.name));
        const portNames: Record<string, Set<string>> = {};
        for (const [port, sch] of Object.entries(result.inputs || {})) {
          portNames[port] = new Set((sch.columns || []).map((c) => c.name));
        }
        const spec = regMap.get(
          nodesRef.current.find((n) => n.id === nodeId)?.data.nodeType || ""
        );
        setNodes((ns) => {
          let changed = false;
          const next = ns.map((n) => {
            if (n.id !== nodeId) return n;
            const params = { ...n.data.params };
            const fieldPort = (key: string) => {
              const field = spec?.params_schema.find((f) => String(f.key) === key);
              return field && typeof field.port === "string" ? field.port : "";
            };
            const namesFor = (key: string) => {
              const port = fieldPort(key);
              return port && portNames[port] ? portNames[port] : defaultNames;
            };
            // Multi-select column params (by/values/columns/…) may include AI-derived
            // fields not yet visible in the probed schema — do not auto-drop them.
            for (const key of ["x", "y", "color"]) {
              const v = params[key];
              const names = namesFor(key);
              if (names.size === 0) continue;
              if (typeof v === "string" && v && !names.has(v)) {
                params[key] = "";
                changed = true;
              }
            }
            return changed ? { ...n, data: { ...n.data, params } } : n;
          });
          return changed ? next : ns;
        });
      } catch {
        setNodeSchema(null);
      } finally {
        setSchemaLoading(false);
      }
    },
    [runId, setNodes, regMap]
  );

  useEffect(() => {
    void refreshSchema(selectedId);
  }, [
    selectedId,
    runId,
    edges,
    refreshSchema,
    selectedId
      ? String(nodes.find((n) => n.id === selectedId)?.data.params?.path || "")
      : "",
  ]);

  const deleteSelected = useCallback(() => {
    const ids = selectedIds.length
      ? selectedIds
      : selectedId
        ? [selectedId]
        : nodesRef.current.filter((n) => n.selected).map((n) => n.id);
    const edgeIds = selectedEdgeIds.length
      ? selectedEdgeIds
      : edgesRef.current.filter((e) => e.selected).map((e) => e.id);
    if (!ids.length && !edgeIds.length) return;

    const idSet = new Set(ids);
    const edgeSet = new Set(edgeIds);
    const labels = nodesRef.current
      .filter((n) => idSet.has(n.id))
      .map((n) => n.data.label)
      .slice(0, 3);
    const listJoin = locale === "en" ? ", " : "、";
    const title =
      ids.length <= 1 && !edgeIds.length
        ? t("confirmDeleteNode", { name: labels[0] || t("unnamed") })
        : t("confirmDeleteNodes", { n: ids.length }) +
          (edgeIds.length ? t("andEdges", { n: edgeIds.length }) : "") +
          (labels.length
            ? `（${labels.join(listJoin)}${ids.length > 3 ? "…" : ""}）`
            : "") +
          "？";

    setConfirm({
      title,
      onYes: () => {
        const nextNodes = nodesRef.current.filter((n) => !idSet.has(n.id));
        const nextEdges = edgesRef.current.filter(
          (e) => !idSet.has(e.source) && !idSet.has(e.target) && !edgeSet.has(e.id)
        );
        setNodes(nextNodes);
        setEdges(nextEdges);
        setSelectedId(null);
        setSelectedIds([]);
        setSelectedEdgeIds([]);
        pushHistory(nextNodes, nextEdges);
        setConfirm(null);
      },
    });
  }, [selectedIds, selectedEdgeIds, selectedId, setNodes, setEdges, pushHistory, t, locale]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        history.undo();
        return;
      }
      if ((meta && e.key === "z" && e.shiftKey) || (meta && e.key === "y")) {
        e.preventDefault();
        history.redo();
        return;
      }
      if (meta && e.key === "s") {
        e.preventDefault();
        saveWorkflow().catch((err) => setToast(String(err)));
        return;
      }
      if (meta && e.key === "o") {
        e.preventDefault();
        openLoadDialog().catch((err) => setToast(String(err)));
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && !isEditableTarget(e.target)) {
        if (selectedIds.length || selectedEdgeIds.length || selectedId) {
          e.preventDefault();
          deleteSelected();
        }
      }
      if (meta && e.key === "a" && !isEditableTarget(e.target)) {
        e.preventDefault();
        setNodes((ns) => ns.map((n) => ({ ...n, selected: true })));
        setSelectedIds(nodesRef.current.map((n) => n.id));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    history,
    saveWorkflow,
    openLoadDialog,
    selectedIds,
    selectedEdgeIds,
    selectedId,
    deleteSelected,
    setNodes,
  ]);

  const clearCanvas = () => {
    setConfirm({
      title: t("clearCanvasConfirm"),
      onYes: () => {
        setNodes([]);
        setEdges([]);
        pushHistory([], []);
        setConfirm(null);
      },
    });
  };

  const run = async () => {
    const graph = toApiGraph(nodes, edges);
    const check = await api.precheck(graph);
    setProblems(check.problems);
    if (check.status === 422) {
      const errIds = new Set(check.problems.filter((p) => p.level === "error").map((p) => p.node_id));
      setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, highlight: errIds.has(n.id) } })));
      setToast(t("precheckFail"));
      return;
    }
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, status: "idle", highlight: false } })));
    const started = await api.run(graph);
    if (Array.isArray(started)) {
      setProblems(started);
      setToast(t("cannotStartRun"));
      return;
    }
    setRunId(started.run_id);
    setFinalOutputs([]);
    setPreview(null);
    setPreviewOpen(false);
    doneNodeIdsRef.current = new Set();
    const es = new EventSource(`/api/run/${started.run_id}/stream`);
    es.addEventListener("node_start", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setNodes((ns) =>
        ns.map((n) => (n.id === data.node_id ? { ...n, data: { ...n.data, status: "running" } } : n))
      );
    });
    es.addEventListener("node_done", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      if (data.node_id) doneNodeIdsRef.current.add(data.node_id);
      setNodes((ns) =>
        ns.map((n) => (n.id === data.node_id ? { ...n, data: { ...n.data, status: "done" } } : n))
      );
      if (data.node_id === selectedId && data.schema) {
        setNodeSchema((prev) => ({
          output: data.schema,
          upstream: prev?.upstream || null,
          inputs: prev?.inputs || {},
          columns: prev?.upstream?.columns?.length ? prev.columns : data.schema.columns || [],
        }));
      }
    });
    es.addEventListener("node_cached", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      if (data.node_id) doneNodeIdsRef.current.add(data.node_id);
      setNodes((ns) =>
        ns.map((n) => (n.id === data.node_id ? { ...n, data: { ...n.data, status: "cached" } } : n))
      );
      if (data.node_id === selectedId && data.schema) {
        setNodeSchema((prev) => ({
          output: data.schema,
          upstream: prev?.upstream || null,
          inputs: prev?.inputs || {},
          columns: prev?.upstream?.columns?.length ? prev.columns : data.schema.columns || [],
        }));
      }
    });
    es.addEventListener("node_error", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      if (data.node_id) {
        setNodes((ns) =>
          ns.map((n) => (n.id === data.node_id ? { ...n, data: { ...n.data, status: "error" } } : n))
        );
      }
      setToast(data.message || t("runError"));
    });
    es.addEventListener("run_done", () => {
      es.close();
      setToast(t("runDone"));
      const ns = nodesRef.current;
      const esEdges = edgesRef.current;
      const sources = new Set(esEdges.map((e) => e.source));
      const done = doneNodeIdsRef.current;
      const sinks = ns.filter(
        (n) =>
          done.has(n.id) &&
          !sources.has(n.id) &&
          (regMap.get(n.data.nodeType)?.outputs?.length ?? 0) > 0
      );
      // Also include terminal-ish export/chart/report even if they have no outgoing edges check failed
      const extras = ns.filter(
        (n) =>
          done.has(n.id) &&
          ["export", "ai_chart", "ai_report"].includes(n.data.nodeType) &&
          !sinks.some((s) => s.id === n.id)
      );
      setFinalOutputs(
        [...sinks, ...extras].map((n) => ({ id: n.id, label: n.data.label }))
      );
    });
  };

  const loadPreview = async (nodeId?: string, title?: string) => {
    const id = nodeId || selectedId;
    if (!runId || !id) {
      setToast(runId ? t("selectNodeFirst") : t("runWorkflowFirst"));
      return;
    }
    try {
      const payload = (await api.preview(runId, id)) as PreviewPayload;
      setPreview(payload);
      setPreviewTitle(title || nodesRef.current.find((n) => n.id === id)?.data.label);
      setPreviewOpen(true);
    } catch (e) {
      setToast(String(e));
    }
  };

  const nodeTypes = useMemo(
    () => ({
      flash: (props: any) => (
        <FlashNode
          {...props}
          spec={regMap.get(props.data.nodeType)}
          dimHandles={dimHandles}
          onRename={updateLabel}
        />
      ),
    }),
    [regMap, dimHandles]
  );

  const onNodesChangeWrapped = useCallback(
    (changes: any[]) => {
      onNodesChange(changes);
      const dragEnd = changes.some((c) => c.type === "position" && c.dragging === false);
      const removed = changes.some((c) => c.type === "remove");
      if (dragEnd || removed) {
        setTimeout(() => {
          setNodes((ns) => {
            pushHistory(ns, edgesRef.current);
            return ns;
          });
        }, 0);
      }
    },
    [onNodesChange, pushHistory, setNodes]
  );

  const onEdgesChangeWrapped = useCallback(
    (changes: any[]) => {
      onEdgesChange(changes);
      const removed = changes.some((c) => c.type === "remove");
      if (removed) {
        setTimeout(() => {
          setEdges((es) => {
            pushHistory(nodesRef.current, es);
            return es;
          });
        }, 0);
      }
    },
    [onEdgesChange, pushHistory, setEdges]
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Data<span>Flash</span>
        </div>
        <input
          className="workflow-name-input"
          value={workflowName}
          onChange={(e) => {
            setWorkflowName(e.target.value);
            setDirty(true);
          }}
          title={t("workflowName")}
        />
        {dirty ? <span className="dirty-dot" title={t("unsaved")}>●</span> : null}
        <details
          ref={examplesMenuRef}
          className="examples-menu"
          onToggle={(e) => {
            const details = e.currentTarget;
            const menu = details.querySelector<HTMLElement>(".examples-dropdown");
            const summary = details.querySelector("summary");
            if (!menu || !summary || !details.open) return;
            const rect = summary.getBoundingClientRect();
            menu.style.top = `${Math.round(rect.bottom + 6)}px`;
            menu.style.left = `${Math.round(rect.left)}px`;
          }}
        >
          <summary title={t("examplesMenuTitle")}>{t("examplesMenu")}</summary>
          <ul className="examples-dropdown">
            {examples.length === 0 ? (
              <li className="examples-empty">{t("examplesEmpty")}</li>
            ) : (
              examples.map((ex) => (
                <li key={ex.id}>
                  <button type="button" onClick={() => pickExample(ex)}>
                    <strong>{ex.title}</strong>
                    {ex.description ? <span>{ex.description}</span> : null}
                  </button>
                </li>
              ))
            )}
          </ul>
        </details>
        <button type="button" disabled={saving || !workflowId} onClick={() => saveWorkflow()}>
          {saving ? t("saving") : t("save")}
        </button>
        <button type="button" onClick={() => openLoadDialog()}>
          {t("load")}
        </button>
        <button
          type="button"
          onClick={() =>
            setConfirm({
              title: dirty ? t("confirmNewDirty") : t("confirmNew"),
              onYes: () => {
                setConfirm(null);
                newBlankWorkflow().catch((e) => setToast(String(e)));
              },
            })
          }
        >
          {t("new")}
        </button>
        <button type="button" disabled={!workflowId} onClick={() => exportFlowFile().catch((e) => setToast(String(e)))}>
          {t("export")}
        </button>
        <button type="button" onClick={() => fileImportRef.current?.click()}>
          {t("import")}
        </button>
        <input
          ref={fileImportRef}
          type="file"
          accept=".json,.flow.json,application/json"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            importFlowFile(f).catch((err) => setToast(String(err)));
          }}
        />
        <button type="button" onClick={() => history.undo()}>
          {t("undo")}
        </button>
        <button type="button" onClick={() => history.redo()}>
          {t("redo")}
        </button>
        <button type="button" onClick={clearCanvas}>
          {t("clear")}
        </button>
        <div className="spacer" />
        <button
          type="button"
          title={t("customNodesMenuTitle")}
          onClick={() => setCustomNodesOpen(true)}
        >
          {t("customNodesMenu")}
        </button>
        <button type="button" onClick={() => setSettingsOpen(true)}>
          {t("settings")}
        </button>
        <button type="button" className="primary" onClick={run}>
          {t("run")}
        </button>
      </header>

      <div className="workspace">
        <aside className="palette">
          <h2>{t("nodes")}</h2>
          <input
            placeholder={t("searchNodes")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            type="button"
            className="palette-manage-custom"
            title={t("customNodesMenuTitle")}
            onClick={() => setCustomNodesOpen(true)}
          >
            {t("paletteManageCustom")}
          </button>
          {[...filtered.entries()].map(([cat, items]) => (
            <div key={cat}>
              <div className="cat-label">{cat}</div>
              {items.map((spec) => (
                <button
                  key={spec.type}
                  type="button"
                  className="palette-item"
                  draggable
                  onDragStart={(e) => e.dataTransfer.setData("application/dataflash-node", spec.type)}
                  onClick={() => addNode(spec)}
                >
                  {spec.label}
                  {spec.custom || spec.type.startsWith("custom.") ? (
                    <span className="custom-tag">{t("customTag")}</span>
                  ) : null}
                  {spec.is_ai ? <span className="ai-tag">AI</span> : null}
                </button>
              ))}
            </div>
          ))}
        </aside>

        <div
          className="canvas-wrap"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const type = e.dataTransfer.getData("application/dataflash-node");
            const spec = regMap.get(type);
            if (spec) addNode(spec);
          }}
        >
          {!configured && (
            <div className="banner">
              {t("apiKeyBanner")}
              <a href="https://zenmux.ai/invite/GBQMC5" target="_blank" rel="noreferrer">
                zenmux.ai/invite/GBQMC5
              </a>
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChangeWrapped}
            onEdgesChange={onEdgesChangeWrapped}
            onConnect={onConnect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            onSelectionChange={({ nodes: ns, edges: es }) => {
              const ids = ns.map((n) => n.id);
              setSelectedIds(ids);
              setSelectedEdgeIds(es.map((e) => e.id));
              // Inspector focuses the last-selected node among the set.
              setSelectedId(ids.length ? ids[ids.length - 1] : null);
            }}
            fitView
            elementsSelectable
            nodesDraggable
            selectionOnDrag
            selectionMode={SelectionMode.Partial}
            panOnDrag={[1, 2]}
            panOnScroll
            multiSelectionKeyCode={["Meta", "Control"]}
            selectionKeyCode="Shift"
            deleteKeyCode={null}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} color="#c9c0ae" />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
          {toast && (
            <div className="toast" onClick={() => setToast(null)}>
              {toast}
            </div>
          )}
        </div>

        <aside className="side panel">
          <h2>{t("inspector")}</h2>
          {selectedIds.length > 1 ? (
            <div className="selection-banner">
              <p>
                {t("selectedCount", { n: selectedIds.length })}
                {selectedEdgeIds.length
                  ? t("selectedEdges", { n: selectedEdgeIds.length })
                  : ""}
              </p>
              <p className="hint">{t("selectionHint")}</p>
              <button type="button" className="danger-solid" onClick={deleteSelected}>
                {t("deleteSelected")}
              </button>
            </div>
          ) : null}
          {selected && selectedSpec ? (
            <>
              <label>
                {t("nodeLabel")}
                <input
                  key={selected.id}
                  type="text"
                  defaultValue={selected.data.label}
                  onBlur={(e) => {
                    const next = e.target.value.trim() || selectedSpec.label;
                    if (next !== selected.data.label) updateLabel(selected.id, next);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  }}
                />
              </label>
              <p className="hint">{selectedSpec.description}</p>
              {selectedSpec.type === "file_input" ? (
                <SchemaPanel
                  title={t("outputFields")}
                  columns={nodeSchema?.output?.columns || []}
                  rowCount={nodeSchema?.output?.row_count}
                  emptyHint={
                    schemaLoading
                      ? t("readingFields")
                      : selected.data.params.path
                        ? t("checkFile")
                        : t("uploadFirst")
                  }
                />
              ) : null}
              {selectedSpec.inputs.filter((p) => p.type === "table").length > 1
                ? selectedSpec.inputs
                    .filter((p) => p.type === "table")
                    .map((p) => (
                      <SchemaPanel
                        key={p.id}
                        title={t("portFields", { port: p.label || p.id })}
                        columns={nodeSchema?.inputs?.[p.id]?.columns || []}
                        rowCount={nodeSchema?.inputs?.[p.id]?.row_count}
                        emptyHint={
                          schemaLoading
                            ? t("fetchingFields")
                            : t("connectPort", { port: p.label || p.id })
                        }
                      />
                    ))
                : selectedSpec.inputs.some((p) => p.type === "table") ? (
                    <SchemaPanel
                      title={t("upstreamFields")}
                      columns={nodeSchema?.upstream?.columns || nodeSchema?.columns || []}
                      rowCount={nodeSchema?.upstream?.row_count}
                      emptyHint={
                        schemaLoading ? t("fetchingUpstream") : t("connectUpstream")
                      }
                    />
                  ) : null}
              {selectedSpec.params_schema.map((field) => {
                const key = String(field.key);
                const typ = String(field.type);
                const val = selected.data.params[key];
                const port = typeof field.port === "string" ? field.port : "";
                const pickerCols =
                  (port && nodeSchema?.inputs?.[port]?.columns) ||
                  nodeSchema?.columns ||
                  [];
                const kinds = Array.isArray(field.kinds)
                  ? (field.kinds as string[])
                  : undefined;
                if (typ === "columns" || typ === "multiselect") {
                  const current = Array.isArray(val)
                    ? (val as string[])
                    : typeof val === "string" && val
                      ? val.split(",").map((s) => s.trim()).filter(Boolean)
                      : [];
                  const options =
                    typ === "multiselect" && Array.isArray(field.options)
                      ? (field.options as string[]).map((name) => ({
                          name,
                          kind: "text",
                          dtype: "str",
                        }))
                      : pickerCols;
                  const hint =
                    key === "left_on" || key === "right_on"
                      ? t("joinKeyHint")
                      : key === "by"
                        ? t("groupByHint")
                        : key === "values"
                          ? t("valuesHint")
                          : t("aiColumnsHint");
                  return (
                    <ColumnsPicker
                      key={key}
                      label={String(field.label)}
                      columns={options}
                      value={current}
                      kinds={kinds}
                      onChange={(next) => updateParam(key, next)}
                      hint={hint}
                    />
                  );
                }
                if (typ === "column") {
                  return (
                    <ColumnSelect
                      key={key}
                      label={String(field.label)}
                      columns={pickerCols}
                      value={String(val ?? "")}
                      kinds={kinds}
                      onChange={(next) => updateParam(key, next)}
                    />
                  );
                }
                if (typ === "file") {
                  return (
                    <label key={key}>
                      {String(field.label)}
                      <input
                        type="file"
                        accept=".csv,.xlsx,.xls,.json"
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          if (!f) return;
                          const up = await api.upload(f);
                          updateParam(key, up.path);
                          void refreshSchema(selected.id);
                        }}
                      />
                      <div className="hint">{val ? String(val) : t("noFileSelected")}</div>
                    </label>
                  );
                }
                if (typ === "select" || typ === "model") {
                  const options =
                    typ === "model" ? models : ((field.options as string[]) || []);
                  return (
                    <label key={key}>
                      {String(field.label)}
                      <select
                        value={String(val ?? "")}
                        onChange={(e) => updateParam(key, e.target.value)}
                      >
                        <option value="">—</option>
                        {options.map((o) => (
                          <option key={o} value={o}>
                            {o || t("emptyOption")}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                }
                if (
                  (key === "intent" || key === "ai_intent") &&
                  (typ === "textarea" || typ === "expression") &&
                  selectedSpec.is_ai
                ) {
                  const templates = selectedSpec.intent_templates || [];
                  return (
                    <IntentEditor
                      key={`${selected.id}-${key}`}
                      label={String(field.label)}
                      value={String(val ?? "")}
                      templates={templates}
                      columns={pickerCols}
                      params={selected.data.params}
                      templateId={String(selected.data.params.intent_template_id ?? "")}
                      onChange={(intent) => updateParam(key, intent)}
                      onTemplateIdChange={(id) => updateParam("intent_template_id", id)}
                      onSyncParam={(paramKey, paramVal) => updateParam(paramKey, paramVal)}
                    />
                  );
                }
                if (typ === "textarea" || typ === "expression" || typ === "code") {
                  return (
                    <label key={key}>
                      {String(field.label)}
                      <textarea
                        value={String(val ?? "")}
                        onChange={(e) => updateParam(key, e.target.value)}
                      />
                    </label>
                  );
                }
                if (typ === "boolean") {
                  return (
                    <label key={key}>
                      <input
                        type="checkbox"
                        checked={Boolean(val)}
                        onChange={(e) => updateParam(key, e.target.checked)}
                      />{" "}
                      {String(field.label)}
                    </label>
                  );
                }
                return (
                  <label key={key}>
                    {String(field.label)}
                    <input
                      type={typ === "number" ? "number" : "text"}
                      value={val == null ? "" : String(val)}
                      onChange={(e) =>
                        updateParam(
                          key,
                          typ === "number" ? Number(e.target.value) : e.target.value
                        )
                      }
                    />
                  </label>
                );
              })}
              <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <button type="button" onClick={deleteSelected}>
                  {selectedIds.length > 1
                    ? t("deleteNodesN", { n: selectedIds.length })
                    : t("deleteNode")}
                </button>
                <button type="button" className="primary-ghost" onClick={() => loadPreview()}>
                  {t("previewOutput")}
                </button>
              </div>
            </>
          ) : selectedIds.length > 1 ? null : (
            <p className="hint">{t("inspectorEmpty")}</p>
          )}

          {finalOutputs.length > 0 && (
            <div className="final-outputs">
              <h2>{t("finalOutputs")}</h2>
              <p className="hint">{t("finalOutputsHint")}</p>
              <ul>
                {finalOutputs.map((item) => (
                  <li key={item.id}>
                    <button type="button" onClick={() => loadPreview(item.id, item.label)}>
                      {item.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {problems.length > 0 && (
            <div className="problems">
              <h2>{t("problems")}</h2>
              {problems.map((p, i) => (
                <div key={i} className={`problem ${p.level === "warn" ? "warn" : ""}`}>
                  <strong>{p.code}</strong> {p.message}
                  {p.fix_hint ? <div className="hint">{p.fix_hint}</div> : null}
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>

      {previewOpen && preview ? (
        <Suspense fallback={<div className="modal-backdrop preview-backdrop"><div className="modal">{t("loadingPreview")}</div></div>}>
          <OutputPreview
            preview={preview}
            title={previewTitle}
            modal
            onClose={() => setPreviewOpen(false)}
          />
        </Suspense>
      ) : null}

      {loadOpen && (
        <div className="modal-backdrop" onClick={() => setLoadOpen(false)}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <h3>{t("loadDialogTitle")}</h3>
            <p className="hint">{t("loadDialogHint")}</p>
            {workflowList.length === 0 ? (
              <p className="hint">{t("noSavedWorkflows")}</p>
            ) : (
              <ul className="workflow-list">
                {workflowList.map((wf) => (
                  <li key={wf.id} className={wf.id === workflowId ? "current" : ""}>
                    <button
                      type="button"
                      className="workflow-item"
                      onClick={() => {
                        if (dirty && wf.id !== workflowId) {
                          setConfirm({
                            title: t("confirmLoad", { name: wf.name }),
                            onYes: () => {
                              setConfirm(null);
                              loadWorkflowById(wf.id).catch((e) => setToast(String(e)));
                            },
                          });
                        } else {
                          loadWorkflowById(wf.id).catch((e) => setToast(String(e)));
                        }
                      }}
                    >
                      <strong>{wf.name}</strong>
                      <span>
                        {wf.updated_at
                          ? new Date(wf.updated_at).toLocaleString()
                          : wf.id.slice(0, 8)}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="danger-ghost"
                      title={t("delete")}
                      onClick={() =>
                        setConfirm({
                          title: t("confirmDeleteWorkflow", { name: wf.name }),
                          onYes: async () => {
                            setConfirm(null);
                            try {
                              await api.deleteWorkflow(wf.id);
                              await refreshWorkflowList();
                              if (wf.id === workflowId) {
                                await newBlankWorkflow();
                              }
                              setToast(t("workflowDeleted"));
                            } catch (e) {
                              setToast(String(e));
                            }
                          },
                        })
                      }
                    >
                      {t("delete")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="actions">
              <button type="button" onClick={() => setLoadOpen(false)}>
                {t("close")}
              </button>
            </div>
          </div>
        </div>
      )}

      <CustomNodesModal
        open={customNodesOpen}
        onClose={() => setCustomNodesOpen(false)}
        onRegistryChange={async () => {
          const nodesList = await api.nodes();
          setRegistry(nodesList);
        }}
        selectedFilePath={(() => {
          const n = nodes.find((x) => x.id === selectedId);
          if (!n || n.type !== "file_input") return null;
          const path = (n.data as FlashNodeData)?.params?.path;
          return typeof path === "string" && path ? path : null;
        })()}
      />

      {settingsOpen && (
        <div className="modal-backdrop" onClick={() => setSettingsOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("settingsTitle")}</h3>
            <label>
              {t("apiKeyLabel")} {maskedKey ? t("apiKeyCurrent", { key: maskedKey }) : ""}
              <input
                type="password"
                value={apiKeyInput}
                placeholder="sk-..."
                onChange={(e) => setApiKeyInput(e.target.value)}
              />
            </label>
            <p className="hint">
              {t("apiKeyHint")}
              <a href="https://zenmux.ai/invite/GBQMC5" target="_blank" rel="noreferrer">
                GBQMC5
              </a>
            </p>
            <label>
              {t("language")}
              <select
                value={locale}
                onChange={async (e) => {
                  const next = e.target.value as Locale;
                  setLocale(next);
                  try {
                    await api.saveSettings({ locale: next });
                    setToast(next === "en" ? "Language switched" : "语言已切换");
                    const nodesList = await api.nodes();
                    setRegistry(nodesList);
                  } catch (err) {
                    setToast(String(err));
                  }
                }}
              >
                <option value="zh-CN">{t("languageZh")}</option>
                <option value="en">{t("languageEn")}</option>
              </select>
            </label>
            <div className="actions">
              <button type="button" onClick={() => setSettingsOpen(false)}>
                {t("cancel")}
              </button>
              <button
                type="button"
                className="primary"
                onClick={async () => {
                  if (apiKeyInput) {
                    await api.saveSettings({ api_key: apiKeyInput });
                    setConfigured(true);
                    setApiKeyInput("");
                    const s = await api.settings();
                    setMaskedKey(s.masked_key);
                  }
                  setSettingsOpen(false);
                }}
              >
                {t("save")}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirm && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>{confirm.title}</h3>
            <div className="actions">
              <button type="button" onClick={() => setConfirm(null)}>
                {t("cancel")}
              </button>
              <button type="button" className="primary" onClick={confirm.onYes}>
                {t("confirmYes")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <AppInner />
    </ReactFlowProvider>
  );
}
