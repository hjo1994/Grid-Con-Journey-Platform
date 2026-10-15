import { AuthProvider } from "eg-auth-react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App";
import { AuthGate } from "./shared/auth/AuthGate";
import { authManager } from "./shared/auth/authManager";
import { LoginPage } from "./shared/auth/LoginPage";
import { LogoutPage } from "./shared/auth/LogoutPage";

/** The app behind the OIDC login. Not used with the local dev bypass. */
export default function AuthApp() {
  return (
    <AuthProvider userManager={authManager.userManager} onSigninCallback={authManager.onSigninCallback}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/logout" element={<LogoutPage />} />
          <Route
            path="/*"
            element={
              <AuthGate>
                <App signOut />
              </AuthGate>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
