import { memo, isValidElement, useMemo, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import css from "highlight.js/lib/languages/css";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import rehypeWords from "@/lib/rehypeWords";
import rehypeCitations from "@/lib/rehypeCitations";
import type { Source } from "@/hooks/useChat";
import { CodeBlock } from "./CodeBlock";
import { SourcePopover } from "./SourcePopover";

const LANGUAGES = { bash, c, cpp, css, go, java, javascript, json, markdown, python, rust, sql, typescript, xml, yaml };
const ALIASES = { bash: ["sh", "shell", "zsh"], javascript: ["js", "jsx"], typescript: ["ts", "tsx"], python: ["py"], xml: ["html"], yaml: ["yml"] };

const highlight: [typeof rehypeHighlight, any] = [rehypeHighlight, { languages: LANGUAGES, aliases: ALIASES, detect: false }];

function languageOf(children: ReactNode): string | undefined {
  const child = Array.isArray(children) ? children[0] : children;
  if (!isValidElement(child)) return undefined;
  const cls = String((child as ReactElement<{ className?: string }>).props.className ?? "");
  return /language-([\w+-]+)/.exec(cls)?.[1];
}

const baseComponents: Components = {
  pre: ({ children }) => <CodeBlock language={languageOf(children)}>{children}</CodeBlock>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="scrollbar-thin overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
};

/** Assistant replies as GitHub-flavoured markdown. No raw HTML is ever rendered (react-markdown drops it).
 *  Citations like [1] that match a real source become small buttons that show the matched passage. */
const Markdown = memo(function Markdown({ text, streaming, sources = [] }: { text: string; streaming?: boolean; sources?: Source[] }) {
  const byN = useMemo(() => new Map(sources.filter((s) => s.n != null).map((s) => [s.n!, s])), [sources]);
  const components = useMemo<Components>(
    () => ({
      ...baseComponents,
      sup: ({ node: _node, className, children, ...props }) => {
        const n = Number((props as Record<string, unknown>)["data-n"]);
        const source = byN.get(n);
        if (!String(className ?? "").includes("cite") || !source) return <sup className={className}>{children}</sup>;
        return (
          <SourcePopover
            source={source}
            label={`Source ${n}: ${source.document}`}
            className="cite-ref mx-0.5 inline-grid h-[1.15rem] min-w-[1.15rem] -translate-y-1.5 place-items-center rounded-md border border-pink/35 bg-pink/12 px-1 text-[10.5px] font-semibold text-pink transition hover:scale-110 hover:bg-pink/25"
          >
            {n}
          </SourcePopover>
        );
      },
    }),
    [byN],
  );
  const plugins = useMemo(
    () => (streaming ? [rehypeWords] : [[rehypeCitations, { valid: [...byN.keys()] }], highlight]) as any,
    [streaming, byN],
  );
  return (
    <div className="prose-morphie">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={plugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

export default Markdown;
