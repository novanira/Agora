import { useState } from "react";
import { AuthProvider, useDescope, useSession } from "@descope/react-sdk";
import { NavLink, useNavigate } from "react-router";

// Paste the public Project ID from Descope Project Settings between the quotes.
export const descopeProjectId = "Paps23MXQCEoZeh2uIa57PaaBenZ61qa";

export function AgoraAuthProvider({ children }) {
  if (!descopeProjectId) return children;
  return <AuthProvider projectId={descopeProjectId}>{children}</AuthProvider>;
}

function LoginLink() {
  return <NavLink to="/login" className="agora-account-nav-link">Log in</NavLink>;
}

function ConnectedAccountNav() {
  const { isAuthenticated } = useSession();
  const { logout } = useDescope();
  const navigate = useNavigate();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState(false);

  async function handleLogout() {
    setLogoutError(false);
    setIsLoggingOut(true);

    try {
      const result = await logout();
      if (result.ok) {
        navigate("/", { replace: true });
      } else {
        setLogoutError(true);
      }
    } catch {
      setLogoutError(true);
    } finally {
      setIsLoggingOut(false);
    }
  }

  if (!isAuthenticated) return <LoginLink />;

  return (
    <div className="agora-account-nav">
      <button
        type="button"
        className="agora-account-nav-link"
        onClick={handleLogout}
        disabled={isLoggingOut}
        aria-busy={isLoggingOut}
      >
        Log out
      </button>
      {logoutError && <p className="account-logout-error" role="alert">Couldn’t log out. Try again.</p>}
    </div>
  );
}

export function AccountNav() {
  return descopeProjectId ? <ConnectedAccountNav /> : <LoginLink />;
}
