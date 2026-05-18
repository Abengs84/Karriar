const API = "/api";

export type AuthStatus = { authenticated: boolean };

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const res = await fetch(`${API}/auth/status`, { credentials: "include" });
  if (!res.ok) return { authenticated: false };
  return res.json();
}

export async function login(password: string): Promise<void> {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Fel lösenord" }));
    throw new Error(err.detail || "Fel lösenord");
  }
}

export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}
