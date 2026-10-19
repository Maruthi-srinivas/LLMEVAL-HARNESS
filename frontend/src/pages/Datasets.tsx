import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, loadSession, request } from "../api";

type Dataset = { id: string; name: string; version_count: number; created_at: string };

export function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [details, setDetails] = useState<{ line: number | null; message: string }[]>([]);
  const viewer = loadSession()?.role === "viewer";

  function refresh() {
    request<{ datasets: Dataset[] }>("/api/v1/datasets")
      .then((body) => setDatasets(body.datasets))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load datasets"));
  }

  useEffect(refresh, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    setError("");
    setDetails([]);
    const session = loadSession();
    if (!session || !file) return;
    const body = new FormData();
    body.set("dataset_name", name);
    body.set("project_id", session.project_id);
    body.set("file", file);
    try {
      await request("/api/v1/datasets", { method: "POST", body });
      setName("");
      setFile(null);
      refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setDetails(err.details);
      } else {
        setError("Upload failed");
      }
    }
  }

  return (
    <>
      <h1>Datasets</h1>
      {viewer ? <p>Viewers can read datasets.</p> : <form className="card" onSubmit={upload}>
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          JSONL file
          <input type="file" accept=".jsonl,application/jsonl,text/plain" onChange={(event) => setFile(event.target.files?.[0] || null)} required />
        </label>
        {error && <p className="error">{error}</p>}
        {details.length > 0 && (
          <ul>
            {details.map((detail, index) => (
              <li key={index}>Line {detail.line ?? "?"}: {detail.message}</li>
            ))}
          </ul>
        )}
        <button type="submit">Upload</button>
      </form>}
      {viewer && error && <p className="error">{error}</p>}
      {datasets === null ? (
        <p>Loading datasets…</p>
      ) : datasets.length === 0 ? (
        <p>No datasets yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Versions</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => (
              <tr key={dataset.id}>
                <td><Link to={`/datasets/${dataset.id}`}>{dataset.name}</Link></td>
                <td>{dataset.version_count}</td>
                <td>{dataset.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
