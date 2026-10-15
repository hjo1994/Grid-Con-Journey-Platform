import { AuthManager, type AuthManagerSettings } from "eg-auth-react";

import { serviceApi } from "../api/serviceApi";
import { setAccessTokenProvider } from "./accessToken";

/*
 * Handles the OIDC login (same setup as the AI Cockpit). Only loaded when the
 * dev bypass is off (see main.tsx).
 */
const settings: AuthManagerSettings = {
  client_id: import.meta.env.VITE_OIDC_CLIENT_ID,
  // Derived at runtime: it differs per stage/domain and cannot be injected at build time.
  redirect_uri: `${window.location.origin}/`,
  authority: import.meta.env.VITE_OIDC_AUTHORITY,
  request_groups: import.meta.env.VITE_OIDC_REQUEST_GROUPS,
};

export const authManager = new AuthManager(serviceApi, settings);

// The API client sends the current access token as Bearer header.
setAccessTokenProvider(async () => (await authManager.userManager.getUser())?.access_token ?? null);

// Load a stored user and raise the addUserLoaded event.
await authManager.userManager.getUser(true);
