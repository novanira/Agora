import { useEffect, useRef, useState } from "react";
import { Descope } from "@descope/react-sdk";
import { useHref, useNavigate } from "react-router";
import { descopeProjectId } from "./AgoraAuth";

const flowId = "passwords-with-explicit-sign-up";
const agoraTheme = {
  light: {
    globals: {
      colors: {
        primary: {
          main: "#287753",
          dark: "#1f6544",
          light: "#edf5ee",
          highlight: "#dce5da",
          contrast: "#ffffff",
        },
      },
    },
  },
};

function PasswordFlow() {
  const navigate = useNavigate();
  const loginPath = useHref("/login");
  const redirectUrl = new URL(loginPath, window.location.origin).href;
  const [status, setStatus] = useState("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (status !== "loading") return;
    const timeout = window.setTimeout(() => setStatus("error"), 20_000);
    return () => window.clearTimeout(timeout);
  }, [attempt, status]);

  function retry() {
    setStatus("loading");
    setAttempt((current) => current + 1);
  }

  function handleSuccess(event) {
    if (event.detail?.sessionJwt || event.detail?.user?.userId) {
      navigate("/list", { replace: true });
      return;
    }
    setStatus("complete");
  }

  if (status === "complete") {
    return (
      <div className="account-flow">
        <p className="account-message" role="status">Complete. Log in to continue.</p>
        <button type="button" onClick={retry}>Continue to log in</button>
      </div>
    );
  }

  return (
    <div className="account-flow">
      {status === "loading" && <p className="account-message" role="status" style={{textAlign: 'center', paddingBottom: '24px'}}>Loading the account form…</p>}
      {status === "error" && (
        <div className="account-flow-error">
          <p className="account-message" role="alert">Couldn’t load the account form.</p>
          <button type="button" onClick={retry}>Try again</button>
        </div>
      )}
      <Descope
        key={attempt}
        flowId={flowId}
        redirectUrl={redirectUrl}
        theme="light"
        themeOverride={agoraTheme}
        onReady={() => setStatus("ready")}
        onError={() => setStatus((current) => current === "loading" ? "error" : current)}
        onSuccess={handleSuccess}
      />
    </div>
  );
}

export default function AccountPage() {
  const heading = useRef(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Account | Agora";
    heading.current?.focus();
    return () => { document.title = previousTitle; };
  }, []);

  return (
    <main className="account-page" aria-labelledby="account-heading">
      <div className="account-content">
        {descopeProjectId ? (
          <PasswordFlow />
        ) : (
          <p className="account-message" role="status">Account sign-in is still being set up.</p>
        )}
      </div>
    </main>
  );
}
