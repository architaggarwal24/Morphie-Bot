import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocRow } from "@/components/docs/DocumentsPanel";
import { SKELETON_DELAY_MS, useDocuments } from "@/hooks/useDocuments";
import { UNDO_MS } from "@/components/ui/Toast";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const DOCS = [
  { id: "a", name: "a.pdf", type: "pdf" },
  { id: "b", name: "b.csv", type: "csv" },
];

describe("documents", () => {
  it(`shows skeleton rows only when loading takes longer than ${SKELETON_DELAY_MS}ms`, async () => {
    expect(SKELETON_DELAY_MS).toBe(300);
    vi.useFakeTimers();
    let resolve!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise((r) => (resolve = r)));
    const { result } = renderHook(() => useDocuments(vi.fn(() => ({ dismiss() {} }))));
    act(() => {
      result.current.loadDocuments();
    });
    act(() => vi.advanceTimersByTime(SKELETON_DELAY_MS - 50));
    expect(result.current.skeleton).toBe(false);
    act(() => vi.advanceTimersByTime(100));
    expect(result.current.skeleton).toBe(true);
    await act(async () => resolve(json({ documents: DOCS })));
    expect(result.current.skeleton).toBe(false);
    expect(result.current.allDocuments.map((d) => d.id)).toEqual(["a", "b"]);
  });

  it("skeleton and loaded rows come from the same builder", () => {
    const { container, rerender } = render(<DocRow doc={null} />);
    const skeleton = container.querySelector(".mp-list-item")!;
    expect(skeleton).toHaveClass("is-skeleton");
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    rerender(<DocRow doc={DOCS[0]} />);
    expect(container.querySelector(".mp-list-item")).not.toHaveClass("is-skeleton");
    expect(screen.getByLabelText("Ask about a.pdf")).toBeInTheDocument();
  });

  it("deletes optimistically, waits out the Undo window, and puts the row back if the server refuses", async () => {
    vi.useFakeTimers();
    const toast = vi.fn(() => ({ dismiss() {} }));
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ documents: DOCS }));
    const { result } = renderHook(() => useDocuments(toast));
    await act(() => result.current.loadDocuments());

    fetchMock.mockResolvedValueOnce(json({ error: "Disk on fire" }, 500));
    act(() => result.current.deleteDocument("a"));
    // gone from the screen before any request is sent
    expect(result.current.allDocuments.map((d) => d.id)).toEqual(["b"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // chat never targets the document on its way out
    expect(result.current.getSelectedDocumentIds()).toEqual(["b"]);
    expect(toast).toHaveBeenCalledWith("Deleted a.pdf", expect.objectContaining({ action: expect.objectContaining({ label: "Undo" }) }));

    await act(async () => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    await act(async () => {});
    expect(fetchMock).toHaveBeenLastCalledWith("/documents/a", expect.objectContaining({ method: "DELETE", keepalive: true }));
    expect(result.current.allDocuments.map((d) => d.id)).toEqual(["a", "b"]); // back where it was
    expect(toast).toHaveBeenLastCalledWith(expect.stringContaining("Couldn't delete a.pdf"), expect.anything());
  });

  it("Undo restores the row and sends no request", async () => {
    vi.useFakeTimers();
    let undo: (() => void) | undefined;
    const toast = vi.fn((_m: string, o?: any) => {
      undo = o?.action?.onClick;
      return { dismiss() {} };
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ documents: DOCS }));
    const { result } = renderHook(() => useDocuments(toast));
    await act(() => result.current.loadDocuments());
    act(() => result.current.deleteDocument("b"));
    act(() => undo!());
    await act(async () => {
      vi.advanceTimersByTime(UNDO_MS * 2);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.allDocuments.map((d) => d.id)).toEqual(["a", "b"]);
  });

  it("asks about all documents (null) unless the person narrows it down", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json({ documents: DOCS }));
    const { result } = renderHook(() => useDocuments(vi.fn(() => ({ dismiss() {} }))));
    await act(() => result.current.loadDocuments());
    expect(result.current.getSelectedDocumentIds()).toBeNull();
    act(() => result.current.setAskAll(false));
    act(() => result.current.toggleSelected("a", false));
    expect(result.current.getSelectedDocumentIds()).toEqual(["b"]);
  });
});
