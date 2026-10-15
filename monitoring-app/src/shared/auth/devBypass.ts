/*
 * Local escape hatch for development OUTSIDE the company network, where the AAP
 * authenticator is unreachable and a real OIDC login can never succeed.
 *
 * Enabled by VITE_AUTH_DEV_BYPASS="true" in the gitignored .env.development.local;
 * the backend must run with EG_AUTH_DEV_MODE=True. `import.meta.env.DEV` is false in
 * every production build, so the bypass cannot be switched on there even if the
 * variable leaked into the build environment.
 */
export const AUTH_DEV_BYPASS = import.meta.env.DEV && import.meta.env.VITE_AUTH_DEV_BYPASS === "true";
