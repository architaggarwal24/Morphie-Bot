import { AnimatePresence, motion } from "motion/react";
import { Check, CircleCheck, FileJson, FileSpreadsheet, FileText, Info, LoaderCircle, Trash2, TriangleAlert, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent, type RefObject } from "react";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { Tooltip } from "@/components/ui/Tooltip";
import type { Doc, DocumentsApi } from "@/hooks/useDocuments";
import { SKELETON_ROWS } from "@/hooks/useDocuments";
import { spotlight } from "@/hooks/useEffects";
import { cn } from "@/lib/cn";

const TYPE_ICON = { csv: FileSpreadsheet, json: FileJson } as Record<string, typeof FileText>;
const TYPE_HUE: Record<string, string> = { pdf: "var(--danger)", docx: "var(--indigo)", txt: "var(--fg-muted)", csv: "var(--success)", json: "var(--warning)" };

function formatSize(bytes?: number) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

interface RowProps {
  doc: Doc | null; // null = the loading skeleton: the very same elements, painted as soft blocks
  askAll?: boolean;
  checked?: boolean;
  onToggle?: (on: boolean) => void;
  onDelete?: () => void;
}

/** One row builder for both states, so real rows land exactly where the skeleton was. */
export function DocRow({ doc, askAll = true, checked = false, onToggle, onDelete }: RowProps) {
  const skeleton = doc === null;
  const type = doc?.type ?? "txt";
  const Icon = TYPE_ICON[type] ?? FileText;
  const hue = TYPE_HUE[type] ?? "var(--primary)";
  const isOn = askAll || checked;
  const meta = doc ? [type.toUpperCase(), formatSize(doc.size_bytes), doc.chunk_count ? `${doc.chunk_count} chunk${doc.chunk_count === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ") : "PDF · 120 KB";
  const semantic = doc?.search === "semantic";

  return (
    <div
      {...(skeleton ? {} : spotlight)}
      aria-hidden={skeleton || undefined}
      className={cn("mp-list-item spotlight group flex items-center gap-3 rounded-2xl border border-line bg-surface p-2.5 transition-colors hover:border-line-strong", skeleton && "is-skeleton")}
    >
      <label className="mp-list-item__check relative grid h-9 w-9 shrink-0 place-items-center">
        <input
          type="checkbox"
          className="doc-checkbox peer absolute inset-0 z-10 cursor-pointer opacity-0 disabled:cursor-not-allowed"
          checked={isOn}
          disabled={skeleton || askAll}
          tabIndex={skeleton ? -1 : undefined}
          aria-label={doc ? `Ask about ${doc.name}` : undefined}
          onChange={(e) => onToggle?.(e.target.checked)}
        />
        <span
          aria-hidden="true"
          className={cn(
            "grid h-5 w-5 place-items-center rounded-md border transition-all duration-200 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring",
            isOn ? "border-primary bg-[linear-gradient(135deg,var(--primary),var(--indigo))] text-white" : "border-line-strong bg-surface-2",
            askAll && "opacity-60",
          )}
        >
          <AnimatePresence>
            {isOn && (
              <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }} transition={{ type: "spring", stiffness: 600, damping: 25 }}>
                <Check size={12} strokeWidth={3} />
              </motion.span>
            )}
          </AnimatePresence>
        </span>
      </label>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border" style={{ color: hue, borderColor: `color-mix(in srgb, ${hue} 30%, transparent)`, background: `color-mix(in srgb, ${hue} 12%, transparent)` }}>
        <Icon size={16} aria-hidden="true" />
      </span>
      <div className="mp-list-item__body min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <div className="mp-list-item__title skeleton-block min-w-0 truncate text-[13.5px] font-medium text-fg" title={doc?.name}>
            {doc ? doc.name : "Loading document name"}
          </div>
          {doc && (
            <span
              title={semantic ? "Searchable by meaning and by keywords" : "Searchable by keywords (add an OpenAI, Mistral or Ollama key before uploading for meaning-based search)"}
              className={cn(
                "search-badge shrink-0 rounded-full border px-1.5 py-px text-[9.5px] font-semibold tracking-wide uppercase",
                semantic ? "border-cyan/35 bg-cyan/10 text-cyan" : "border-line-strong text-subtle",
              )}
            >
              {semantic ? "Semantic" : "Keyword"}
            </span>
          )}
        </div>
        <div className="skeleton-block mt-0.5 w-fit text-[11.5px] text-subtle">{meta}</div>
      </div>
      <Tooltip label="Delete" side="left">
        <button
          type="button"
          disabled={skeleton}
          tabIndex={skeleton ? -1 : undefined}
          onClick={onDelete}
          aria-label={doc ? `Delete ${doc.name}` : "Delete"}
          className="grid h-9 w-9 place-items-center rounded-xl text-subtle opacity-70 transition hover:bg-danger-soft hover:text-danger group-hover:opacity-100"
        >
          <Trash2 size={15} aria-hidden="true" />
        </button>
      </Tooltip>
    </div>
  );
}

const STATUS_ICON = { busy: LoaderCircle, ok: CircleCheck, info: Info, error: TriangleAlert };

interface PanelProps {
  docs: DocumentsApi;
  onClose: () => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
}

export function DocumentsPanel({ docs, onClose, fileInputRef }: PanelProps) {
  const [dragOver, setDragOver] = useState(false);
  const depth = useRef(0);

  function onDrag(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (e.type === "dragenter") depth.current++;
    if (e.type === "dragleave") depth.current = Math.max(0, depth.current - 1);
    if (e.type === "drop") {
      depth.current = 0;
      const files = Array.from(e.dataTransfer.files);
      if (files.length) docs.uploadFiles(files);
    }
    setDragOver(e.type !== "drop" && depth.current > 0);
  }

  const status = docs.uploadState;
  const StatusIcon = status ? STATUS_ICON[status.tone] : null;

  return (
    <section id="docsPanel" className="mp-panel-block is-active flex h-full flex-col" aria-labelledby="docsTitle">
      <div className="mp-panel-head flex items-center gap-2 px-5 pt-5 pb-3">
        <span className="grid h-8 w-8 place-items-center rounded-xl bg-pink/15 text-pink">
          <FileText size={16} aria-hidden="true" />
        </span>
        <h2 id="docsTitle" className="text-[15px] font-semibold text-fg">
          Documents
        </h2>
        <span className="flex-1" />
        <button type="button" onClick={onClose} aria-label="Close" className="mp-panel-close grid h-9 w-9 place-items-center rounded-xl text-muted transition hover:rotate-90 hover:bg-surface-2 hover:text-fg">
          <X size={17} aria-hidden="true" />
        </button>
      </div>

      <div className="mp-panel-body scrollbar-thin flex-1 overflow-y-auto px-5 pb-5">
        <motion.div
          id="dropzone"
          role="button"
          tabIndex={0}
          aria-label="Drop files here, or click to upload"
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          onDragEnter={onDrag}
          onDragOver={onDrag}
          onDragLeave={onDrag}
          onDrop={onDrag}
          animate={{ scale: dragOver ? 1.02 : 1 }}
          transition={{ type: "spring", stiffness: 400, damping: 25 }}
          className={cn(
            "mp-dropzone relative flex flex-col items-center gap-2 overflow-hidden rounded-2xl px-4 py-7 text-center transition-colors",
            dragOver ? "is-dragover bg-primary-soft" : "bg-surface hover:bg-surface-2",
            docs.uploading && "is-busy",
          )}
        >
          {/* animated dashed outline */}
          <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full">
            <rect
              x="1"
              y="1"
              style={{ width: "calc(100% - 2px)", height: "calc(100% - 2px)" }}
              rx="15"
              fill="none"
              stroke={dragOver ? "var(--primary)" : "var(--line-strong)"}
              strokeWidth="1.5"
              strokeDasharray="7 6"
              className={cn(dragOver || docs.uploading ? "animate-[dash_0.9s_linear_infinite]" : "")}
            />
          </svg>
          <motion.span
            animate={dragOver ? { y: -4, scale: 1.1 } : docs.uploading ? { y: [0, -4, 0] } : { y: 0, scale: 1 }}
            transition={docs.uploading ? { repeat: Infinity, duration: 1.2 } : { type: "spring", stiffness: 400, damping: 18 }}
            className="grid h-12 w-12 place-items-center rounded-2xl bg-[linear-gradient(135deg,var(--primary),var(--indigo))] text-white shadow-glow"
          >
            <UploadCloud size={22} aria-hidden="true" />
          </motion.span>
          <strong className="mt-1 text-[14px] font-semibold text-fg">{dragOver ? "Drop to upload" : "Drop files here, or click to upload"}</strong>
          <span className="text-[12px] text-subtle">PDF, DOCX, TXT, CSV, JSON · up to 10 at once</span>
        </motion.div>
        <input
          type="file"
          id="fileInput"
          ref={fileInputRef}
          accept=".pdf,.txt,.docx,.csv,.json"
          multiple
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) docs.uploadFiles(files);
          }}
        />
        <Button id="uploadBtn" variant="primary" block className="mt-3" onClick={() => fileInputRef.current?.click()}>
          {docs.uploading ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <UploadCloud size={16} aria-hidden="true" />}
          {docs.uploading ? "Uploading… add more" : "Upload files"}
        </Button>

        <AnimatePresence initial={false}>
          {docs.uploads.length > 0 && (
            <motion.ul
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 space-y-1.5 overflow-hidden"
              aria-label="Uploads"
            >
              <AnimatePresence initial={false}>
                {docs.uploads.map((u) => (
                  <motion.li
                    key={u.key}
                    layout
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: 30, transition: { duration: 0.2 } }}
                    className="upload-row rounded-xl border border-line bg-surface px-3 py-2"
                  >
                    <div className="flex items-center gap-2 text-[12.5px]">
                      {u.status === "error" ? (
                        <TriangleAlert size={13} className="shrink-0 text-danger" aria-hidden="true" />
                      ) : u.status === "done" || u.status === "duplicate" ? (
                        <CircleCheck size={13} className="shrink-0 text-success" aria-hidden="true" />
                      ) : (
                        <LoaderCircle size={13} className={cn("shrink-0 text-primary", u.status !== "queued" && "animate-spin")} aria-hidden="true" />
                      )}
                      <span className="min-w-0 flex-1 truncate text-fg">{u.name}</span>
                      <span className={cn("shrink-0 text-[11.5px]", u.status === "error" ? "text-danger" : "text-subtle")}>
                        {u.status === "queued" ? "Waiting" : u.status === "uploading" ? `${Math.round(u.progress * 100)}%` : u.status === "indexing" ? "Indexing…" : u.status === "duplicate" ? "Already there" : u.status === "done" ? "Ready" : "Failed"}
                      </span>
                      {u.status === "error" && (
                        <button type="button" aria-label={`Dismiss ${u.name}`} onClick={() => docs.dismissUpload(u.key)} className="grid h-6 w-6 place-items-center rounded-md text-subtle hover:bg-surface-2 hover:text-fg">
                          <X size={12} aria-hidden="true" />
                        </button>
                      )}
                    </div>
                    {u.status !== "error" && u.status !== "duplicate" && (
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label={`Uploading ${u.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(u.progress * 100)}>
                        <motion.div
                          className={cn("h-full rounded-full bg-[linear-gradient(90deg,var(--cyan),var(--primary))]", u.status === "indexing" && "animate-pulse")}
                          animate={{ width: `${Math.max(4, u.progress * 100)}%` }}
                          transition={{ type: "spring", stiffness: 120, damping: 20 }}
                        />
                      </div>
                    )}
                    {u.status === "error" && u.message && <p className="mt-1 text-[11.5px] text-danger">{u.message}</p>}
                    {u.status === "done" && u.message && <p className="mt-1 text-[11.5px] text-subtle">{u.message}</p>}
                  </motion.li>
                ))}
              </AnimatePresence>
            </motion.ul>
          )}
        </AnimatePresence>

        <div id="uploadStatus" role="status" className="mp-status-line mt-2 min-h-5 text-[12.5px]">
          <AnimatePresence mode="wait">
            {status && StatusIcon && (
              <motion.span
                key={status.text}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className={cn(
                  "flex items-center gap-1.5",
                  status.tone === "error" ? "text-danger" : status.tone === "ok" ? "text-success" : "text-muted",
                )}
              >
                <StatusIcon size={13} className={status.tone === "busy" ? "animate-spin" : ""} aria-hidden="true" />
                {status.text}
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="mt-3 rounded-2xl border border-line bg-surface px-3 py-0.5">
          <Switch id="allDocsToggle" label="Ask about all documents" checked={docs.askAll} onChange={docs.setAskAll} />
        </div>

        <div className="mp-section-title mt-6 mb-2.5 flex items-center justify-between text-[11px] font-semibold tracking-[0.14em] text-subtle uppercase">
          Your documents
          {docs.allDocuments.length > 0 && <span className="tracking-normal normal-case">{docs.allDocuments.length}</span>}
        </div>

        <div id="docsList" aria-busy={!docs.loaded || undefined} className="flex flex-col gap-2">
          {docs.skeleton && !docs.loaded ? (
            Array.from({ length: SKELETON_ROWS }, (_, i) => <DocRow key={`s${i}`} doc={null} />)
          ) : docs.failed && !docs.loaded ? (
            <div className="mp-list-empty rounded-2xl border border-danger/25 bg-danger-soft p-4 text-center text-[13px] text-fg">Could not load documents.</div>
          ) : docs.loaded && docs.allDocuments.length === 0 ? (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mp-list-empty rounded-2xl border border-dashed border-line-strong p-6 text-center text-[13px] text-muted">
              No documents uploaded yet.
            </motion.div>
          ) : (
            <AnimatePresence initial={false} mode="popLayout">
              {docs.allDocuments.map((d) => (
                <motion.div
                  key={d.id}
                  layout
                  initial={{ opacity: 0, y: -8, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, x: 40, scale: 0.95, transition: { duration: 0.2 } }}
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                >
                  <DocRow doc={d} askAll={docs.askAll} checked={docs.selected.has(d.id)} onToggle={(on) => docs.toggleSelected(d.id, on)} onDelete={() => docs.deleteDocument(d.id)} />
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>
      </div>
    </section>
  );
}
