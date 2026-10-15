import { ServiceApi } from "eg-auth-react";

// Required by AuthManager (eg-auth-react), which sets the auth header on it once
// a user is signed in. The app's own requests go through src/api/client.ts.
export const serviceApi = new ServiceApi({ baseURL: import.meta.env.VITE_API_BASE || "/api/v1" });
