import { useT, type MessageKey } from "./i18n";

export type SchemaColumn = {
  name: string;
  kind: string;
  dtype: string;
  role?: string;
  null_pct?: number;
  n_unique?: number;
};

const KIND_KEYS: Record<string, MessageKey> = {
  numeric: "kindNumeric",
  categorical: "kindCategorical",
  datetime: "kindDatetime",
  text: "kindText",
  boolean: "kindBoolean",
};

function useKindLabel() {
  const t = useT();
  return (kind: string) => (KIND_KEYS[kind] ? t(KIND_KEYS[kind]) : kind);
}

type MultiProps = {
  label: string;
  columns: SchemaColumn[];
  value: string[];
  onChange: (next: string[]) => void;
  kinds?: string[];
  hint?: string;
};

/** Multi-select column picker (checkbox list). */
export function ColumnsPicker({ label, columns, value, onChange, kinds, hint }: MultiProps) {
  const t = useT();
  const kindLabel = useKindLabel();
  const options = kinds?.length ? columns.filter((c) => kinds.includes(c.kind)) : columns;
  const selected = new Set(value);

  const toggle = (name: string) => {
    if (selected.has(name)) onChange(value.filter((v) => v !== name));
    else onChange([...value, name]);
  };

  const allNames = options.map((c) => c.name);
  const allSelected = allNames.length > 0 && allNames.every((n) => selected.has(n));

  return (
    <div className="column-picker">
      <div className="column-picker-head">
        <span>{label}</span>
        {options.length > 0 ? (
          <button
            type="button"
            className="linkish"
            onClick={() => onChange(allSelected ? [] : allNames)}
          >
            {allSelected ? t("clearSelection") : t("selectAll")}
          </button>
        ) : null}
      </div>
      {hint ? <p className="hint">{hint}</p> : null}
      {options.length === 0 ? (
        <p className="hint">{t("noColumns")}</p>
      ) : (
        <ul className="column-checklist">
          {options.map((c) => (
            <li key={c.name}>
              <label>
                <input
                  type="checkbox"
                  checked={selected.has(c.name)}
                  onChange={() => toggle(c.name)}
                />
                <span className="col-name">{c.name}</span>
                <em className={`col-kind kind-${c.kind}`}>{kindLabel(c.kind)}</em>
                <span className="col-dtype">{c.dtype}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type SingleProps = {
  label: string;
  columns: SchemaColumn[];
  value: string;
  onChange: (next: string) => void;
  kinds?: string[];
};

/** Single-select column dropdown. */
export function ColumnSelect({ label, columns, value, onChange, kinds }: SingleProps) {
  const kindLabel = useKindLabel();
  const options = kinds?.length ? columns.filter((c) => kinds.includes(c.kind)) : columns;
  return (
    <label>
      {label}
      <select value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {options.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name} · {kindLabel(c.kind)} ({c.dtype})
          </option>
        ))}
      </select>
    </label>
  );
}

type SchemaPanelProps = {
  title: string;
  columns: SchemaColumn[];
  rowCount?: number | null;
  emptyHint?: string;
};

/** Read-only field list (e.g. file_input output schema). */
export function SchemaPanel({ title, columns, rowCount, emptyHint }: SchemaPanelProps) {
  const t = useT();
  const kindLabel = useKindLabel();
  return (
    <div className="schema-panel">
      <h3>
        {title}
        {rowCount != null ? (
          <span className="hint">
            {" "}
            · {rowCount} {t("rows")}
          </span>
        ) : null}
      </h3>
      {columns.length === 0 ? (
        <p className="hint">{emptyHint || t("noSchemaInfo")}</p>
      ) : (
        <table className="schema-table">
          <thead>
            <tr>
              <th>{t("fieldName")}</th>
              <th>{t("fieldKind")}</th>
              <th>dtype</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>
                  <em className={`col-kind kind-${c.kind}`}>{kindLabel(c.kind)}</em>
                </td>
                <td>{c.dtype}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
