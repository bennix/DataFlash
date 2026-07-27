import { useEffect, useMemo, useRef, useState } from "react";
import { ColumnSelect, ColumnsPicker, type SchemaColumn } from "./ColumnPicker";
import { useI18n } from "./i18n";

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

type Props = {
  label: string;
  value: string;
  templates: IntentTemplate[];
  columns: SchemaColumn[];
  /** Current node params — used to seed slots (columns / x / y / color …). */
  params: Record<string, unknown>;
  templateId?: string;
  onChange: (intent: string) => void;
  onTemplateIdChange: (id: string) => void;
  onSyncParam: (key: string, value: unknown) => void;
};

function formatSlot(value: unknown, join: string): string {
  if (value == null) return "";
  if (Array.isArray(value)) {
    return value.map((v) => String(v).trim()).filter(Boolean).join(join);
  }
  return String(value).trim();
}

export function fillTemplate(
  body: string,
  slots: Record<string, unknown>,
  opts?: { pending?: string; join?: string }
): string {
  const pending = opts?.pending ?? "（待选）";
  const join = opts?.join ?? "、";
  return body.replace(/\{\{(\w+)\}\}/g, (full, key: string) => {
    if (!(key in slots)) return full;
    const filled = formatSlot(slots[key], join);
    return filled || pending;
  });
}

function seedSlots(
  template: IntentTemplate | undefined,
  params: Record<string, unknown>
): Record<string, unknown> {
  if (!template) return {};
  const out: Record<string, unknown> = {};
  for (const slot of template.slots) {
    const fromParams = params[slot.key];
    if (slot.type === "columns") {
      if (Array.isArray(fromParams)) out[slot.key] = fromParams;
      else if (typeof fromParams === "string" && fromParams.trim()) {
        out[slot.key] = fromParams.split(",").map((s) => s.trim()).filter(Boolean);
      } else out[slot.key] = [];
    } else if (slot.type === "column") {
      out[slot.key] = typeof fromParams === "string" ? fromParams : "";
    } else {
      out[slot.key] = fromParams == null ? "" : String(fromParams);
    }
  }
  return out;
}

/** Params that exist on node schemas — keep them in sync when template slots share the same key. */
const SYNC_KEYS = new Set(["columns", "x", "y", "color"]);

export function IntentEditor({
  label,
  value,
  templates,
  columns,
  params,
  templateId = "",
  onChange,
  onTemplateIdChange,
  onSyncParam,
}: Props) {
  const { locale, t } = useI18n();
  const listJoin = locale === "en" ? ", " : "、";
  const fillOpts = { pending: t("intentPending"), join: listJoin };
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const selected = useMemo(
    () => templates.find((tpl) => tpl.id === templateId),
    [templates, templateId]
  );
  const [slots, setSlots] = useState<Record<string, unknown>>(() =>
    seedSlots(selected, params)
  );

  useEffect(() => {
    setSlots(seedSlots(selected, params));
    // Re-seed when template changes; params seed only at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId, selected?.id]);

  const applySlots = (nextSlots: Record<string, unknown>, body?: string) => {
    setSlots(nextSlots);
    const source = body ?? selected?.body;
    if (source) onChange(fillTemplate(source, nextSlots, fillOpts));
    for (const [key, val] of Object.entries(nextSlots)) {
      if (SYNC_KEYS.has(key)) onSyncParam(key, val);
    }
  };

  const pickTemplate = (id: string) => {
    onTemplateIdChange(id);
    const tpl = templates.find((item) => item.id === id);
    if (!tpl) {
      setSlots({});
      return;
    }
    applySlots(seedSlots(tpl, params), tpl.body);
  };

  const setSlot = (key: string, slotValue: unknown) => {
    applySlots({ ...slots, [key]: slotValue });
  };

  const insertColumn = (name: string) => {
    const el = textareaRef.current;
    if (!el) {
      onChange(value ? `${value}${value.endsWith(" ") ? "" : " "}${name}` : name);
      return;
    }
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = value.slice(0, start) + name + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + name.length;
      el.setSelectionRange(pos, pos);
    });
  };

  return (
    <div className="intent-editor">
      <div className="intent-editor-head">
        <span>{label}</span>
      </div>

      {templates.length > 0 ? (
        <label className="intent-template-select">
          {t("intentTemplate")}
          <select value={templateId} onChange={(e) => pickTemplate(e.target.value)}>
            <option value="">{t("intentCustom")}</option>
            {templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {tpl.label}
                {tpl.description ? ` · ${tpl.description}` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {selected ? (
        <div className="intent-slots">
          <p className="hint">{t("intentFillSlots")}</p>
          {selected.slots.map((slot) => {
            if (slot.type === "columns") {
              const current = Array.isArray(slots[slot.key])
                ? (slots[slot.key] as string[])
                : [];
              return (
                <ColumnsPicker
                  key={slot.key}
                  label={`${slot.label}${slot.required ? " *" : ""}`}
                  columns={columns}
                  value={current}
                  kinds={slot.kinds}
                  onChange={(next) => setSlot(slot.key, next)}
                  hint={t("intentMultiHint")}
                />
              );
            }
            if (slot.type === "column") {
              return (
                <ColumnSelect
                  key={slot.key}
                  label={`${slot.label}${slot.required ? " *" : ""}`}
                  columns={columns}
                  value={String(slots[slot.key] ?? "")}
                  kinds={slot.kinds}
                  onChange={(next) => setSlot(slot.key, next)}
                />
              );
            }
            return (
              <label key={slot.key}>
                {slot.label}
                {slot.required ? " *" : ""}
                <input
                  type="text"
                  value={String(slots[slot.key] ?? "")}
                  onChange={(e) => setSlot(slot.key, e.target.value)}
                  placeholder={t("intentFillText")}
                />
              </label>
            );
          })}
          {selected.body.includes("{{") ? (
            <p className="hint intent-preview-body">
              {t("intentTemplatePreview", { body: selected.body })}
            </p>
          ) : null}
        </div>
      ) : null}

      {columns.length > 0 ? (
        <div className="intent-insert-cols">
          <span className="hint">{t("intentInsertCols")}</span>
          <div className="intent-col-chips">
            {columns.map((c) => (
              <button
                key={c.name}
                type="button"
                className="intent-col-chip"
                title={`${c.name} · ${c.kind}`}
                onClick={() => insertColumn(c.name)}
              >
                {c.name}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="hint">{t("intentConnectUpstream")}</p>
      )}

      <label>
        {t("intentBody")}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("intentPlaceholder")}
        />
      </label>
    </div>
  );
}
