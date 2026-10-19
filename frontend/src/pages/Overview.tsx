import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, loadSession, request } from "../api";

type Overview = {
  generated_at: string;
  scope: { workspace_id: string; workspace_name: string; organization_name?: string };
  status_counts: Record<string, number>;
  metric_averages: { metric_name: string; average: number }[] | null;
  latency_ms_median: number | null;
  latency_ms_p95: number | null;
  token_usage: { input_tokens: number | null; output_tokens: number | null } | null;
  estimated_cost: null;
  estimated_cost_reason: string;
  safety: { passed: number; failed: number; metric_error: number } | null;
  comparisons: { experiment_id: string; name: string; decision: string; created_at: string }[];
  regressions: {
    experiment_id: string;
    experiment_name: string;
    candidate_run_id: string;
    case_key: string;
    metric: string;
  }[];
  later_note: string;
};

type RunList = {
  runs: {
    run_id: string;
    status: string;
    dataset_name: string;
    target_name: string | null;
    created_at: string;
  }[];
};

export function OverviewPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [runs, setRuns] = useState<RunList["runs"]>([]);
  const [error, setError] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [acceptToken, setAcceptToken] = useState("");
  const [notice, setNotice] = useState("");
  const role = loadSession()?.role;

  useEffect(() => {
    Promise.all([request<Overview>("/api/v1/overview"), request<RunList>("/api/v1/evaluations")])
      .then(([summary, listed]) => {
        setOverview(summary);
        setRuns(listed.runs);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load overview"));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!overview) return <p>Loading overview…</p>;

  return (
    <>
      <h1>Overview</h1>
      <p className="muted">
        Organization: {overview.scope.organization_name || "missing"}. Workspace: {overview.scope.workspace_name}. Freshness: {overview.generated_at}.
      </p>
      {role === "owner" && (
        <section className="card">
          <h2>Invite</h2>
          <button
            type="button"
            onClick={() => {
              request<{ token: string }>("/api/v1/invites", { method: "POST", body: JSON.stringify({ role: "member" }) })
                .then((body) => setInviteToken(body.token))
                .catch((err) => setNotice(err instanceof ApiError ? err.message : "Could not create an invite"));
            }}
          >
            Create member invite
          </button>
          <button
            type="button"
            onClick={() => {
              request<{ token: string }>("/api/v1/invites", { method: "POST", body: JSON.stringify({ role: "viewer" }) })
                .then((body) => setInviteToken(body.token))
                .catch((err) => setNotice(err instanceof ApiError ? err.message : "Could not create an invite"));
            }}
          >
            Create viewer invite
          </button>
          {inviteToken && <p>Invite token: {inviteToken}</p>}
        </section>
      )}
      <section className="card">
        <h2>Accept invite</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            request(`/api/v1/invites/${encodeURIComponent(acceptToken)}/accept`, { method: "POST" })
              .then(() => setNotice("Invite accepted."))
              .catch((err) => setNotice(err instanceof ApiError ? err.message : "Could not accept the invite"));
          }}
        >
          <input value={acceptToken} onChange={(event) => setAcceptToken(event.target.value)} placeholder="Invite token" />
          <button type="submit">Accept</button>
        </form>
        {notice && <p>{notice}</p>}
      </section>
      <section className="grid">
        {Object.entries(overview.status_counts).map(([status, count]) => (
          <article className="card" key={status}>
            <strong>{status}</strong>
            <div>{count}</div>
          </article>
        ))}
      </section>
      <section className="card">
        <h2>Metric averages</h2>
        {overview.metric_averages === null ? (
          <p>Missing. No scored metrics in this workspace.</p>
        ) : (
          <table>
            <tbody>
              {overview.metric_averages.map((metric) => (
                <tr key={metric.metric_name}>
                  <td>{metric.metric_name}</td>
                  <td>{metric.average.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <h2>Latency and tokens</h2>
        <p>Median latency: {show(overview.latency_ms_median, "ms")}</p>
        <p>p95 latency: {show(overview.latency_ms_p95, "ms")}</p>
        <p>
          Token usage:{" "}
          {overview.token_usage
            ? `${overview.token_usage.input_tokens ?? "missing"} input, ${overview.token_usage.output_tokens ?? "missing"} output`
            : "Missing. No token usage recorded."}
        </p>
        <p>Estimated cost: missing. {overview.estimated_cost_reason}.</p>
      </section>
      <section className="card">
        <h2>Safety</h2>
        <p className="muted">Safety is not included in the metric averages.</p>
        {overview.safety === null ? (
          <p>Missing. No safety results in this workspace.</p>
        ) : (
          <p>
            Passed {overview.safety.passed}, failed {overview.safety.failed}, metric errors {overview.safety.metric_error}.
          </p>
        )}
      </section>
      <section className="card">
        <h2>Comparisons</h2>
        {overview.comparisons.length === 0 ? (
          <p>No experiment comparisons yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Decision</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {overview.comparisons.map((item) => (
                <tr key={item.experiment_id}>
                  <td><Link to={`/experiments/${item.experiment_id}`}>{item.name}</Link></td>
                  <td>{item.decision}</td>
                  <td>{item.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <h2>Regressions</h2>
        {overview.regressions.length === 0 ? (
          <p>No pass-to-fail regressions in recent comparisons.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Case</th>
                <th>Metric</th>
              </tr>
            </thead>
            <tbody>
              {overview.regressions.map((item) => (
                <tr key={`${item.experiment_id}-${item.case_key}-${item.metric}`}>
                  <td>{item.experiment_name}</td>
                  <td>
                    <Link to={`/runs/${item.candidate_run_id}/cases/${item.case_key}`}>{item.case_key}</Link>
                  </td>
                  <td>{item.metric}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <h2>Later</h2>
        <p>{overview.later_note}</p>
      </section>
      <section className="card">
        <h2>Runs</h2>
        {runs.length === 0 ? (
          <p>No runs yet. {role === "viewer" ? "Viewers cannot start a run." : <Link to="/runs/new">Start one</Link>}</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Created</th>
                <th>Dataset</th>
                <th>Target</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td>{run.created_at}</td>
                  <td>{run.dataset_name}</td>
                  <td>{run.target_name || "missing"}</td>
                  <td><Link to={`/runs/${run.run_id}`}>{run.status}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function show(value: number | null, unit: string): string {
  return value === null ? "Missing" : `${value.toFixed(1)} ${unit}`;
}
