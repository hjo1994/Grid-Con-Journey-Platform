/*
 * Source of the OIDC access token for src/api/client.ts. Without a provider
 * (dev bypass, tests) requests go out without an Authorization header; the
 * OIDC setup registers one in authManager.ts.
 */
type TokenProvider = () => Promise<string | null>;

let provider: TokenProvider = async () => null;

export function setAccessTokenProvider(p: TokenProvider): void {
  provider = p;
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await provider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
