import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, request } from "../api";

type Version = { id: string; version_number: number; content_hash: string; case_count: number };
type CaseRow = {
  case_key: string;
  input: string;
  expected_output: string;
  tags: string[];
};

export function DatasetDetailPage() {
  const { datasetId = "" } = useParams();
  const [name, setName] = useState("");
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [cases, setCases] = useState<CaseRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    request<{ name: string; versions: Version[] }>(`/api/v1/datasets/${datasetId}`)
      .then(async (dataset) => {
        setName(dataset.name);
        setVersions(dataset.versions);
        const latest = dataset.versions[dataset.versions.length - 1];
        if (!latest) {
          setCases([]);
          return;
        }
        const version = await request<{ cases: CaseRow[] }>(
          `/api/v1/datasets/${datasetId}/versions/${latest.version_number}`,
        );
        setCases(version.cases);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load dataset"));
  }, [datasetId]);

  if (error) return <p className="error">{error}</p>;
  if (!versions || !cases) return <p>Loading dataset…</p>;

  const tags = [...new Set(cases.flatMap((row) => row.tags))];

  return (
    <>
      <h1>{name}</h1>
      <section className="card">
        <h2>Versions</h2>
        {versions.length === 0 ? (
          <p>No versions.</p>
        ) : (
          <ul>
            {versions.map((version) => (
              <li key={version.id}>
                v{version.version_number} · {version.case_count} cases · {version.content_hash.slice(0, 12)}
              </li>
            ))}
          </ul>
        )}
        <p>Tags: {tags.length ? tags.join(", ") : "none"}</p>
      </section>
      <section className="card">
        <h2>Cases</h2>
        {cases.length === 0 ? (
          <p>No cases in the latest version.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Input</th>
                <th>Expected</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((row) => (
                <tr key={row.case_key}>
                  <td>{row.case_key}</td>
                  <td>{row.input}</td>
                  <td>{row.expected_output}</td>
                  <td>{row.tags.join(", ") || "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
