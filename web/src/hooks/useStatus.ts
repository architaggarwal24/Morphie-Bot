import { useCallback, useRef, useState } from "react";
import { callApi } from "@/lib/api";
import { clearLlm, withLlmHeaders } from "@/lib/llm";
import type { StatusInfo } from "@/components/layout/Sidebar";

interface Options {
  onNeedsKey: () => void;
  onError: (message: string) => void;
}

/** The sidebar badge: what will answer (GET /status, with the saved choice). */
export function useStatus({ onNeedsKey, onError }: Options) {
  const [status, setStatus] = useState<StatusInfo>({ label: "…", configured: true, offline: false, tip: "Choose your model and API key" });
  const lastFetch = useRef(0);

  const loadStatus = useCallback(
    async (autoOpen = false) => {
      lastFetch.current = Date.now();
      const result = await callApi("/status", { headers: withLlmHeaders({}) });
      if (!result.ok || !result.data) {
        setStatus({ label: "Offline", configured: false, offline: true, tip: "Morphie can't be reached right now" });
        if (result.status === 400 && result.message) {
          clearLlm(); // e.g. a saved choice the server no longer accepts
          onError(result.message);
        }
        return;
      }
      const info = result.data;
      if (info.configured) {
        setStatus({ label: `${info.provider} · ${info.model}`, configured: true, offline: false, tip: "Change your model or API key" });
      } else {
        setStatus({ label: "Add your API key", configured: false, offline: false, tip: `${info.provider} needs an API key. Click to add yours.` });
        if (autoOpen) onNeedsKey();
      }
    },
    [onNeedsKey, onError],
  );

  return { status, loadStatus, lastStatusFetch: lastFetch };
}
