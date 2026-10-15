import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { authManager } from "./authManager";

export function LogoutPage() {
  const navigate = useNavigate();

  useEffect(() => {
    // Whatever happens while removing the stored user, the next stop is the login page.
    authManager.userManager
      .removeUser()
      .catch(() => undefined)
      .finally(() => navigate("/login", { replace: true }));
  }, [navigate]);

  return (
    <div className="state">
      <p role="status">Abmeldung läuft …</p>
    </div>
  );
}
