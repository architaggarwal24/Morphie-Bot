import { motion, useAnimate } from "motion/react";
import { Brain, Globe, KeyRound, Link2, Lock, Settings2, ShieldCheck, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Switch } from "@/components/ui/Switch";
import { callApi } from "@/lib/api";
import { cn } from "@/lib/cn";
import { BASE_URL_PATTERN, KEY_PATTERN, MODEL_PATTERN, clearLlm, isRemembered, loadLlm, saveLlm, type LlmChoice } from "@/lib/llm";
import { followupsEnabled, setFollowupsEnabled } from "@/lib/prefs";

export interface ProviderInfo {
  id: string;
  name: string;
  default_model: string;
  models: string[];
  requires_key: boolean;
  group?: "native" | "compatible" | "custom";
  semantic_search?: boolean;
  needs_base_url?: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** After a save or removal: refresh the badge, and tell the person. */
  onSaved: (message: string) => void;
  onRemoved: (previous: LlmChoice | null, wasRemembered: boolean) => void;
}

let providerCache: ProviderInfo[] = [];
let followupsServerOn = true;

const fieldClass =
  "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] text-fg placeholder:text-subtle transition focus:border-primary/60 focus:bg-surface-2 focus:shadow-[0_0_0_4px_var(--primary-soft)] focus:outline-none";

export function SettingsModal({ open, onClose, onSaved, onRemoved }: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>(providerCache);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [remember, setRemember] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [followups, setFollowups] = useState(followupsEnabled());
  const [error, setError] = useState("");
  const [formScope, animateForm] = useAnimate<HTMLFormElement>();
  const keyRef = useRef<HTMLInputElement>(null);
  const modelRef = useRef<HTMLInputElement>(null);

  // Every time it opens: fill from what is saved - except the key, which is never put back into the page.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      let list = providerCache;
      if (!list.length) {
        const result = await callApi<{ providers: ProviderInfo[]; features?: { followups?: boolean } }>("/providers");
        list = (result.ok && result.data?.providers) || [];
        providerCache = list;
        followupsServerOn = result.data?.features?.followups !== false;
      }
      if (cancelled) return;
      setProviders(list);
      const saved = loadLlm();
      const initial = saved && list.some((p) => p.id === saved.provider) ? saved.provider : list[0]?.id ?? "";
      setProvider(initial);
      setModel(saved?.model ?? "");
      setBaseUrl(saved?.baseUrl ?? "");
      setFollowups(followupsEnabled());
      setKey(""); // the saved key is never put back into the page
      setRemember(saved ? isRemembered() : true);
      setError("");
      const info = list.find((p) => p.id === initial);
      requestAnimationFrame(() => (info?.requires_key ? keyRef.current : modelRef.current)?.focus());
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const info = providers.find((p) => p.id === provider) ?? null;
  const saved = open ? loadLlm() : null;
  const hasSavedKey = !!(saved && info && saved.provider === info.id && saved.key);

  function fail(message: string) {
    setError(message);
    if (formScope.current) animateForm(formScope.current, { x: [0, -8, 8, -5, 5, 0] }, { duration: 0.4 });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!info) return fail("Choose a provider.");
    const m = model.trim();
    if (m && !MODEL_PATTERN.test(m)) return fail("That model name has characters a model id never contains.");
    const url = baseUrl.trim().replace(/\/+$/, "");
    if (info.needs_base_url && !BASE_URL_PATTERN.test(url)) return fail("Enter the server's URL, like http://localhost:1234/v1.");
    let k = key.trim();
    const current = loadLlm();
    if (!k && current && current.provider === info.id && current.key) k = current.key; // keep the saved key
    if (info.requires_key) {
      if (!k) return fail(`Paste your ${info.name} API key.`);
      if (!KEY_PATTERN.test(k)) return fail("That doesn't look like an API key (no spaces, 8+ characters).");
    }
    if (info.needs_base_url && k && !KEY_PATTERN.test(k)) return fail("That doesn't look like an API key (no spaces, 8+ characters).");
    const keepKey = info.requires_key || info.needs_base_url;
    saveLlm({ provider: info.id, model: m, key: keepKey ? k : "", ...(info.needs_base_url ? { baseUrl: url } : {}) }, remember);
    setFollowupsEnabled(followups);
    setKey("");
    onClose();
    onSaved(`Saved. Morphie will use ${info.name}${m ? " · " + m : ""}.`);
  }

  function removeKey() {
    const previous = loadLlm(); // kept in memory only for the length of the Undo toast
    const wasRemembered = isRemembered();
    clearLlm();
    setKey("");
    onClose();
    onRemoved(previous, wasRemembered);
  }

  return (
    <Modal open={open} onClose={onClose} id="settingsModal" labelledBy="settingsTitle" className="mp-modal__card scrollbar-thin max-h-[calc(100dvh-2rem)] max-w-lg overflow-y-auto">
      <div className="mp-panel-head flex items-center gap-3 px-6 pt-6">
        <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[linear-gradient(135deg,var(--primary),var(--indigo))] text-white shadow-glow">
          <Settings2 size={18} aria-hidden="true" />
        </span>
        <div>
          <h2 id="settingsTitle" className="text-[17px] font-semibold text-fg">
            Model &amp; API key
          </h2>
          <p className="text-[12.5px] text-muted">Bring your own key. Pick who answers.</p>
        </div>
        <span className="flex-1" />
        <button id="settingsCloseBtn" type="button" onClick={onClose} aria-label="Close" className="mp-panel-close grid h-9 w-9 place-items-center rounded-xl text-muted transition hover:rotate-90 hover:bg-surface-2 hover:text-fg">
          <X size={17} aria-hidden="true" />
        </button>
      </div>

      <form
        id="settingsForm"
        ref={formScope}
        onSubmit={submit}
        className="mp-modal__body flex flex-col gap-4 px-6 pt-5 pb-6"
        autoComplete="off"
        noValidate
      >
        <p className="mp-modal__note flex gap-2.5 rounded-2xl border border-cyan/25 bg-cyan/[0.07] p-3 text-[12.5px] leading-relaxed text-muted">
          <ShieldCheck size={16} className="mt-0.5 shrink-0 text-cyan" aria-hidden="true" />
          <span>
            Morphie-Bot uses <strong className="text-fg">your own</strong> API key. It stays in this browser and is sent with each message so the model can answer; the server never stores or logs it.
          </span>
        </p>

        <fieldset>
          <legend className="mb-2 text-[13px] font-medium text-fg">Provider</legend>
          <div id="llmProvider" role="radiogroup" aria-label="Provider" className="grid grid-cols-3 gap-2">
            {providers.map((p) => {
              const active = p.id === provider;
              const compact = p.group && p.group !== "native";
              return (
                <label
                  key={p.id}
                  className={cn(
                    "relative flex cursor-pointer items-center rounded-2xl border text-center transition-colors",
                    compact ? "gap-2 px-2.5 py-2 text-left" : "flex-col gap-1.5 px-2 py-3",
                    active ? "border-primary/60 text-fg" : "border-line bg-surface text-muted hover:border-line-strong hover:text-fg",
                  )}
                >
                  <input type="radio" name="llmProvider" value={p.id} checked={active} onChange={() => setProvider(p.id)} className="peer sr-only" />
                  {active && (
                    <motion.span
                      layoutId="provider-active"
                      className="absolute inset-0 rounded-2xl bg-primary-soft shadow-[inset_0_0_0_1px_rgb(139_92_246/0.4)]"
                      transition={{ type: "spring", stiffness: 500, damping: 35 }}
                    />
                  )}
                  <span className="absolute inset-0 rounded-2xl peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring" aria-hidden="true" />
                  <span
                    className={cn(
                      "relative grid shrink-0 place-items-center rounded-xl font-bold",
                      compact ? "h-6 w-6 text-[11px]" : "h-8 w-8 text-[13px]",
                      active ? "bg-[linear-gradient(135deg,var(--primary),var(--indigo))] text-white" : "bg-surface-2",
                    )}
                  >
                    {p.group === "custom" ? <Link2 size={12} aria-hidden="true" /> : p.name.slice(0, 1)}
                  </span>
                  <span className={cn("relative font-medium", compact ? "min-w-0 truncate text-[12px]" : "text-[12.5px]")}>{p.name}</span>
                  {!compact && (
                    <span className="relative flex items-center gap-1 text-[10.5px] text-subtle">
                      {p.semantic_search && <Brain size={10} className="text-cyan" aria-label="Meaning-based document search" />}
                      {!p.requires_key ? "no key" : p.semantic_search ? "semantic" : ""}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          {info && (
            <p className="mt-2 flex items-center gap-1.5 text-[12px] text-subtle">
              {info.semantic_search ? (
                <>
                  <Brain size={12} className="text-cyan" aria-hidden="true" /> Documents you upload with this provider are searchable by meaning, not just keywords.
                </>
              ) : info.group === "compatible" ? (
                <>
                  <Globe size={12} aria-hidden="true" /> OpenAI-compatible endpoint. Documents use keyword search.
                </>
              ) : info.group === "custom" ? (
                <>
                  <Link2 size={12} aria-hidden="true" /> Any OpenAI-compatible server: LM Studio, vLLM, llama.cpp, a gateway.
                </>
              ) : null}
            </p>
          )}
        </fieldset>

        {info?.needs_base_url && (
          <label className="mp-field flex flex-col gap-1.5 text-[13px] font-medium text-fg" htmlFor="llmBaseUrl">
            Server URL
            <input
              id="llmBaseUrl"
              type="url"
              inputMode="url"
              maxLength={200}
              spellCheck={false}
              autoComplete="off"
              value={baseUrl}
              placeholder="http://localhost:1234/v1"
              onChange={(e) => setBaseUrl(e.target.value)}
              className={cn(fieldClass, "font-mono")}
            />
          </label>
        )}

        <label className="mp-field flex flex-col gap-1.5 text-[13px] font-medium text-fg" htmlFor="llmModel">
          <span>
            Model <span className="mp-field__hint font-normal text-subtle">(optional)</span>
          </span>
          <input
            id="llmModel"
            ref={modelRef}
            type="text"
            list="llmModelList"
            maxLength={80}
            spellCheck={false}
            autoComplete="off"
            value={model}
            placeholder={info?.default_model ?? ""}
            onChange={(e) => setModel(e.target.value)}
            className={fieldClass}
          />
          <datalist id="llmModelList">
            {(info?.models ?? []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>

        {(info?.requires_key !== false || info?.needs_base_url) && (
          <label id="llmKeyField" className="mp-field flex flex-col gap-1.5 text-[13px] font-medium text-fg" htmlFor="llmKey">
            <span>
              API key {info?.needs_base_url && <span className="mp-field__hint font-normal text-subtle">(optional)</span>}
            </span>
            <span className="relative">
              <KeyRound size={15} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-subtle" />
              <input
                id="llmKey"
                ref={keyRef}
                type="password"
                maxLength={400}
                spellCheck={false}
                autoComplete="off"
                placeholder={hasSavedKey ? "•••••••• saved" : "Paste your key"}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                className={cn(fieldClass, "pl-10 font-mono")}
              />
            </span>
            <span id="llmKeyHint" className="mp-field__hint flex items-center gap-1.5 text-[12px] font-normal text-subtle">
              <Lock size={11} aria-hidden="true" />
              {hasSavedKey ? "A key is saved. Leave this empty to keep it, or paste a new one." : info ? `Create one in your ${info.name} dashboard. It is only sent with your messages.` : ""}
            </span>
          </label>
        )}

        <div className="divide-y divide-line rounded-2xl border border-line bg-surface px-3 py-0.5">
          <Switch id="llmRemember" label="Remember on this device" checked={remember} onChange={setRemember} />
          {followupsServerOn && (
            <Switch
              id="followupsToggle"
              label="Suggest follow-up questions"
              checked={followups}
              onChange={(on) => {
                setFollowups(on);
                setFollowupsEnabled(on);
              }}
            />
          )}
        </div>

        <div id="settingsError" role="alert" className="mp-status-line mp-status-line--err min-h-5 text-[13px] text-danger">
          {error}
        </div>

        <div className="mp-modal__actions flex items-center gap-2">
          <Button id="settingsClearBtn" variant="danger" onClick={removeKey}>
            <Trash2 size={15} aria-hidden="true" /> Remove my key
          </Button>
          <span className="flex-1" />
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button id="settingsSaveBtn" type="submit" variant="primary">
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
