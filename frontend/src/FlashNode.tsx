import { useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { FlashNodeData } from "./graph";
import type { NodeDef } from "./api";
import { useT } from "./i18n";

type Props = NodeProps & {
  data: FlashNodeData;
  spec?: NodeDef;
  dimHandles?: Set<string>;
  onRename?: (id: string, label: string) => void;
};

export default function FlashNode({ id, data, selected, spec, dimHandles, onRename }: Props) {
  const t = useT();
  const inputs = spec?.inputs || [];
  const outputs = spec?.outputs || [];
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(data.label);

  const commit = () => {
    const next = draft.trim() || spec?.label || data.nodeType;
    setEditing(false);
    if (next !== data.label) onRename?.(id, next);
    setDraft(next);
  };

  return (
    <div
      className={`flash-node status-${data.status || "idle"} ${selected ? "selected" : ""} ${data.highlight ? "highlight" : ""}`}
    >
      <header>
        <span className="cat">{spec?.category || "node"}</span>
        {editing ? (
          <input
            className="node-label-input nodrag nopan"
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") {
                setDraft(data.label);
                setEditing(false);
              }
            }}
          />
        ) : (
          <strong
            className="node-label"
            title={t("renameHint")}
            onDoubleClick={(e) => {
              e.stopPropagation();
              setDraft(data.label);
              setEditing(true);
            }}
          >
            {data.label}
          </strong>
        )}
        {data.status === "running" ? (
          <em className="run-badge">
            <span className="dot" aria-hidden />
            {t("running")}
          </em>
        ) : spec?.is_ai ? (
          <em className="ai">AI</em>
        ) : null}
      </header>
      <div className="ports">
        <div className="ins">
          {inputs.map((p) => (
            <div key={p.id} className="port-row">
              <Handle
                type="target"
                position={Position.Left}
                id={p.id}
                className={`port port-${p.type}`}
                style={{ opacity: dimHandles?.has(`in:${p.id}`) ? 0.25 : 1 }}
              />
              <span>{p.label || p.id}</span>
            </div>
          ))}
        </div>
        <div className="outs">
          {outputs.map((p) => (
            <div key={p.id} className="port-row out">
              <span>{p.label || p.id}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={p.id}
                className={`port port-${p.type}`}
                style={{ opacity: dimHandles?.has(`out:${p.id}`) ? 0.25 : 1 }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
