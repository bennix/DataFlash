import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import pdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorker;

type Props = {
  url: string;
};

/** PDF viewer with page nav, wheel zoom, and drag pan. */
export default function PdfViewer({ url }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [scale, setScale] = useState(1.1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [error, setError] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDoc(null);
    setPage(1);
    setOffset({ x: 0, y: 0 });
    setError(null);
    pdfjs
      .getDocument({ url })
      .promise.then((pdf) => {
        if (cancelled) return;
        setDoc(pdf);
        setPageCount(pdf.numPages);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  useEffect(() => {
    if (!doc || !canvasRef.current) return;
    let cancelled = false;
    (async () => {
      const pg = await doc.getPage(page);
      if (cancelled || !canvasRef.current) return;
      const viewport = pg.getViewport({ scale });
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await pg.render({ canvasContext: ctx, viewport, canvas }).promise;
    })().catch((e) => {
      if (!cancelled) setError(String(e?.message || e));
    });
    return () => {
      cancelled = true;
    };
  }, [doc, page, scale]);

  const onWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey) {
      e.preventDefault();
      setScale((s) => Math.min(3.5, Math.max(0.4, s - e.deltaY * 0.0015)));
    }
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    setOffset({
      x: drag.current.ox + (e.clientX - drag.current.x),
      y: drag.current.oy + (e.clientY - drag.current.y),
    });
  };

  const onPointerUp = () => {
    drag.current = null;
  };

  return (
    <div className="pdf-viewer">
      <div className="pdf-toolbar">
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
          上一页
        </button>
        <span className="pdf-page">
          {page} / {pageCount || "—"}
        </span>
        <button
          type="button"
          disabled={!pageCount || page >= pageCount}
          onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
        >
          下一页
        </button>
        <span className="pdf-sep" />
        <button type="button" onClick={() => setScale((s) => Math.max(0.4, s - 0.15))}>
          −
        </button>
        <span className="pdf-zoom">{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => setScale((s) => Math.min(3.5, s + 0.15))}>
          +
        </button>
        <button
          type="button"
          onClick={() => {
            setScale(1.1);
            setOffset({ x: 0, y: 0 });
          }}
        >
          重置
        </button>
        <a className="pdf-open" href={url} target="_blank" rel="noreferrer">
          新窗口打开
        </a>
      </div>
      {error ? (
        <p className="hint">无法渲染 PDF：{error}</p>
      ) : (
        <div
          className="pdf-viewport"
          ref={viewportRef}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div
            className="pdf-stage"
            style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
          >
            <canvas ref={canvasRef} />
          </div>
        </div>
      )}
      <p className="hint pdf-hint">拖拽平移 · ⌘/Ctrl+滚轮缩放 · 工具栏翻页</p>
    </div>
  );
}
