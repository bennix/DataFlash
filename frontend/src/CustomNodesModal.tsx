import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type CustomNodeInfo } from "./api";
import { useI18n } from "./i18n";

type Props = {
  open: boolean;
  onClose: () => void;
  onRegistryChange: () => void | Promise<void>;
  selectedFilePath?: string | null;
};

type DebugResult = {
  ok: boolean;
  stdout?: string;
  stderr?: string;
  error?: string | null;
  traceback?: string | null;
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
  duration_ms?: number;
};

export default function CustomNodesModal({
  open,
  onClose,
  onRegistryChange,
  selectedFilePath,
}: Props) {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<CustomNodeInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [csvText, setCsvText] = useState("a,b\n1,2\n3,4\n");
  const [useFilePath, setUseFilePath] = useState(false);
  const [paramsJson, setParamsJson] = useState('{"columns":["b"],"factor":2}');
  const [debugResult, setDebugResult] = useState<DebugResult | null>(null);
  const [debugging, setDebugging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) || null,
    [items, selectedId]
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.customNodes();
      setItems(list);
      if (list.length && !list.some((i) => i.id === selectedId)) {
        setSelectedId(list[0].id);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!selected) return;
    const schema = selected.params_schema || [];
    const defaults: Record<string, unknown> = {};
    for (const field of schema) {
      const key = String(field.key || "");
      if (!key) continue;
      if (field.default !== undefined) defaults[key] = field.default;
      else if (field.type === "columns") defaults[key] = [];
      else if (field.type === "number") defaults[key] = 1;
      else if (field.type === "boolean") defaults[key] = false;
      else defaults[key] = "";
    }
    if (selected.id === "scale_numeric") {
      defaults.columns = ["b"];
      defaults.factor = 2;
    }
    setParamsJson(JSON.stringify(defaults, null, 2));
    setDebugResult(null);
  }, [selected?.id]);

  if (!open) return null;

  async function handleUpload(file: File) {
    setUploading(true);
    setError(null);
    try {
      const info = await api.uploadCustomNode(file);
      setSelectedId(info.id);
      await refresh();
      await onRegistryChange();
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm(t("customNodesConfirmDelete", { id }))) return;
    setError(null);
    try {
      await api.deleteCustomNode(id);
      if (selectedId === id) setSelectedId(null);
      await refresh();
      await onRegistryChange();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDebug() {
    if (!selectedId) return;
    setDebugging(true);
    setError(null);
    setDebugResult(null);
    try {
      let params: Record<string, unknown> = {};
      try {
        params = JSON.parse(paramsJson || "{}");
      } catch {
        throw new Error(t("customNodesBadParams"));
      }
      const body: { params: Record<string, unknown>; csv_text?: string; path?: string } = {
        params,
      };
      if (useFilePath && selectedFilePath) body.path = selectedFilePath;
      else body.csv_text = csvText;
      const result = await api.debugCustomNode(selectedId, body);
      setDebugResult(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setDebugging(false);
    }
  }

  const labelOf = (item: CustomNodeInfo) =>
    locale === "en" ? item.label_en || item.label : item.label;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide custom-nodes-modal" onClick={(e) => e.stopPropagation()}>
        <div className="custom-nodes-head">
          <h3>{t("customNodesTitle")}</h3>
          <button type="button" onClick={onClose}>
            {t("close")}
          </button>
        </div>
        <p className="hint">{t("customNodesHint")}</p>

        <div className="custom-nodes-toolbar">
          <button
            type="button"
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
          >
            {uploading ? t("customNodesUploading") : t("customNodesUpload")}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void handleUpload(f);
            }}
          />
          <a className="button-link" href={api.customNodeSampleUrl()} download="scale_numeric.zip">
            {t("customNodesDownloadSample")}
          </a>
          <a
            className="button-link"
            href={api.customNodeAiSampleUrl()}
            download="ai_flag_rows.zip"
          >
            {t("customNodesDownloadAiSample")}
          </a>
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            {t("customNodesRefresh")}
          </button>
        </div>

        {error ? <p className="custom-nodes-error">{error}</p> : null}

        <div className="custom-nodes-body">
          <div className="custom-nodes-list">
            <h4>{t("customNodesInstalled")}</h4>
            {loading && !items.length ? <p className="hint">{t("loading")}</p> : null}
            {!loading && items.length === 0 ? (
              <p className="hint">{t("customNodesEmpty")}</p>
            ) : (
              <ul>
                {items.map((item) => (
                  <li
                    key={item.id}
                    className={item.id === selectedId ? "active" : undefined}
                  >
                    <button type="button" className="pick" onClick={() => setSelectedId(item.id)}>
                      <strong>{labelOf(item)}</strong>
                      <span>{item.type}</span>
                      {item.error ? <em>{item.error}</em> : null}
                    </button>
                    <button
                      type="button"
                      className="danger"
                      onClick={() => void handleDelete(item.id)}
                    >
                      {t("delete")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="custom-nodes-debug">
            <h4>{t("customNodesDebug")}</h4>
            {!selected ? (
              <p className="hint">{t("customNodesPickFirst")}</p>
            ) : (
              <>
                <p className="hint">
                  {labelOf(selected)} · <code>{selected.type}</code>
                </p>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={useFilePath}
                    disabled={!selectedFilePath}
                    onChange={(e) => setUseFilePath(e.target.checked)}
                  />
                  {selectedFilePath
                    ? t("customNodesUseFilePath")
                    : t("customNodesNoFilePath")}
                </label>
                {!useFilePath ? (
                  <label>
                    {t("customNodesCsv")}
                    <textarea
                      rows={5}
                      value={csvText}
                      onChange={(e) => setCsvText(e.target.value)}
                      spellCheck={false}
                    />
                  </label>
                ) : (
                  <p className="hint mono">{selectedFilePath}</p>
                )}
                <label>
                  {t("customNodesParams")}
                  <textarea
                    rows={6}
                    value={paramsJson}
                    onChange={(e) => setParamsJson(e.target.value)}
                    spellCheck={false}
                    className="mono"
                  />
                </label>
                <button
                  type="button"
                  className="primary"
                  disabled={debugging}
                  onClick={() => void handleDebug()}
                >
                  {debugging ? t("customNodesDebugging") : t("customNodesRunDebug")}
                </button>

                {debugResult ? (
                  <div className="custom-nodes-result">
                    <p className={debugResult.ok ? "ok" : "fail"}>
                      {debugResult.ok
                        ? t("customNodesDebugOk", {
                            ms: String(debugResult.duration_ms ?? ""),
                            rows: String(debugResult.preview?.row_count ?? ""),
                          })
                        : t("customNodesDebugFail")}
                    </p>
                    {debugResult.error ? (
                      <pre className="fail-block">{debugResult.error}</pre>
                    ) : null}
                    {debugResult.traceback ? (
                      <pre className="fail-block">{debugResult.traceback}</pre>
                    ) : null}
                    {debugResult.stdout ? (
                      <pre className="log-block">{debugResult.stdout}</pre>
                    ) : null}
                    {debugResult.schema?.columns?.length ? (
                      <p className="hint">
                        schema:{" "}
                        {debugResult.schema.columns
                          .map((c) => `${c.name}${c.kind ? `(${c.kind})` : ""}`)
                          .join(", ")}
                      </p>
                    ) : null}
                    {debugResult.preview?.rows?.length ? (
                      <div className="debug-table-wrap">
                        <table className="schema-table">
                          <thead>
                            <tr>
                              {(debugResult.preview.columns || []).map((c) => (
                                <th key={c}>{c}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {debugResult.preview.rows.map((row, i) => (
                              <tr key={i}>
                                {(debugResult.preview?.columns || []).map((c) => (
                                  <td key={c}>{row[c]}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                    {debugResult.preview?.text ? (
                      <pre className="log-block">{debugResult.preview.text}</pre>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
