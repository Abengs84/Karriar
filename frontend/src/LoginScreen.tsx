import { FormEvent, useState } from "react";
import { login } from "./auth";
import { PrivacyNotice } from "./PrivacyNotice";

type Props = {
  onLoggedIn: () => void;
};

export function LoginScreen({ onLoggedIn }: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPrivacy, setShowPrivacy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(password);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inloggning misslyckades");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card card">
        <h1>Karriär – Placering</h1>
        <p className="login-lead">
          Logga in med lösenord för att hantera elevdata. Endast behörig personal ska ha
          åtkomst.
        </p>
        <form onSubmit={submit} className="login-form">
          <label htmlFor="password">Lösenord</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={loading}
          />
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="primary" disabled={loading || !password}>
            {loading ? "Loggar in…" : "Logga in"}
          </button>
        </form>
        <p className="login-privacy">
          <button type="button" className="link-button" onClick={() => setShowPrivacy(true)}>
            Integritet och personuppgifter
          </button>
        </p>
      </div>
      {showPrivacy && <PrivacyNotice onClose={() => setShowPrivacy(false)} />}
    </div>
  );
}
