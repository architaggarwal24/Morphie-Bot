import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "@/App";

function mockServer(configured = true) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body =
      url === "/status"
        ? { provider: "Mistral", model: "mistral-large-latest", configured }
        : url === "/documents"
          ? { documents: [] }
          : url === "/providers"
            ? { providers: [{ id: "mistral", name: "Mistral", default_model: "m", models: [], requires_key: true }] }
            : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

describe("the app", () => {
  it("boots to the welcome screen, loads status and warms the documents cache", async () => {
    const fetchMock = mockServer();
    render(<App />);
    expect(screen.getByRole("heading", { name: "Ask Morphie anything" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Crunch numbers|Ask your documents|Check any clock|Search the web/ })).toHaveLength(4);
    await waitFor(() => expect(document.getElementById("providerBadgeName")).toHaveTextContent("Mistral · mistral-large-latest"));
    const called = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(called).toEqual(expect.arrayContaining(["/status", "/documents"]));
  });

  it("asks for an API key right away when none is configured", async () => {
    mockServer(false);
    render(<App />);
    expect(await screen.findByRole("dialog", { name: /Model & API key/ })).toBeInTheDocument();
  });

  it("a suggestion card fills the message box", async () => {
    mockServer();
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Crunch numbers/ }));
    expect(screen.getByLabelText("Message Morphie")).toHaveValue("What's 20% of 500?");
  });

  it("Ctrl/Cmd+K opens the command menu even from the message box; plain keys don't fire while typing", async () => {
    mockServer();
    render(<App />);
    const input = screen.getByLabelText("Message Morphie");
    input.focus();
    fireEvent.keyDown(input, { key: "/" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "k", ctrlKey: true, metaKey: false });
    fireEvent.keyDown(input, { key: "k", metaKey: true, ctrlKey: false });
    // one of the two is the platform modifier: the menu is open
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Command menu" })).toBeInTheDocument());
  });

  it("Escape in the command menu does not also close the documents panel behind it", async () => {
    mockServer();
    render(<App />);
    fireEvent.click(document.getElementById("docsBtn")!);
    await waitFor(() => expect(document.getElementById("docsPanel")).toBeInTheDocument());
    fireEvent.click(document.getElementById("cmdBtn")!);
    const field = await screen.findByRole("combobox", { name: "Search pages and actions" });
    act(() => {
      fireEvent.keyDown(field, { key: "Escape" });
    });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Command menu" })).not.toBeInTheDocument());
    expect(document.getElementById("docsPanel")).toBeInTheDocument();
  });
});
