import { type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { clearSession, loadSession } from "./api";
import { AuthPage } from "./pages/Auth";
import { CaseDetailPage } from "./pages/CaseDetail";
import { DatasetDetailPage } from "./pages/DatasetDetail";
import { DatasetsPage } from "./pages/Datasets";
import { NewRunPage } from "./pages/NewRun";
import { ExperimentDetailPage } from "./pages/ExperimentDetail";
import { ExperimentsPage } from "./pages/Experiments";
import { OverviewPage } from "./pages/Overview";
import { RunDetailPage } from "./pages/RunDetail";

function Shell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  if (!loadSession()) return <Navigate to="/login" replace />;
  return (
    <div className="layout">
      <nav>
        <strong>EvalForge</strong>
        <NavLink to="/">Overview</NavLink>
        <NavLink to="/datasets">Datasets</NavLink>
        {loadSession()?.role !== "viewer" && <NavLink to="/runs/new">New run</NavLink>}
        <NavLink to="/experiments">Experiments</NavLink>
        <button
          className="secondary"
          type="button"
          onClick={() => {
            clearSession();
            navigate("/login");
          }}
        >
          Log out
        </button>
      </nav>
      {children}
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route path="/" element={<Shell><OverviewPage /></Shell>} />
      <Route path="/datasets" element={<Shell><DatasetsPage /></Shell>} />
      <Route path="/datasets/:datasetId" element={<Shell><DatasetDetailPage /></Shell>} />
      <Route path="/runs/new" element={<Shell><NewRunPage /></Shell>} />
      <Route path="/runs/:runId" element={<Shell><RunDetailPage /></Shell>} />
      <Route path="/runs/:runId/cases/:caseKey" element={<Shell><CaseDetailPage /></Shell>} />
      <Route path="/experiments" element={<Shell><ExperimentsPage /></Shell>} />
      <Route path="/experiments/:experimentId" element={<Shell><ExperimentDetailPage /></Shell>} />
      <Route path="*" element={<Link to="/">Go to overview</Link>} />
    </Routes>
  );
}
