import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  source: string;
  className?: string;
};

/** Allow report-embedded data URIs; keep default safety for other protocols. */
function urlTransform(url: string) {
  if (url.startsWith("data:image/")) return url;
  return defaultUrlTransform(url);
}

/** Render report markdown including GFM tables and data-URI images. */
export default function MarkdownView({ source, className }: Props) {
  return (
    <div className={`markdown-body ${className || ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          img: ({ src, alt, ...rest }) => (
            <img
              {...rest}
              src={src}
              alt={alt || "图表"}
              className="markdown-img"
              loading="lazy"
            />
          ),
          a: ({ href, children, ...rest }) => (
            <a {...rest} href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

export function looksLikeMarkdown(text: string): boolean {
  const sample = text.slice(0, 2000);
  return (
    /^#{1,6}\s/m.test(sample) ||
    /^\s*[-*+]\s/m.test(sample) ||
    /^\|.+\|/m.test(sample) ||
    /!\[[^\]]*]\([^)]+\)/.test(sample) ||
    /```/.test(sample) ||
    /^>\s/m.test(sample)
  );
}
