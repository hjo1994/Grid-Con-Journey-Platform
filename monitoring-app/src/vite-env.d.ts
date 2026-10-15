/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_C4C_TICKET_URL?: string;
  readonly VITE_OIDC_CLIENT_ID: string;
  readonly VITE_OIDC_AUTHORITY: string;
  readonly VITE_OIDC_REQUEST_GROUPS: string;
  readonly VITE_AUTH_DEV_BYPASS?: string;
}
