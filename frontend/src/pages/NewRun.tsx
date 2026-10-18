import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, loadSession, request } from "../api";

type Dataset = { id: string; name: string };
type Version = { id: string; version_number: number; case_count: number };
type Contract = { name: string; required_inputs: string[] };
type VersionCase = {
  json_schema: unknown;
  relevant_document_ids: string[];
  citations: unknown[];
  expected_policy: string | null;
  context: string | null;
  retrieved_context: unknown;
  allowed_tools: string[];
  expected_tools: unknown[];
  goal: string | null;
};

export function NewRunPage() {
  const navigate = useNavigate();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [targetName, setTargetName] = useState("mock-target");
  const [promptVersion, setPromptVersion] = useState("prompt-1");
  const [adapterType, setAdapterType] = useState("mock");
  const [endpoint, setEndpoint] = useState("");
  const [behavior, setBehavior] = useState("default");
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [versionCases, setVersionCases] = useState<VersionCase[]>([]);
  const [selected, setSelected] = useState<string[]>(["exact_match"]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    request<{ datasets: Dataset[] }>("/api/v1/datasets")
      .then((body) => {
        setDatasets(body.datasets);
        setLoading(false);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load datasets"));
  }, []);

  useEffect(() => {
    request<{ evaluators: Contract[] }>("/api/v1/evaluators")
      .then((body) => setContracts(body.evaluators))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load evaluators"));
  }, []);

  useEffect(() => {
    if (!datasetId) {
      setVersions([]);
      return;
    }
    request<{ versions: Version[] }>(`/api/v1/datasets/${datasetId}`)
      .then((body) => {
        setVersions(body.versions);
        setVersionId(body.versions[body.versions.length - 1]?.id || "");
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load versions"));
  }, [datasetId]);

  useEffect(() => {
    const version = versions.find((item) => item.id === versionId);
    if (!datasetId || !version) {
      setVersionCases([]);
      return;
    }
    request<{ cases: VersionCase[] }>(`/api/v1/datasets/${datasetId}/versions/${version.version_number}`)
      .then((detail) => setVersionCases(detail.cases))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load cases"));
  }, [datasetId, versionId, versions]);

  function toggle(name: string) {
    setSelected((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const session = loadSession();
    if (!session) return;
    try {
      const target = await request<{ id: string }>("/api/v1/targets", {
        method: "POST",
        body: JSON.stringify({
          project_id: session.project_id,
          name: targetName,
          adapter_type: adapterType,
          config:
            adapterType === "http_rag"
              ? { endpoint }
              : adapterType === "langgraph"
                ? {}
                : behavior === "default"
                  ? { model: "mock-v1" }
                  : { model: "mock-v1", behavior },
          prompt_version: promptVersion,
        }),
      });
      const run = await request<{ run_id: string }>("/api/v1/evaluations", {
        method: "POST",
        body: JSON.stringify({
          dataset_version_id: versionId,
          target_id: target.id,
          evaluator_names: selected,
        }),
      });
      navigate(`/runs/${run.run_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the run");
    }
  }

  if (loading) return <p>Loading datasets…</p>;

  return (
    <>
      <h1>New run</h1>
      {datasets.length === 0 ? (
        <p>Upload a dataset before starting a run.</p>
      ) : (
        <form className="card" onSubmit={submit}>
          <label>
            Dataset
            <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} required>
              <option value="">Select a dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>{dataset.name}</option>
              ))}
            </select>
          </label>
          <label>
            Version
            <select value={versionId} onChange={(event) => setVersionId(event.target.value)} required>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version_number} ({version.case_count} cases)
                </option>
              ))}
            </select>
          </label>
          <label>
            Mock target name
            <input value={targetName} onChange={(event) => setTargetName(event.target.value)} required />
          </label>
          <label>
            Prompt version
            <input value={promptVersion} onChange={(event) => setPromptVersion(event.target.value)} required />
          </label>
          <label>
            Adapter
            <select value={adapterType} onChange={(event) => setAdapterType(event.target.value)}>
              <option value="mock">mock</option>
              <option value="http_rag">http_rag</option>
              <option value="langgraph">langgraph</option>
            </select>
          </label>
          {adapterType === "http_rag" && (
            <label>
              Endpoint
              <input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} required placeholder="http://rag.example/answer" />
            </label>
          )}
          {adapterType === "mock" && (
            <label>
              Mock behavior
              <select value={behavior} onChange={(event) => setBehavior(event.target.value)}>
                <option value="default">default</option>
                <option value="refuse_all">refuse_all</option>
                <option value="release_baseline">release_baseline</option>
                <option value="release_candidate">release_candidate</option>
              </select>
            </label>
          )}
          <fieldset>
            <legend>Evaluators</legend>
            {contracts.map((contract) => {
              const available = versionCases.length === 0 || versionCases.every((row) => availableFor(row, contract.required_inputs));
              return (
                <label key={contract.name}>
                  <input
                    type="checkbox"
                    checked={selected.includes(contract.name)}
                    disabled={!available}
                    onChange={() => toggle(contract.name)}
                  />{" "}
                  {contract.name}
                  {!available && <span className="muted"> — missing required case fields</span>}
                </label>
              );
            })}
          </fieldset>
          <p className="muted">This page does not store provider keys.</p>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={selected.length === 0}>Start run</button>
        </form>
      )}
    </>
  );
}

function availableFor(row: VersionCase, required: string[]): boolean {
  return required.every((field) => {
    if (field === "expected_output" || field === "input") return true;
    if (field === "json_schema") return row.json_schema != null;
    if (field === "relevant_document_ids") return (row.relevant_document_ids || []).length > 0;
    if (field === "citations") return (row.citations || []).length > 0;
    if (field === "expected_policy") return row.expected_policy === "refuse" || row.expected_policy === "answer";
    if (field === "context") return row.context != null;
    if (field === "retrieved_context") return row.retrieved_context != null;
    if (field === "allowed_tools") return (row.allowed_tools || []).length > 0;
    if (field === "expected_tools") return (row.expected_tools || []).length > 0;
    if (field === "goal") return Boolean(row.goal);
    return true;
  });
}
