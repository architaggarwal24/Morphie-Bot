import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { ClipboardCopy, FileDown, FileText, FileUp, KeyRound, MessageSquare, Plus, Printer, SunMoon, TextCursorInput } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatView } from "@/components/chat/ChatView";
import { CommandMenu, type CommandAction } from "@/components/dialogs/CommandMenu";
import { SettingsModal } from "@/components/dialogs/SettingsModal";
import { DocumentsPanel } from "@/components/docs/DocumentsPanel";
import { Aurora } from "@/components/fx/Aurora";
import { Composer } from "@/components/layout/Composer";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { ToastProvider, UNDO_MS, useToast } from "@/components/ui/Toast";
import { useChat } from "@/hooks/useChat";
import { useDocuments } from "@/hooks/useDocuments";
import { useRevalidate, useShortcuts } from "@/hooks/useShortcuts";
import { useStatus } from "@/hooks/useStatus";
import { useTheme } from "@/hooks/useTheme";
import { saveLlm } from "@/lib/llm";
import { copyText } from "@/lib/clipboard";
import { parseLeadingCommand } from "@/lib/commands";
import { downloadText, exportFilename, toMarkdown } from "@/lib/exportChat";
import type { Doc } from "@/hooks/useDocuments";
import { SUGGESTIONS, TOOLS } from "@/lib/tools";

const REVALIDATE_MIN_GAP_MS = 5000; // focus fires a lot; don't hammer the server

function useMediaQuery(query: string) {
  const [match, setMatch] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setMatch(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

function Shell() {
  const showToast = useToast();
  const { theme, toggle: toggleTheme } = useTheme();
  const wide = useMediaQuery("(min-width: 1280px)");

  const [docsOpen, setDocsOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- model status (sidebar badge) ----
  const openSettings = useCallback(() => {
    setCmdOpen(false);
    setDrawer(false);
    setSettingsOpen(true);
  }, []);
  const onStatusError = useCallback((m: string) => showToast(m, { tone: "error" }), [showToast]);
  const { status, loadStatus, lastStatusFetch } = useStatus({ onNeedsKey: openSettings, onError: onStatusError });

  // ---- documents ----
  const docs = useDocuments(showToast);
  const { loadDocuments, getSelectedDocumentIds } = docs;

  // ---- chat ----
  const onResetFailed = useCallback((m: string) => showToast(m, { tone: "error" }), [showToast]);
  const chat = useChat({ getDocumentIds: getSelectedDocumentIds, onResetFailed });

  const { restore } = chat;
  // ---- boot: restore what the server remembers, warm the documents cache, ask for a key if none is set ----
  useEffect(() => {
    restore();
    loadDocuments();
    loadStatus(true);
  }, [restore, loadDocuments, loadStatus]);

  // composer extras: a forced tool ("/web") and @mentioned documents
  const [tool, setTool] = useState<string | null>(null);
  const [mentions, setMentions] = useState<Doc[]>([]);

  const focusInput = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  const fillInput = useCallback(
    (text: string) => {
      setDraft(text);
      requestAnimationFrame(focusInput);
    },
    [focusInput],
  );

  const submit = useCallback(() => {
    if (chat.busy) {
      chat.stop();
      return;
    }
    let text = draft;
    let forced = tool;
    const typed = parseLeadingCommand(text); // "/web latest news" typed without picking from the menu
    if (typed) {
      forced = typed.tool;
      text = typed.rest;
    }
    if (!text.trim()) return;
    // mentioned documents that still exist scope this one question
    const live = mentions.filter((m) => docs.allDocuments.some((d) => d.id === m.id));
    chat.send(text, { tool: forced ?? undefined, documentIds: live.length ? live.map((m) => m.id) : undefined });
    setDraft("");
    setTool(null);
    setMentions([]);
  }, [chat, draft, tool, mentions, docs.allDocuments]);

  const editMessage = useCallback(
    async (id: string) => {
      const text = await chat.editFrom(id);
      if (text != null) fillInput(text);
    },
    [chat, fillInput],
  );

  const askFollowup = useCallback((text: string) => chat.send(text), [chat]);

  const addFiles = useCallback(
    (files: File[]) => {
      setDocsOpen(true);
      docs.uploadFiles(files);
    },
    [docs],
  );

  // ---- export ----
  const exportMarkdown = useCallback(() => {
    if (!chat.messages.length) return showToast("Nothing to export yet.");
    downloadText(exportFilename(), toMarkdown(chat.messages));
    showToast("Saved the conversation as Markdown.", { tone: "success" });
  }, [chat.messages, showToast]);
  const copyConversation = useCallback(async () => {
    if (!chat.messages.length) return showToast("Nothing to copy yet.");
    if (await copyText(toMarkdown(chat.messages))) showToast("Conversation copied.", { tone: "success" });
    else showToast("Couldn't copy the conversation.", { tone: "error" });
  }, [chat.messages, showToast]);
  const printConversation = useCallback(() => {
    if (!chat.messages.length) return showToast("Nothing to print yet.");
    setDocsOpen(false);
    requestAnimationFrame(() => window.print());
  }, [chat.messages.length, showToast]);

  const openDocs = useCallback(() => {
    setDocsOpen(true);
    setDrawer(false);
    loadDocuments();
  }, [loadDocuments]);
  const closeDocs = useCallback(() => setDocsOpen(false), []);
  const toggleDocs = useCallback(() => (docsOpen ? closeDocs() : openDocs()), [docsOpen, openDocs, closeDocs]);

  const newChat = useCallback(async () => {
    if (await chat.reset()) {
      setDocsOpen(false);
      setDrawer(false);
      focusInput();
    }
  }, [chat, focusInput]);

  const toggleThemeCentered = useCallback(() => toggleTheme(), [toggleTheme]);

  // ---- settings outcomes ----
  const onSaved = useCallback(
    (message: string) => {
      showToast(message, { tone: "success" });
      loadStatus();
    },
    [showToast, loadStatus],
  );
  const onRemoved = useCallback(
    (previous: Parameters<typeof saveLlm>[0] | null, wasRemembered: boolean) => {
      showToast(
        "Your key was removed from this browser.",
        previous
          ? {
              duration: UNDO_MS,
              action: {
                label: "Undo",
                onClick: () => {
                  saveLlm(previous, wasRemembered);
                  showToast("Your key is back.", { tone: "success" });
                  loadStatus();
                },
              },
            }
          : undefined,
      );
      loadStatus();
    },
    [showToast, loadStatus],
  );

  // ---- keyboard ----
  const dialogOpen = cmdOpen || settingsOpen;
  useShortcuts(
    {
      commandMenu: () => {
        if (settingsOpen) return;
        setCmdOpen((o) => !o);
      },
      newChat,
      focusInput,
      toggleDocs,
    },
    dialogOpen,
  );

  // Escape closes the documents panel / drawer (dialogs handle their own Escape and stop it there)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape" || e.defaultPrevented || dialogOpen) return;
      if (drawer) setDrawer(false);
      else if (docsOpen) setDocsOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dialogOpen, docsOpen, drawer]);

  useRevalidate((force) => {
    const now = Date.now();
    if (docsOpen && (force || now - docs.lastDocsFetch.current > REVALIDATE_MIN_GAP_MS)) loadDocuments();
    if (force || now - lastStatusFetch.current > 30000) loadStatus();
  });

  // ---- command menu: every page and action ----
  const actions = useMemo<CommandAction[]>(
    () => [
      { id: "newChat", label: "New chat", group: "Actions", icon: Plus, shortcut: "newChat", keywords: "clear reset conversation", run: newChat },
      { id: "chat", label: "Go to chat", group: "Actions", icon: MessageSquare, keywords: "close panel back", run: () => { closeDocs(); focusInput(); } },
      { id: "documents", label: "Open documents", group: "Actions", icon: FileText, shortcut: "toggleDocs", keywords: "files rag manage", run: openDocs },
      { id: "upload", label: "Upload a document", group: "Actions", icon: FileUp, keywords: "file pdf docx csv json txt", run: () => { openDocs(); requestAnimationFrame(() => fileInputRef.current?.click()); } },
      { id: "theme", label: "Toggle light / dark theme", group: "Actions", icon: SunMoon, keywords: "appearance mode", run: toggleThemeCentered },
      { id: "settings", label: "Model & API key", group: "Actions", icon: KeyRound, keywords: "provider settings bring your own key", run: openSettings },
      { id: "focusInput", label: "Focus the message box", group: "Actions", icon: TextCursorInput, shortcut: "focusInput", keywords: "type write compose", run: focusInput },
      { id: "exportMd", label: "Export chat as Markdown", group: "Actions", icon: FileDown, keywords: "download save md file", run: exportMarkdown },
      { id: "copyChat", label: "Copy the whole conversation", group: "Actions", icon: ClipboardCopy, keywords: "clipboard export", run: copyConversation },
      { id: "printChat", label: "Print or save as PDF", group: "Actions", icon: Printer, keywords: "pdf export print", run: printConversation },
      ...SUGGESTIONS.map((s, i) => ({
        id: `prompt${i}`,
        label: `Ask: ${s.prompt}`,
        group: "Ask Morphie" as const,
        icon: TOOLS[s.tool].icon,
        keywords: "suggestion prompt example",
        run: () => fillInput(s.prompt),
      })),
    ],
    [newChat, closeDocs, focusInput, openDocs, toggleThemeCentered, openSettings, fillInput, exportMarkdown, copyConversation, printConversation],
  );

  const sidebar = (
    <Sidebar
      view={docsOpen ? "documents" : "chat"}
      docCount={docs.allDocuments.length}
      status={status}
      theme={theme}
      busy={chat.busy}
      onNewChat={newChat}
      onSearch={() => {
        setDrawer(false);
        setCmdOpen(true);
      }}
      onChat={() => {
        closeDocs();
        setDrawer(false);
      }}
      onDocs={() => (docsOpen ? closeDocs() : openDocs())}
      onSettings={openSettings}
      onToggleTheme={toggleTheme}
    />
  );

  const panel = <DocumentsPanel docs={docs} onClose={closeDocs} fileInputRef={fileInputRef} />;

  return (
    <div id="shell" className="relative flex h-dvh overflow-hidden">
      <Aurora />

      {/* desktop sidebar: a floating glass column */}
      <aside id="sidebar" className="glass scrollbar-thin relative z-30 m-3 mr-0 hidden w-[268px] shrink-0 overflow-y-auto rounded-3xl lg:block">
        {sidebar}
      </aside>

      {/* mobile drawer */}
      <AnimatePresence>
        {drawer && (
          <>
            <motion.div
              id="sidebarScrim"
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawer(false)}
            />
            <motion.aside
              aria-label="Menu"
              className="glass-strong scrollbar-thin fixed inset-y-2 left-2 z-50 w-[284px] overflow-y-auto rounded-3xl lg:hidden"
              initial={{ x: -320 }}
              animate={{ x: 0 }}
              exit={{ x: -320 }}
              transition={{ type: "spring", stiffness: 380, damping: 36 }}
              drag="x"
              dragConstraints={{ left: -300, right: 0 }}
              dragElastic={0.05}
              onDragEnd={(_, info) => {
                if (info.offset.x < -80) setDrawer(false);
              }}
            >
              {sidebar}
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div id="mainColumn" className="relative flex min-w-0 flex-1 flex-col">
        <Header
          onMenu={() => setDrawer(true)}
          onDocs={toggleDocs}
          onNewChat={newChat}
          docsOpen={docsOpen}
          docCount={docs.allDocuments.length}
          busy={chat.busy}
          canExport={chat.messages.length > 0}
          onExportMarkdown={exportMarkdown}
          onCopyAll={copyConversation}
          onPrint={printConversation}
        />
        <ChatView
          messages={chat.messages}
          busy={chat.busy}
          needsKey={!status.configured && !status.offline}
          onPick={fillInput}
          onAddKey={openSettings}
          onRegenerate={chat.regenerate}
          onEdit={editMessage}
          onFollowup={askFollowup}
          onDropFiles={addFiles}
        />
        <Composer
          inputRef={inputRef}
          value={draft}
          onChange={setDraft}
          onSubmit={submit}
          busy={chat.busy}
          onAttach={openDocs}
          docCount={docs.allDocuments.length}
          documents={docs.allDocuments}
          tool={tool}
          onTool={setTool}
          mentions={mentions}
          onMentions={setMentions}
          onPasteFiles={addFiles}
        />
      </div>

      {/* Documents: a docked glass column on wide screens, a sliding sheet elsewhere */}
      <AnimatePresence>
        {docsOpen && wide && (
          <motion.aside
            key="docked"
            id="workspace"
            className="glass panel-open relative z-20 my-3 mr-3 w-[380px] shrink-0 overflow-hidden rounded-3xl"
            initial={{ opacity: 0, x: 40, width: 0, marginRight: 0 }}
            animate={{ opacity: 1, x: 0, width: 380, marginRight: 12 }}
            exit={{ opacity: 0, x: 40, width: 0, marginRight: 0, transition: { duration: 0.22, ease: [0.4, 0, 1, 1] } }}
            transition={{ type: "spring", stiffness: 320, damping: 36 }}
          >
            <div className="h-full w-[380px]">{panel}</div>
          </motion.aside>
        )}
        {docsOpen && !wide && (
          <motion.div key="sheet" className="fixed inset-0 z-[45]">
            <motion.div className="absolute inset-0 bg-black/40 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.2 } }} onClick={closeDocs} />
            <motion.aside
              id="workspace"
              className="glass-strong panel-open absolute inset-y-2 right-2 w-[min(400px,calc(100vw-16px))] overflow-hidden rounded-3xl"
              initial={{ x: "110%" }}
              animate={{ x: 0 }}
              exit={{ x: "110%", transition: { duration: 0.22, ease: [0.4, 0, 1, 1] } }}
              transition={{ type: "spring", stiffness: 360, damping: 36 }}
            >
              {panel}
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} onSaved={onSaved} onRemoved={onRemoved} />
      <CommandMenu open={cmdOpen} onClose={() => setCmdOpen(false)} actions={actions} />
    </div>
  );
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <Shell />
      </ToastProvider>
    </MotionConfig>
  );
}
