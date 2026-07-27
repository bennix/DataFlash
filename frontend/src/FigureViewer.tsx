import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";

type Props = {
  figure: { data: unknown[]; layout?: Record<string, unknown>; config?: Record<string, unknown> };
};

/** Interactive Plotly figure with scroll-zoom and pan. */
export default function FigureViewer({ figure }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !figure?.data) return;
    const layout = {
      ...(figure.layout || {}),
      autosize: true,
      margin: { t: 40, r: 20, b: 40, l: 50, ...(figure.layout?.margin as object) },
      paper_bgcolor: "transparent",
      plot_bgcolor: "#fffdf8",
    };
    const config = {
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      modeBarButtonsToRemove: ["sendDataToCloud", "lasso2d", "select2d"],
      ...(figure.config || {}),
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Plotly.react(el, figure.data as any, layout as any, config as any);
    const onResize = () => {
      Plotly.Plots.resize(el);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      Plotly.purge(el);
    };
  }, [figure]);

  return <div className="figure-viewer" ref={ref} />;
}
