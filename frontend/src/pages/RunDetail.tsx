import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, download, request } from "../api";

type Metric = { metric_name: string; status: string; score: number | null; explanation: string };
type CaseRow = {
  case_key: string;
  tags: string[];
  execution_status: string;
  output: string | null;
  metrics: Metric[];
};
type Run = {
  run_id: string;
  status: string;
  snapshot: Record<string, unknown>;
  summary: Record<string, unknown> | null;
  progress: { total?: number; resolved?: number } | null;
};

const TERMINAL = new Set(["completed", "partial", "cancelled"]);

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("failed");
  const [tag, setTag] = useState("");
  const [maxScore, setMaxScore] = useState("");

  useEffect(() => {
    let stopped = false;
    async function load() {
      try {
        const next = await request<Run>(`/api/v1/evaluations/${runId}`);
        if (stopped) return;
        setRun(next);
        if (TERMINAL.has(next.status)) {
          const body = await request<{ cases: CaseRow[] }>(`/api/v1/evaluations/${runId}/cases`);
          if (!stopped) setCases(body.cases);
        }
      } catch (err) {
        if (!stopped) setError(err instanceof ApiError ? err.message : "Could not load the run");
      }
    }
    load();
    const timer = window.setInterval(load, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runId]);

  async function cancel() {
    try {
      await request(`/api/v1/evaluations/${runId}/cancel`, { method: "POST" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel");
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!run) return <p>Loading run…</p>;

  const visible = cases.filter((row) => matches(row, statusFilter, tag, maxScore));

  return (
    <>
      <h1>Run {run.status}</h1>
      <p className="muted">
        Progress: {run.progress?.resolved ?? 0} / {run.progress?.total ?? "missing"}
      </p>
      {run.status === "queued" || run.status === "running" ? (
        <button type="button" onClick={cancel}>Cancel</button>
      ) : (
        <p>
          <button type="button" onClick={() => download(`/api/v1/evaluations/${runId}/report?format=json`, `run-${runId}.json`)}>
            Download JSON
          </button>{" "}
          <button type="button" onClick={() => download(`/api/v1/evaluations/${runId}/report?format=csv`, `run-${runId}.csv`)}>
            Download CSV
          </button>
        </p>
      )}
      <section className="card">
        <h2>Snapshot</h2>
        <pre>{JSON.stringify(run.snapshot, null, 2)}</pre>
      </section>
      <section className="card">
        <h2>Summary</h2>
        {run.summary ? <pre>{JSON.stringify(run.summary, null, 2)}</pre> : <p>Missing. The run has not finished.</p>}
      </section>
      <section className="card">
        <h2>Cases</h2>
        {!TERMINAL.has(run.status) ? (
          <p>Waiting for a terminal status before loading cases.</p>
        ) : cases.length === 0 ? (
          <p>No case results.</p>
        ) : (
          <>
            <div className="filters">
              <label>
                Status
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="failed">Failed</option>
                  <option value="all">All</option>
                  <option value="succeeded">Succeeded</option>
                  <option value="execution_error">Execution error</option>
                </select>
              </label>
              <label>
                Tag
                <input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="support" />
              </label>
              <label>
                Score at most
                <input value={maxScore} onChange={(event) => setMaxScore(event.target.value)} placeholder="1" />
              </label>
            </div>
            {visible.length === 0 ? (
              <p>No cases match these filters.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Status</th>
                    <th>Tags</th>
                    <th>Scores</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <tr key={row.case_key}>
                      <td><Link to={`/runs/${runId}/cases/${encodeURIComponent(row.case_key)}`}>{row.case_key}</Link></td>
                      <td>{row.execution_status}</td>
                      <td>{row.tags.join(", ") || "none"}</td>
                      <td>{row.metrics.map((metric) => `${metric.metric_name}: ${metric.status}`).join(", ") || "none"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>
    </>
  );
}

function matches(row: CaseRow, statusFilter: string, tag: string, maxScore: string): boolean {
  const failed = row.execution_status !== "succeeded" || row.metrics.some((metric) => metric.status !== "passed");
  if (statusFilter === "failed" && !failed) return false;
  if (statusFilter === "succeeded" && row.execution_status !== "succeeded") return false;
  if (statusFilter === "execution_error" && row.execution_status !== "execution_error") return false;
  if (tag && !row.tags.some((item) => item.toLowerCase().includes(tag.toLowerCase()))) return false;
  if (maxScore.trim()) {
    const limit = Number(maxScore);
    if (!Number.isNaN(limit)) {
      const scores = row.metrics.map((metric) => metric.score).filter((score): score is number => score !== null);
      if (scores.length === 0 || Math.min(...scores) > limit) return false;
    }
  }
  return true;
}
