import { useEffect, useState } from "react";
import FigureViewer from "./FigureViewer";
import MarkdownView, { looksLikeMarkdown } from "./MarkdownView";
import PdfViewer from "./PdfViewer";
import { useT, type MessageKey } from "./i18n";

export type PreviewPayload =
  | {
      type: "table";
      columns: string[];
      rows: Record<string, unknown>[];
      row_count: number;
    }
  | { type: "figure"; figure: { data: unknown[]; layout?: Record<string, unknown> } }
  | { type: "text"; text: string }
  | { type: "markdown"; text: string }
  | {
      type: "file";
      name: string;
      format: string;
      size: number;
      path: string;
      file_url: string;
    }
  | { type: "value"; value: unknown };

type Props = {
  preview: PreviewPayload;
  title?: string;
  onClose?: () => void;
  modal?: boolean;
};

const TITLE_KEYS: Record<PreviewPayload["type"], MessageKey> = {
  table: "previewTable",
  figure: "previewFigure",
  text: "previewText",
  markdown: "previewMarkdown",
  file: "previewFile",
  value: "previewValue",
};

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function useRemoteText(url: string) {
  const t = useT();
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((r) => r.text())
      .then((txt) => {
        if (!cancelled) setText(txt);
      })
      .catch(() => {
        if (!cancelled) setText(t("cannotReadFile"));
      });
    return () => {
      cancelled = true;
    };
  }, [url, t]);
  return text;
}

function FileText({ url, asMarkdown }: { url: string; asMarkdown?: boolean }) {
  const t = useT();
  const text = useRemoteText(url);
  if (text == null) return <p className="hint">{t("loading")}</p>;
  if (asMarkdown || looksLikeMarkdown(text)) {
    return <MarkdownView source={text} />;
  }
  return <pre className="preview-text">{text}</pre>;
}

function PreviewBody({ preview }: { preview: PreviewPayload }) {
  const t = useT();
  if (preview.type === "table") {
    return (
      <div className="preview-table-wrap">
        <p className="hint">
          {t("tableRowsHint", {
            total: preview.row_count,
            shown: Math.min(50, preview.rows.length),
          })}
        </p>
        <table className="preview-table">
          <thead>
            <tr>
              {preview.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.slice(0, 50).map((row, i) => (
              <tr key={i}>
                {preview.columns.map((c) => (
                  <td key={c}>{String(row[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (preview.type === "figure") {
    return <FigureViewer figure={preview.figure} />;
  }
  if (preview.type === "markdown") {
    return <MarkdownView source={preview.text} />;
  }
  if (preview.type === "text") {
    if (looksLikeMarkdown(preview.text)) {
      return <MarkdownView source={preview.text} />;
    }
    return <pre className="preview-text">{preview.text}</pre>;
  }
  if (preview.type === "file") {
    const isPdf = preview.format === "pdf";
    return (
      <div className="preview-file">
        <div className="preview-file-meta">
          <strong>{preview.name}</strong>
          <span>
            {preview.format.toUpperCase()} · {formatBytes(preview.size)}
          </span>
          <a href={preview.file_url} download={preview.name}>
            {t("download")}
          </a>
        </div>
        {isPdf ? (
          <PdfViewer url={preview.file_url} />
        ) : preview.format === "html" || preview.format === "htm" ? (
          <iframe className="preview-iframe" title={preview.name} src={preview.file_url} />
        ) : preview.format === "md" ? (
          <FileText url={preview.file_url} asMarkdown />
        ) : preview.format === "txt" || preview.format === "csv" ? (
          <FileText url={preview.file_url} />
        ) : (
          <p className="hint">{t("unsupportedPreview", { path: preview.path })}</p>
        )}
      </div>
    );
  }
  return <pre className="preview-text">{JSON.stringify(preview.value, null, 2)}</pre>;
}

export default function OutputPreview({ preview, title, onClose, modal }: Props) {
  const t = useT();
  const heading = title || t(TITLE_KEYS[preview.type]);
  const body = (
    <div className={`output-preview ${modal ? "output-preview-modal" : ""}`}>
      <header className="output-preview-head">
        <h2>{heading}</h2>
        {onClose ? (
          <button type="button" onClick={onClose}>
            {t("close")}
          </button>
        ) : null}
      </header>
      <PreviewBody preview={preview} />
    </div>
  );

  if (!modal) return body;
  return (
    <div className="modal-backdrop preview-backdrop" onClick={onClose}>
      <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
        {body}
      </div>
    </div>
  );
}
