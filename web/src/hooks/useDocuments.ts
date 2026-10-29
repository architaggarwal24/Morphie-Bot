import { useCallback, useEffect, useRef, useState } from "react";
import { callApi, uploadWithProgress } from "@/lib/api";
import { withLlmHeaders } from "@/lib/llm";
import { UNDO_MS, type ToastHandle, type ToastOptions } from "@/components/ui/Toast";

export interface Doc {
  id: string;
  name: string;
  type: string;
  size_bytes?: number;
  chunk_count?: number;
  created_at?: string | number;
  /** "semantic" = also searchable by meaning; "keyword" = shared words only */
  search?: "semantic" | "keyword";
}

export type UploadState = { tone: "busy" | "ok" | "info" | "error"; text: string } | null;

export interface UploadItem {
  key: string;
  name: string;
  progress: number; // 0..1 of the bytes sent; indexing happens after
  status: "queued" | "uploading" | "indexing" | "done" | "duplicate" | "error";
  message?: string;
}

export const MAX_FILES_PER_DROP = 10;

export const SKELETON_DELAY_MS = 300; // loads faster than this never flash a placeholder
export const SKELETON_ROWS = 3;

type ShowToast = (message: string, options?: ToastOptions) => ToastHandle;

/**
 * The person's documents. Stale-while-revalidate: whatever list we already have stays on screen while a request
 * refreshes it. Deletes are optimistic with an Undo window; uploads are never optimistic.
 */
export function useDocuments(showToast: ShowToast) {
  const [allDocuments, setAllDocuments] = useState<Doc[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [skeleton, setSkeleton] = useState(false);
  const [failed, setFailed] = useState(false);
  const [askAll, setAskAll] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>(null);

  // Mirrors of state for code that runs outside a render (chat send, timers, pagehide).
  const docsRef = useRef<Doc[]>([]);
  const selectedRef = useRef<Set<string>>(new Set());
  const askAllRef = useRef(true);
  const loadedRef = useRef(false);
  const requestId = useRef(0);
  const lastFetch = useRef(0);
  const pendingDeleteIds = useRef(new Set<string>()); // gone from the screen, DELETE not finished
  const pendingDeletes = useRef(new Map<string, () => Promise<void>>()); // id -> send its DELETE right now

  const commitDocs = useCallback((next: Doc[]) => {
    docsRef.current = next;
    setAllDocuments(next);
  }, []);
  const commitSelected = useCallback((next: Set<string>) => {
    selectedRef.current = next;
    setSelected(next);
  }, []);

  const loadDocuments = useCallback(async () => {
    const id = ++requestId.current;
    lastFetch.current = Date.now();
    // Gray rows in the shape of the real ones, but only if the answer is slow (and there is nothing to show yet).
    const skeletonTimer = loadedRef.current ? null : window.setTimeout(() => setSkeleton(true), SKELETON_DELAY_MS);
    const result = await callApi<{ documents: Doc[] }>("/documents");
    if (skeletonTimer) window.clearTimeout(skeletonTimer);
    if (id !== requestId.current) return; // a newer request owns the screen now
    setSkeleton(false);
    if (!result.ok || !result.data) {
      if (!loadedRef.current) setFailed(true);
      return; // a failed background refresh keeps showing the cached list
    }
    const known = new Set(docsRef.current.map((d) => d.id));
    const next = (result.data.documents || []).filter((d) => !pendingDeleteIds.current.has(d.id));
    const current = new Set(next.map((d) => d.id));
    const keep = new Set([...selectedRef.current].filter((x) => current.has(x)));
    // Only documents we hadn't seen yet start ticked, so a refresh never undoes someone's own choices.
    next.forEach((d) => {
      if (!known.has(d.id)) keep.add(d.id);
    });
    loadedRef.current = true;
    setLoaded(true);
    setFailed(false);
    commitDocs(next);
    commitSelected(keep);
  }, [commitDocs, commitSelected]);

  /** null = ask about every document. While a delete is pending, name the ones that stay instead of "all". */
  const getSelectedDocumentIds = useCallback((): string[] | null => {
    if (pendingDeleteIds.current.size) {
      const keep = askAllRef.current ? docsRef.current.map((d) => d.id) : [...selectedRef.current];
      return keep.filter((id) => !pendingDeleteIds.current.has(id));
    }
    if (askAllRef.current) return null;
    return [...selectedRef.current];
  }, []);

  const setAskAllDocs = useCallback((value: boolean) => {
    askAllRef.current = value;
    setAskAll(value);
  }, []);

  const toggleSelected = useCallback(
    (id: string, on: boolean) => {
      const next = new Set(selectedRef.current);
      if (on) next.add(id);
      else next.delete(id);
      commitSelected(next);
    },
    [commitSelected],
  );

  // No confirm dialog. The row leaves the list at once (optimistic) and an Undo toast opens; the DELETE is only
  // sent when the toast runs out, so Undo is a pure client-side step. If the server then refuses, the row returns.
  const deleteDocument = useCallback(
    (id: string) => {
      const list = [...docsRef.current];
      let index = list.findIndex((d) => d.id === id);
      if (index === -1) return;
      const doc = list.splice(index, 1)[0];
      pendingDeleteIds.current.add(id);
      commitDocs(list);

      let timer = 0;
      let toast: ToastHandle | null = null;

      const putBack = () => {
        const now = [...docsRef.current];
        index = Math.min(index, now.length);
        now.splice(index, 0, doc);
        commitDocs(now);
      };

      const undo = () => {
        window.clearTimeout(timer);
        pendingDeletes.current.delete(id);
        pendingDeleteIds.current.delete(id);
        putBack();
      };

      const send = async () => {
        pendingDeletes.current.delete(id);
        // keepalive lets the request finish even if the tab is closing
        const result = await callApi(`/documents/${encodeURIComponent(id)}`, { method: "DELETE", keepalive: true });
        pendingDeleteIds.current.delete(id);
        if (!result.ok && result.status !== 404) {
          putBack();
          showToast(`Couldn't delete ${doc.name}. ${result.message ?? ""}`, { tone: "error" });
        }
      };

      pendingDeletes.current.set(id, () => {
        window.clearTimeout(timer);
        toast?.dismiss();
        return send();
      });
      timer = window.setTimeout(send, UNDO_MS);
      toast = showToast(`Deleted ${doc.name}`, { duration: UNDO_MS, action: { label: "Undo", onClick: undo } });
    },
    [commitDocs, showToast],
  );

  /** Send every delete still waiting out its Undo window (before an upload, or when the page goes away). */
  const flushPendingDeletes = useCallback(() => Promise.all([...pendingDeletes.current.values()].map((fn) => fn())), []);

  useEffect(() => {
    const onHide = () => {
      flushPendingDeletes();
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [flushPendingDeletes]);

  // Several files at once: they go one after another (the server indexes one at a time anyway), each with its own
  // progress bar. Uploads are never optimistic - a row appears in the list only once the server has indexed it.
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const queue = useRef<{ key: string; file: File }[]>([]);
  const running = useRef(false);
  const keySeq = useRef(0);

  const setItem = useCallback((key: string, patch: Partial<UploadItem>) => {
    setUploads((list) => list.map((u) => (u.key === key ? { ...u, ...patch } : u)));
  }, []);

  const pump = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setUploading(true);
    try {
      await flushPendingDeletes(); // a document deleted a moment ago must be gone before the same file returns
      let next: { key: string; file: File } | undefined;
      while ((next = queue.current.shift())) {
        const { key, file } = next;
        setItem(key, { status: "uploading" });
        setUploadState({ tone: "busy", text: `Uploading ${file.name}…` });
        const form = new FormData();
        form.append("file", file);
        const result = await uploadWithProgress("/documents/upload", form, withLlmHeaders({}), (f) => {
          setItem(key, { progress: f, status: f >= 1 ? "indexing" : "uploading" });
        });
        if (!result.ok || !result.data) {
          const message = result.message ?? "Upload failed.";
          setItem(key, { status: "error", message, progress: 1 });
          setUploadState({ tone: "error", text: `${file.name}: ${message}` });
          continue;
        }
        const name = result.data.document.name;
        if (result.data.duplicate) {
          setItem(key, { status: "duplicate", progress: 1, message: "Already uploaded" });
          setUploadState({ tone: "info", text: `${name} was already uploaded.` });
        } else {
          setItem(key, { status: "done", progress: 1, message: result.data.notice });
          setUploadState(result.data.notice ? { tone: "info", text: `${name}: ${result.data.notice}` } : { tone: "ok", text: `${name} uploaded.` });
        }
        await loadDocuments();
      }
    } finally {
      running.current = false;
      setUploading(false);
      // finished rows fade away after a moment; failures stay until dismissed
      window.setTimeout(() => setUploads((list) => list.filter((u) => u.status === "error" || u.status === "queued" || u.status === "uploading" || u.status === "indexing")), 2600);
    }
  }, [flushPendingDeletes, loadDocuments, setItem]);

  const uploadFiles = useCallback(
    (files: File[]) => {
      const picked = files.slice(0, MAX_FILES_PER_DROP);
      if (files.length > MAX_FILES_PER_DROP) showToast(`Up to ${MAX_FILES_PER_DROP} files at a time - the first ${MAX_FILES_PER_DROP} are on their way.`);
      const items = picked.map((file) => ({ key: `u${++keySeq.current}`, file }));
      queue.current.push(...items);
      setUploads((list) => [...list, ...items.map(({ key, file }) => ({ key, name: file.name, progress: 0, status: "queued" as const }))]);
      pump();
      if (picked.length > 1) showToast(`Uploading ${picked.length} files…`);
    },
    [pump, showToast],
  );

  const uploadFile = useCallback((file: File) => uploadFiles([file]), [uploadFiles]);

  const dismissUpload = useCallback((key: string) => setUploads((list) => list.filter((u) => u.key !== key)), []);

  return {
    allDocuments,
    loaded,
    skeleton,
    failed,
    askAll,
    setAskAll: setAskAllDocs,
    selected,
    toggleSelected,
    uploading,
    uploadState,
    uploads,
    uploadFiles,
    dismissUpload,
    loadDocuments,
    getSelectedDocumentIds,
    deleteDocument,
    uploadFile,
    lastDocsFetch: lastFetch,
  };
}

export type DocumentsApi = ReturnType<typeof useDocuments>;
