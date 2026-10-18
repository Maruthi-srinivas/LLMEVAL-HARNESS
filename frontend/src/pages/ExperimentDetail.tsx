import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, request } from "../api";

type Delta = {
  metric_name: string;
  baseline_average: number | null;
  candidate_average: number | null;
  delta: number | null;
};
type Regression = { case_key: string; metric: string; baseline_status: string; candidate_status: string };
type Experiment = {
  id: string;
  name: string;
  decision: string;
  baseline_run_id: string;
  candidate_run_id: string;
  comparison: {
    matched_count: number;
    unmatched_baseline_count: number;
    unmatched_candidate_count: number;
    warning: string | null;
    metric_deltas: Delta[];
    regressions: Regression[];
    latency_ms: { baseline_median: number | null; candidate_median: number | null; change: number | null };
    cost: { baseline: number; candidate: number; change: number; price_per_1k_tokens: number };
    evaluator_differences: { name: string }[];
    gate_reasons: string[];
    review_reasons: string[];
  };
};

export function ExperimentDetailPage() {
  const { experimentId = "" } = useParams();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    request<Experiment>(`/api/v1/experiments/${experimentId}`)
      .then(setExperiment)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the comparison"));
  }, [experimentId]);

  if (error) return <p className="error">{error}</p>;
  if (!experiment) return <p>Loading comparison…</p>;
  const comparison = experiment.comparison;

  return (
    <>
      <h1>{experiment.name}</h1>
      <p>Decision: <strong>{experiment.decision}</strong></p>
      {comparison.warning && <p className="error">{comparison.warning}</p>}
      <p>
        Matched cases: {comparison.matched_count}. Unmatched baseline: {comparison.unmatched_baseline_count}. Unmatched candidate: {comparison.unmatched_candidate_count}.
      </p>
      <section className="card">
        <h2>Baseline and candidate</h2>
        <table>
          <thead>
            <tr>
              <th>Metric</th>
              <th>Baseline</th>
              <th>Candidate</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metric_deltas.map((metric) => (
              <tr key={metric.metric_name}>
                <td>{metric.metric_name}</td>
                <td>{show(metric.baseline_average)}</td>
                <td>{show(metric.candidate_average)}</td>
                <td>{show(metric.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          Median latency change: {show(comparison.latency_ms.change)} ms. Cost change: {comparison.cost.change.toFixed(4)} at {comparison.cost.price_per_1k_tokens} per 1,000 tokens.
        </p>
        <p>
          <Link to={`/runs/${experiment.baseline_run_id}`}>Baseline run</Link>
          {" · "}
          <Link to={`/runs/${experiment.candidate_run_id}`}>Candidate run</Link>
        </p>
      </section>
      <section className="card">
        <h2>Regressions</h2>
        {comparison.regressions.length === 0 ? (
          <p>No case moved from pass to fail.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Metric</th>
                <th>Baseline</th>
                <th>Candidate</th>
              </tr>
            </thead>
            <tbody>
              {comparison.regressions.map((item) => (
                <tr key={`${item.case_key}-${item.metric}`}>
                  <td>
                    <Link to={`/runs/${experiment.candidate_run_id}/cases/${item.case_key}`}>{item.case_key}</Link>
                  </td>
                  <td>{item.metric}</td>
                  <td>{item.baseline_status}</td>
                  <td>{item.candidate_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <h2>Policy result</h2>
        <p>Gate reasons: {comparison.gate_reasons.join("; ") || "none"}</p>
        <p>Review reasons: {comparison.review_reasons.join("; ") || "none"}</p>
        <p>Evaluator differences: {comparison.evaluator_differences.map((item) => item.name).join(", ") || "none"}</p>
      </section>
    </>
  );
}

function show(value: number | null): string {
  return value === null ? "missing" : value.toFixed(3);
}
