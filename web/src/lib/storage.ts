// Browser storage can be missing or throw (private windows, disabled site data). Every access goes through here.

function probe(get: () => Storage): Storage | null {
  try {
    const s = get();
    const k = "__mp_probe__";
    s.setItem(k, "1");
    s.removeItem(k);
    return s;
  } catch {
    return null;
  }
}

export const local = (): Storage | null => probe(() => window.localStorage);
export const session = (): Storage | null => probe(() => window.sessionStorage);

export function read(store: Storage | null, key: string): string | null {
  try {
    return store ? store.getItem(key) : null;
  } catch {
    return null;
  }
}

export function write(store: Storage | null, key: string, value: string): void {
  try {
    store?.setItem(key, value);
  } catch {
    /* quota / disabled: the choice just won't persist */
  }
}

export function remove(store: Storage | null, key: string): void {
  try {
    store?.removeItem(key);
  } catch {
    /* ignore */
  }
}
