import { useState } from "react";

import { authManager } from "./authManager";

// Nonce for the OIDC redirect (protects against replayed ID tokens).
const nonce = () => crypto.randomUUID();

export function LoginPage() {
  const [error, setError] = useState<string | null>(null);

  const login = () => {
    setError(null);
    // Typical cause: VITE_OIDC_AUTHORITY / VITE_OIDC_CLIENT_ID were not set for this build.
    authManager.userManager.signinRedirect({ nonce: nonce() }).catch((e: unknown) => {
      setError(e instanceof Error ? e.message : "Unbekannter Fehler");
    });
  };

  return (
    <div className="state">
      <div className="card login-card">
        <h1>
          GRID CON <i>Monitoring</i>
        </h1>
        <p className="dim">Übersicht der Netzanschlussanfragen. Bitte melde dich an.</p>
        <button type="button" className="primary" onClick={login}>
          Anmelden
        </button>
        {error && (
          <p role="alert" className="error">
            Die Anmeldung konnte nicht gestartet werden: {error}. Ist die OIDC-Konfiguration (VITE_OIDC_*) für
            diesen Build gesetzt?
          </p>
        )}
      </div>
    </div>
  );
}
