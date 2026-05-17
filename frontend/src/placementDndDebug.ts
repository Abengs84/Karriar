const PREFIX = "[Karriär DnD]";

declare global {
  interface Window {
    karriarEnableDndDebug?: () => void;
    karriarDisableDndDebug?: () => void;
  }
}

/** På i dev, ?dnd-debug=1 i URL, eller localStorage "karriar-dnd-debug" = "1" */
export function isDndDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  const stored = localStorage.getItem("karriar-dnd-debug");
  if (stored === "1") return true;
  if (stored === "0") return false;
  if (new URLSearchParams(window.location.search).has("dnd-debug")) return true;
  return import.meta.env.DEV;
}

if (typeof window !== "undefined") {
  window.karriarEnableDndDebug = () => {
    localStorage.setItem("karriar-dnd-debug", "1");
    location.reload();
  };
  window.karriarDisableDndDebug = () => {
    localStorage.setItem("karriar-dnd-debug", "0");
    location.reload();
  };
}

export function dndDebug(message: string, data?: Record<string, unknown>): void {
  if (!isDndDebugEnabled()) return;
  if (data !== undefined) {
    console.log(PREFIX, message, data);
  } else {
    console.log(PREFIX, message);
  }
}

export function dndDebugWarn(message: string, data?: Record<string, unknown>): void {
  if (!isDndDebugEnabled()) return;
  if (data !== undefined) {
    console.warn(PREFIX, message, data);
  } else {
    console.warn(PREFIX, message);
  }
}

export function dndDebugGroup(title: string, fn: () => void): void {
  if (!isDndDebugEnabled()) return;
  console.groupCollapsed(`${PREFIX} ${title}`);
  try {
    fn();
  } finally {
    console.groupEnd();
  }
}

let loggedHelp = false;

export function logDndDebugHelpOnce(): void {
  if (loggedHelp) return;
  loggedHelp = true;
  if (isDndDebugEnabled()) {
    console.info(
      `${PREFIX} Debug aktiv (console.log). Filtrera på "Karriär DnD". ` +
        `Av: karriarDisableDndDebug() i konsolen.`
    );
  } else {
    console.info(
      `[Karriär] DnD-felsökning av: öppna F12 → Console, skriv: karriarEnableDndDebug() ` +
        `(eller lägg till ?dnd-debug=1 i URL:en)`
    );
  }
}
