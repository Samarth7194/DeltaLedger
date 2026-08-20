"use client";

import { useEffect, useState } from "react";
import { KeyRound, LogIn, LogOut, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, clearApiAuthToken, issueApiAuthToken, setApiAuthToken } from "@/lib/api/client";

const AUTH_TOKEN_KEY = "deltaledger.authToken";

export function AuthTokenSettings() {
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setToken(window.localStorage.getItem(AUTH_TOKEN_KEY) ?? "");
  }, []);

  async function login() {
    setSubmitting(true);
    setStatus(null);
    try {
      const issued = await issueApiAuthToken({ username: username.trim(), password });
      setToken(issued.access_token);
      setPassword("");
      setSaved(true);
      setStatus(`Signed in as ${issued.subject} (${issued.role}).`);
    } catch (error) {
      setSaved(false);
      setStatus(error instanceof ApiError ? error.message : "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function saveToken() {
    const trimmed = token.trim();
    if (trimmed) {
      setApiAuthToken(trimmed);
      setToken(trimmed);
      setSaved(true);
      setStatus("Token saved for this browser.");
    }
  }

  function clearToken() {
    clearApiAuthToken();
    setToken("");
    setPassword("");
    setSaved(false);
    setStatus(null);
  }

  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
      <div className="flex items-center gap-2">
        <KeyRound aria-hidden="true" className="h-4 w-4 text-stone-600" />
        <h3 className="text-sm font-semibold text-ink-950">API Access</h3>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-medium text-stone-700" htmlFor="api-username">
          Username
          <input
            id="api-username"
            className="mt-1 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-ledger-600 focus:ring-2 focus:ring-ledger-200"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => {
              setSaved(false);
              setUsername(event.target.value);
            }}
          />
        </label>
        <label className="block text-xs font-medium text-stone-700" htmlFor="api-password">
          Password
          <input
            id="api-password"
            className="mt-1 w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-ledger-600 focus:ring-2 focus:ring-ledger-200"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setSaved(false);
              setPassword(event.target.value);
            }}
          />
        </label>
      </div>
      <Button
        type="button"
        variant="primary"
        className="mt-3"
        onClick={login}
        disabled={submitting || !username.trim() || !password}
      >
        <LogIn aria-hidden="true" className="h-4 w-4" />
        {submitting ? "Signing in" : "Sign in"}
      </Button>
      <label className="mt-3 block text-xs font-medium text-stone-700" htmlFor="api-token">
        Token
      </label>
      <input
        id="api-token"
        className="mt-1 w-full rounded-md border border-stone-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-ledger-600 focus:ring-2 focus:ring-ledger-200"
        type="password"
        autoComplete="off"
        value={token}
        onChange={(event) => {
          setSaved(false);
          setToken(event.target.value);
        }}
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" variant="secondary" onClick={saveToken} disabled={!token.trim()}>
          <Save aria-hidden="true" className="h-4 w-4" />
          Save
        </Button>
        <Button type="button" variant="secondary" onClick={clearToken}>
          <LogOut aria-hidden="true" className="h-4 w-4" />
          Clear
        </Button>
        {saved ? <span className="text-xs text-emerald-700">Saved.</span> : null}
      </div>
      {status ? <p className="mt-2 text-xs text-stone-700">{status}</p> : null}
    </div>
  );
}
