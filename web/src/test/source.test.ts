// Guards over the source itself: cheap checks that catch a class of mistake no unit test would.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return n === "test" ? [] : files(p);
    return /\.(ts|tsx)$/.test(n) ? [p] : [];
  });
}
const sources = files(SRC).map((p) => ({ p, text: readFileSync(p, "utf8") }));
const all = sources.map((s) => s.text).join("\n");

describe("source guards", () => {
  it("never logs (an API key must never reach the console) and never touches cookies", () => {
    expect(all).not.toMatch(/\bconsole\./);
    expect(all).not.toMatch(/document\.cookie/);
  });

  it("never injects HTML: model and user text only reaches the page as React text or sanitized markdown", () => {
    expect(all).not.toMatch(/dangerouslySetInnerHTML/);
    expect(all).not.toMatch(/\.innerHTML\s*=/);
    expect(all).not.toMatch(/rehype-raw/);
  });

  it("never evaluates strings as code (the CSP forbids it)", () => {
    expect(all).not.toMatch(/\beval\(|new Function\(/);
  });

  it("keeps the payments-free promise: nothing here is optimistic about money", () => {
    expect(all.toLowerCase()).not.toContain("payment");
  });

  it("keeps the removed features out", () => {
    for (const gone of ["previewPanel", "memoryPanel", "providerPanel", "/memory", "/studio"]) expect(all).not.toContain(gone);
  });
});
