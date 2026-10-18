import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, loadSession, request } from "../api";

type Policy = { id: string; name: string };
type Run = { run_id: string; status: string; dataset_name: string; target_name: string | null };

const TERMINAL = new Set(["completed", "partial"]);

export function ExperimentsPage() {
  const navigate = useNavigate();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [policyName, setPolicyName] = useState("release-policy");
  const [minimums, setMinimums] = useState('{"correctness": 0.5, "faithfulness": 0.5}');
  const [maxErrorRate, setMaxErrorRate] = useState("1");
  const [latencyBudget, setLatencyBudget] = useState("1000");
  const [safetyRequired, setSafetyRequired] = useState(true);
  const [price, setPrice] = useState("0.002");
  const [maxCostIncrease, setMaxCostIncrease] = useState("1");
  const [name, setName] = useState("candidate-check");
  const [policyId, setPolicyId] = useState("");
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [error, setError] = useState("");

  function refresh() {
    Promise.all([
      request<{ policies: Policy[] }>("/api/v1/policies"),
      request<{ runs: Run[] }>("/api/v1/evaluations"),
    ])
      .then(([policyBody, runBody]) => {
        setPolicies(policyBody.policies);
        setPolicyId((current) => current || policyBody.policies[0]?.id || "");
        const finished = runBody.runs.filter((run) => TERMINAL.has(run.status));
        setRuns(finished);
        setBaselineId((current) => current || finished[0]?.run_id || "");
        setCandidateId((current) => current || finished[1]?.run_id || finished[0]?.run_id || "");
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load experiments"));
  }

  useEffect(refresh, []);

  async function createPolicy(event: FormEvent) {
    event.preventDefault();
    setError("");
    const session = loadSession();
    if (!session) return;
    try {
      const created = await request<Policy>("/api/v1/policies", {
        method: "POST",
        body: JSON.stringify({
          project_id: session.project_id,
          name: policyName,
          metric_minimums: JSON.parse(minimums),
          max_error_rate: Number(maxErrorRate),
          latency_budget_ms: Number(latencyBudget),
          safety_required: safetyRequired,
          price_per_1k_tokens: Number(price),
          max_cost_increase: Number(maxCostIncrease),
        }),
      });
      setPolicyId(created.id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the policy");
    }
  }

  async function createExperiment(event: FormEvent) {
    event.preventDefault();
    setError("");
    const session = loadSession();
    if (!session) return;
    try {
      const created = await request<{ id: string }>("/api/v1/experiments", {
        method: "POST",
        body: JSON.stringify({
          project_id: session.project_id,
          name,
          policy_id: policyId,
          baseline_run_id: baselineId,
          candidate_run_id: candidateId,
        }),
      });
      navigate(`/experiments/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not compare the runs");
    }
  }

  return (
    <>
      <h1>Experiments</h1>
      <form className="card" onSubmit={createPolicy}>
        <h2>Release policy</h2>
        <label>
          Name
          <input value={policyName} onChange={(event) => setPolicyName(event.target.value)} required />
        </label>
        <label>
          Metric minimums
          <input value={minimums} onChange={(event) => setMinimums(event.target.value)} required />
        </label>
        <label>
          Maximum error rate
          <input value={maxErrorRate} onChange={(event) => setMaxErrorRate(event.target.value)} required />
        </label>
        <label>
          Latency budget (ms)
          <input value={latencyBudget} onChange={(event) => setLatencyBudget(event.target.value)} required />
        </label>
        <label>
          Price per 1,000 tokens
          <input value={price} onChange={(event) => setPrice(event.target.value)} required />
        </label>
        <label>
          Maximum cost increase
          <input value={maxCostIncrease} onChange={(event) => setMaxCostIncrease(event.target.value)} required />
        </label>
        <label>
          <input type="checkbox" checked={safetyRequired} onChange={(event) => setSafetyRequired(event.target.checked)} /> Safety failure blocks the candidate
        </label>
        <button type="submit">Save policy</button>
      </form>
      <form className="card" onSubmit={createExperiment}>
        <h2>Compare runs</h2>
        <label>
          Experiment name
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          Policy
          <select value={policyId} onChange={(event) => setPolicyId(event.target.value)} required>
            {policies.map((policy) => (
              <option key={policy.id} value={policy.id}>{policy.name}</option>
            ))}
          </select>
        </label>
        <label>
          Baseline
          <select value={baselineId} onChange={(event) => setBaselineId(event.target.value)} required>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.dataset_name} / {run.target_name || "missing"} / {run.status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Candidate
          <select value={candidateId} onChange={(event) => setCandidateId(event.target.value)} required>
            {runs.map((run) => (
              <option key={`candidate-${run.run_id}`} value={run.run_id}>
                {run.dataset_name} / {run.target_name || "missing"} / {run.status}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">Only finished runs can be compared. This page does not store provider keys.</p>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={!policyId || !baselineId || !candidateId}>Compare</button>
      </form>
      <p><Link to="/">Back to overview</Link></p>
    </>
  );
}
