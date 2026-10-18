import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, loadSession, request } from "../api";

type Metric = {
  metric_name: string;
  status: string;
  score: number | null;
  explanation: string;
  details?: { evidence?: string[]; judge_model?: string; rubric?: string; rubric_version?: string };
};
type Document = { id: string; text: string };
type Citation = { document_id: string; claim: string };
type TraceStep = {
  kind: string;
  name: string;
  duration_ms: number;
  error?: string | null;
  mcp?: boolean;
};
type CaseRow = {
  case_key: string;
  input: string;
  expected_output: string;
  tags: string[];
  execution_status: string;
  output: string | null;
  error_category: string | null;
  error_detail: string | null;
  latency_ms: number | null;
  token_usage: { input_tokens?: number; output_tokens?: number };
  retrieved_documents: Document[] | null;
  citations: Citation[] | null;
  trace: { steps?: TraceStep[] } | null;
  metrics: Metric[];
};
const TRACE_METRICS = new Set([
  "tool_selection",
  "tool_arguments",
  "tool_permission",
  "tool_recovery",
  "tool_unnecessary",
  "task_completion",
]);

export function CaseDetailPage() {
  const { runId = "", caseKey = "" } = useParams();
  const [row, setRow] = useState<CaseRow | null>(null);
  const [error, setError] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [notice, setNotice] = useState("");
  const role = loadSession()?.role;
  const faithfulness = row?.metrics.find((metric) => metric.metric_name === "faithfulness");
  const steps = row?.trace?.steps || [];

  async function queueReview() {
    if (!row) return;
    setNotice("");
    const labels = Object.fromEntries(
      row.metrics.map((metric) => [metric.metric_name, metric.status === "passed" ? "passed" : metric.status === "metric_error" ? "metric_error" : "failed"]),
    );
    try {
      const review = await request<{ id: string }>("/api/v1/reviews", {
        method: "POST",
        body: JSON.stringify({ run_id: runId, case_key: row.case_key, labels }),
      });
      setReviewId(review.id);
      setNotice("Review queued.");
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Could not queue the review");
    }
  }

  async function approveReview() {
    setNotice("");
    try {
      const approved = await request<{ version_number: number }>(`/api/v1/reviews/${reviewId}/approve`, { method: "POST" });
      setNotice(`Approved into dataset version ${approved.version_number}.`);
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Could not approve the review");
    }
  }

  useEffect(() => {
    request<{ cases: CaseRow[] }>(`/api/v1/evaluations/${runId}/cases`)
      .then((body) => {
        const found = body.cases.find((item) => item.case_key === decodeURIComponent(caseKey));
        if (!found) setError("Case not found in this run");
        else setRow(found);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the case"));
  }, [runId, caseKey]);

  if (error) return <p className="error">{error}</p>;
  if (!row) return <p>Loading case…</p>;

  return (
    <>
      <h1>{row.case_key}</h1>
      <p className="muted">Tags: {row.tags.join(", ") || "none"}</p>
      <section className="card">
        <h2>Expected output</h2>
        <pre>{row.expected_output}</pre>
      </section>
      <section className="card">
        <h2>Actual output</h2>
        <pre>{row.output || "Missing"}</pre>
        {faithfulness && faithfulness.status !== "passed" && (
          <p><a href="#faithfulness-evidence">Open faithfulness evidence</a></p>
        )}
      </section>
      <section className="card">
        <h2>Retrieved documents</h2>
        {row.retrieved_documents && row.retrieved_documents.length > 0 ? (
          row.retrieved_documents.map((document) => (
            <article key={document.id}>
              <strong>{document.id}</strong>
              <pre>{document.text}</pre>
            </article>
          ))
        ) : (
          <p>Missing</p>
        )}
      </section>
      <section className="card">
        <h2>Citations</h2>
        {row.citations && row.citations.length > 0 ? (
          <ul>
            {row.citations.map((citation) => (
              <li key={`${citation.document_id}-${citation.claim}`}>
                {citation.document_id}: {citation.claim}
              </li>
            ))}
          </ul>
        ) : (
          <p>Missing</p>
        )}
      </section>
      <section className="card">
        <h2>Evaluators</h2>
        {row.metrics.length === 0 ? (
          <p>No metric scores. This case did not reach quality scoring.</p>
        ) : (
          row.metrics.map((metric) => (
            <article key={metric.metric_name} id={metric.metric_name === "faithfulness" ? "faithfulness-evidence" : undefined}>
              <strong>{metric.metric_name}</strong> · {metric.status}
              {metric.score !== null ? ` · ${metric.score}` : ""}
              <p>{metric.explanation || "No explanation"}</p>
              {metric.details?.evidence && metric.details.evidence.length > 0 && (
                <ul>
                  {metric.details.evidence.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              {metric.details?.judge_model && (
                <p className="muted">
                  Judge {metric.details.judge_model}, rubric {metric.details.rubric} {metric.details.rubric_version}
                </p>
              )}
              {TRACE_METRICS.has(metric.metric_name) && metric.status !== "passed" && (
                <p><a href="#agent-trace">Open the agent trace for {metric.metric_name}</a></p>
              )}
            </article>
          ))
        )}
      </section>
      <section className="card" id="agent-trace">
        <h2>Agent trace</h2>
        {steps.length === 0 ? (
          <p>Missing</p>
        ) : (
          <ol>
            {steps.map((step, index) => (
              <li key={`${step.kind}-${step.name}-${index}`}>
                {step.kind} {step.name} · {step.duration_ms} ms{step.mcp ? " · MCP" : ""}{step.error ? ` · ${step.error}` : ""}
              </li>
            ))}
          </ol>
        )}
      </section>
      <section className="card">
        <h2>Review</h2>
        <button type="button" onClick={queueReview}>Queue review</button>
        {role === "owner" && reviewId && (
          <button type="button" onClick={approveReview}>Approve review</button>
        )}
        {notice && <p>{notice}</p>}
      </section>
      <section className="card">
        <h2>Latency and tokens</h2>
        <p>Latency: {row.latency_ms === null ? "Missing" : `${row.latency_ms} ms`}</p>
        <p>
          Tokens: {row.token_usage.input_tokens ?? "missing"} input, {row.token_usage.output_tokens ?? "missing"} output
        </p>
      </section>
      <section className="card">
        <h2>Error</h2>
        {row.error_category ? (
          <p>{row.error_category}: {row.error_detail || "No detail recorded"}</p>
        ) : (
          <p>No execution error.</p>
        )}
      </section>
    </>
  );
}
