import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Plus } from "lucide-react";
import { CommandMenu, type CommandAction } from "@/components/dialogs/CommandMenu";
import { SettingsModal } from "@/components/dialogs/SettingsModal";
import { LLM_KEY, loadLlm, saveLlm } from "@/lib/llm";

const PROVIDERS = {
  providers: [
    { id: "mistral", name: "Mistral", default_model: "mistral-large-latest", models: ["mistral-small-latest"], requires_key: true },
    { id: "ollama", name: "Ollama", default_model: "llama3.1", models: [], requires_key: false },
  ],
};

function mockProviders() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(PROVIDERS), { status: 200 }));
}

describe("settings (bring your own key)", () => {
  it("is an accessible dialog with a password field browsers don't autofill or spellcheck", async () => {
    mockProviders();
    render(<SettingsModal open onClose={vi.fn()} onSaved={vi.fn()} onRemoved={vi.fn()} />);
    expect(await screen.findByRole("dialog")).toHaveAttribute("aria-modal", "true");
    const key = await screen.findByLabelText(/^API key/);
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveAttribute("autocomplete", "off");
    expect(key).toHaveAttribute("spellcheck", "false");
  });

  it("never writes the saved key back into the page", async () => {
    saveLlm({ provider: "mistral", model: "", key: "sk-very-secret-1" }, true);
    mockProviders();
    const { container } = render(<SettingsModal open onClose={vi.fn()} onSaved={vi.fn()} onRemoved={vi.fn()} />);
    const key = (await screen.findByLabelText(/^API key/)) as HTMLInputElement;
    await waitFor(() => expect(screen.getByText(/A key is saved/)).toBeInTheDocument());
    expect(key.value).toBe("");
    expect(container.innerHTML).not.toContain("sk-very-secret-1");
    expect(document.body.innerHTML).not.toContain("sk-very-secret-1");
  });

  it("validates, keeps a saved key when the field is left empty, and saves", async () => {
    const user = userEvent.setup();
    mockProviders();
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} onSaved={onSaved} onRemoved={vi.fn()} />);
    const key = await screen.findByLabelText(/^API key/);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Paste your Mistral API key.");
    await user.type(key, "has space");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/doesn't look like an API key/);
    await user.clear(key);
    await user.type(key, "sk-good-key-123");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(loadLlm()).toEqual({ provider: "mistral", model: "", key: "sk-good-key-123" });
    expect(onSaved).toHaveBeenCalledWith(expect.stringContaining("Mistral"));
    expect(onClose).toHaveBeenCalled();
  });

  it("removing the key hands the previous choice to the Undo toast", async () => {
    saveLlm({ provider: "mistral", model: "", key: "sk-undo-me-123" }, true);
    mockProviders();
    const onRemoved = vi.fn();
    render(<SettingsModal open onClose={vi.fn()} onSaved={vi.fn()} onRemoved={onRemoved} />);
    fireEvent.click(await screen.findByRole("button", { name: /Remove my key/ }));
    expect(localStorage.getItem(LLM_KEY)).toBeNull();
    expect(onRemoved).toHaveBeenCalledWith({ provider: "mistral", model: "", key: "sk-undo-me-123" }, true);
  });
});

describe("command menu", () => {
  const run = vi.fn();
  const actions: CommandAction[] = [
    { id: "newChat", label: "New chat", group: "Actions", icon: Plus, shortcut: "newChat", run },
    { id: "documents", label: "Open documents", group: "Actions", icon: Plus, keywords: "files", run },
  ];

  it("is a combobox over a listbox, driven by the keyboard alone", async () => {
    const onClose = vi.fn();
    render(<CommandMenu open onClose={onClose} actions={actions} />);
    const field = screen.getByRole("combobox");
    expect(field).toHaveAttribute("aria-controls", "cmdList");
    expect(field).toHaveAttribute("aria-autocomplete", "list");
    expect(screen.getByRole("listbox")).toHaveAttribute("id", "cmdList");
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(field).toHaveAttribute("aria-activedescendant", "cmd-opt-0");
    fireEvent.keyDown(field, { key: "ArrowDown" });
    expect(field).toHaveAttribute("aria-activedescendant", "cmd-opt-1");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(field, { key: "ArrowDown" }); // wraps
    expect(field).toHaveAttribute("aria-activedescendant", "cmd-opt-0");
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onClose).toHaveBeenCalled();
    await waitFor(() => expect(run).toHaveBeenCalled());
  });

  it("filters as you type and says when nothing matches", () => {
    render(<CommandMenu open onClose={vi.fn()} actions={actions} />);
    const field = screen.getByRole("combobox");
    fireEvent.change(field, { target: { value: "files" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([expect.stringContaining("Open documents")]);
    fireEvent.change(field, { target: { value: "zzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(document.getElementById("cmdEmpty")).not.toHaveAttribute("hidden");
  });

  it("Escape closes the menu without also reaching what is behind it", () => {
    const onClose = vi.fn();
    const behind = vi.fn();
    document.addEventListener("keydown", behind);
    render(<CommandMenu open onClose={onClose} actions={actions} />);
    act(() => {
      fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalled();
    expect(behind).not.toHaveBeenCalled();
    document.removeEventListener("keydown", behind);
  });
});
