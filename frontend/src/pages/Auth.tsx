import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, request, saveSession } from "../api";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const body =
        mode === "register"
          ? { email, password, workspace_name: workspace }
          : { email, password };
      const session = await request<{
        token: string;
        user_id: string;
        workspace_id: string;
        project_id: string;
        role: string;
      }>(`/api/v1/auth/${mode === "register" ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      saveSession(session);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in");
    }
  }

  return (
    <main className="layout">
      <h1>{mode === "register" ? "Create a workspace" : "Sign in"}</h1>
      <form className="card" onSubmit={submit}>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
        </label>
        <label>
          Password
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required />
        </label>
        {mode === "register" && (
          <label>
            Workspace name
            <input value={workspace} onChange={(event) => setWorkspace(event.target.value)} required />
          </label>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit">{mode === "register" ? "Register" : "Sign in"}</button>
      </form>
      {mode === "login" ? <Link to="/register">Create an account</Link> : <Link to="/login">Already registered</Link>}
    </main>
  );
}
