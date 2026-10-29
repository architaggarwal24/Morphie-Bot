// Small per-browser preferences (not secrets). Missing storage just means defaults.
import { local, read, write } from "./storage";

const FOLLOWUPS_KEY = "morphie-followups";

export function followupsEnabled(): boolean {
  return read(local(), FOLLOWUPS_KEY) !== "off";
}

export function setFollowupsEnabled(on: boolean): void {
  write(local(), FOLLOWUPS_KEY, on ? "on" : "off");
}

/** An id for one question-and-answer pair (the server's history, Stop and Regenerate refer to it). */
export function newTurnId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, "");
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}
