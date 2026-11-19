import "./fonts/fonts.css";
import "./journey/journey.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// For now the app is the evaluation journey on demo data; the monitoring
// (App.tsx, styles.css) stays in the code but is not mounted.
import JourneyApp from "./journey/JourneyApp";
import { AUTH_DEV_BYPASS } from "./shared/auth/devBypass";

const root = createRoot(document.getElementById("root")!);

if (AUTH_DEV_BYPASS) {
  root.render(
    <StrictMode>
      <JourneyApp />
    </StrictMode>,
  );
} else {
  // Loaded on demand so that nothing of the OIDC setup runs with the dev bypass.
  const { default: AuthApp } = await import("./AuthApp");
  root.render(
    <StrictMode>
      <AuthApp />
    </StrictMode>,
  );
}
