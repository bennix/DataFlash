import { getApiLocale, localeHeaders, localeQuery } from "./i18n/apiLocale";

export type PortDef = {
  id: string;
  type: string;
  label: string;
  required: boolean;
  multiple: boolean;
  default: boolean;
};

export type IntentSlotDef = {
  key: string;
  label: string;
  type: "column" | "columns" | "text";
  kinds?: string[];
  required?: boolean;
};

export type IntentTemplate = {
  id: string;
  label: string;
  description?: string;
  body: string;
  slots: IntentSlotDef[];
};

export type NodeDef = {
  type: string;
  category: string;
  label: string;
  description: string;
  keywords: string[];
  icon: string;
  priority: number;
  inputs: PortDef[];
  outputs: PortDef[];
  params_schema: Array<Record<string, unknown>>;
  is_ai: boolean;
  intent_templates?: IntentTemplate[];
  custom?: boolean;
  custom_id?: string;
  source?: string;
};

export type CustomNodeInfo = {
  id: string;
  type: string;
  label: string;
  label_en?: string;
  description?: string;
  category?: string;
  result_kind?: string;
  params_schema?: Array<Record<string, unknown>>;
  loaded?: boolean;
  error?: string | null;
};

export type Problem = {
  node_id: string | null;
  level: string;
  code: string;
  message: string;
  fix_hint: string;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body.error || res.statusText), { status: res.status, body });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type WorkflowSummary = {
  id: string;
  name: string;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowDetail = {
  id: string;
  name: string;
  graph: any;
  created_at?: string;
  updated_at?: string;
};

export const api = {
  nodes: () =>
    fetch(`/api/nodes?${localeQuery()}`, { headers: localeHeaders() }).then((r) =>
      json<NodeDef[]>(r)
    ),
  workflows: () => fetch("/api/workflows").then((r) => json<WorkflowSummary[]>(r)),
  createWorkflow: (name: string, graph?: unknown) =>
    fetch("/api/workflows", {
      method: "POST",
      headers: localeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        name,
        graph: graph ?? { format_version: 2, nodes: [], edges: [], annotations: [] },
      }),
    }).then((r) => json<WorkflowDetail>(r)),
  getWorkflow: (id: string) =>
    fetch(`/api/workflows/${id}`).then((r) => json<WorkflowDetail>(r)),
  saveWorkflow: (id: string, name: string, graph: unknown) =>
    fetch(`/api/workflows/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, graph }),
    }).then((r) => json<void>(r)),
  deleteWorkflow: (id: string) =>
    fetch(`/api/workflows/${id}`, { method: "DELETE" }).then((r) => json<void>(r)),
  exportWorkflow: (id: string) =>
    fetch(`/api/workflows/${id}/export`).then((r) => json<any>(r)),
  importWorkflow: (payload: { name?: string; graph: unknown }) =>
    fetch("/api/workflows/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => json<WorkflowDetail>(r)),
  precheck: (graph: unknown) =>
    fetch("/api/precheck", {
      method: "POST",
      headers: localeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ graph, locale: getApiLocale() }),
    }).then(async (r) => {
      const body = await r.json();
      return { status: r.status, problems: body as Problem[] };
    }),
  run: (graph: unknown) =>
    fetch("/api/run", {
      method: "POST",
      headers: localeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ graph, locale: getApiLocale() }),
    }).then((r) => json<{ run_id: string } | Problem[]>(r)),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/upload", { method: "POST", body: fd }).then((r) =>
      json<{ path: string; name: string; size: number }>(r)
    );
  },
  preview: (runId: string, nodeId: string) =>
    fetch(`/api/preview/${runId}/${nodeId}`).then((r) => json<any>(r)),
  resolveSchema: (payload: {
    graph: unknown;
    node_id: string;
    run_id?: string | null;
    target_handle?: string;
  }) =>
    fetch("/api/schema/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) =>
      json<{
        output: {
          row_count: number;
          columns: Array<{
            name: string;
            kind: string;
            dtype: string;
            role?: string;
            null_pct?: number;
            n_unique?: number;
          }>;
        } | null;
        upstream: {
          row_count: number;
          columns: Array<{
            name: string;
            kind: string;
            dtype: string;
            role?: string;
            null_pct?: number;
            n_unique?: number;
          }>;
        } | null;
        inputs?: Record<
          string,
          {
            row_count: number;
            columns: Array<{
              name: string;
              kind: string;
              dtype: string;
              role?: string;
              null_pct?: number;
              n_unique?: number;
            }>;
          }
        >;
        source_node_id: string | null;
        source_port: string | null;
        columns: Array<{
          name: string;
          kind: string;
          dtype: string;
          role?: string;
          null_pct?: number;
          n_unique?: number;
        }>;
      }>(r)
    ),
  settings: () =>
    fetch(`/api/settings?${localeQuery()}`, { headers: localeHeaders() }).then((r) =>
      json<{
        configured: boolean;
        masked_key: string | null;
        models: string[];
        locale?: string;
      }>(r)
    ),
  saveSettings: (payload: { api_key?: string; models?: string[]; locale?: string }) =>
    fetch("/api/settings", {
      method: "PUT",
      headers: localeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    }).then((r) => json<void>(r)),
  examples: () =>
    fetch(`/api/examples?${localeQuery()}`, { headers: localeHeaders() }).then((r) =>
      json<Array<{ id: string; title: string; description: string; dataset?: string }>>(r)
    ),
  instantiateExample: (id: string) =>
    fetch(`/api/examples/${id}/instantiate?${localeQuery()}`, {
      method: "POST",
      headers: localeHeaders(),
    }).then((r) =>
      json<{
        workflow: { id: string; name: string; graph: any };
        title: string;
        description: string;
      }>(r)
    ),
  customNodes: () =>
    fetch(`/api/custom-nodes?${localeQuery()}`, { headers: localeHeaders() }).then((r) =>
      json<CustomNodeInfo[]>(r)
    ),
  uploadCustomNode: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return fetch(`/api/custom-nodes/upload?${localeQuery()}`, {
      method: "POST",
      headers: localeHeaders(),
      body,
    }).then((r) =>
      json<{ id: string; type: string; label: string; description?: string }>(r)
    );
  },
  deleteCustomNode: (id: string) =>
    fetch(`/api/custom-nodes/${encodeURIComponent(id)}?${localeQuery()}`, {
      method: "DELETE",
      headers: localeHeaders(),
    }).then((r) => json<void>(r)),
  debugCustomNode: (
    id: string,
    payload: { csv_text?: string; path?: string; params?: Record<string, unknown> }
  ) =>
    fetch(`/api/custom-nodes/${encodeURIComponent(id)}/debug?${localeQuery()}`, {
      method: "POST",
      headers: localeHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    }).then(async (r) => {
      const body = await r.json();
      if (!r.ok && body?.error && body.ok === undefined) {
        throw new Error(body.error);
      }
      return body as {
        ok: boolean;
        stdout?: string;
        stderr?: string;
        error?: string | null;
        traceback?: string | null;
        duration_ms?: number;
        schema?: { columns?: Array<{ name: string; kind?: string }> };
        preview?: {
          columns?: string[];
          rows?: Array<Record<string, string>>;
          row_count?: number;
          type?: string;
          text?: string;
          value?: unknown;
        };
        input_rows?: number;
      };
    }),
  customNodeSampleUrl: () => `/api/custom-nodes/sample?${localeQuery()}`,
  customNodeAiSampleUrl: () =>
    `/api/custom-nodes/sample?id=ai_flag_rows&${localeQuery()}`,
};
