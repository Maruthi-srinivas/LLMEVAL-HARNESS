# EvalForge Version Plan

**Source:** [PRD.md](./PRD.md)  
**Purpose:** Ten sequential versions that take EvalForge from an empty repository to a production-grade evaluation platform, followed by a zero-cost deployment plan.  
**Rule:** Finish a version’s exit criteria before starting the next one. Later technologies (Kafka, SSO) stay out of earlier versions.  
**Host rule:** Docker Engine and the Docker Compose plugin are the only software installed on a developer laptop, a CI runner, or a production VM. Node.js, Python, pip, npm, PostgreSQL, Redis, Kafka, MinIO, Caddy, Prometheus, Grafana, and the EvalForge CLI run as containers. Every command in this plan is a `docker compose` command.

| Version | Name | PRD release | Outcome |
| --- | --- | --- | --- |
| 1 | Foundation | V1.0 steps 1–4 | Docker monorepo, database, and a working evaluation engine |
| 2 | API and access control | V1.0 step 5, EF-008 | Authenticated REST API for datasets, targets, and runs |
| 3 | Reliable execution | V1.0 step 6, EF-005 | Celery workers, recovery, and distinct failure types |
| 4 | Inspection dashboard | V1.0 steps 7–8, EF-007 | UI to upload data, run evaluations, and debug cases |
| 5 | Semantic and RAG evaluation | V1.5 steps 1–2, EF-009, EF-010 | Judges, retrieval metrics, faithfulness, and citations |
| 6 | Safety, registry, and calibration | V1.5 steps 3–5, EF-011, EF-012 | Safety suites, evaluator contracts, and human agreement |
| 7 | Experiments and release policy | V2.0 steps 1–3, EF-013 | Baseline comparison, regressions, and gate decisions |
| 8 | CI and operations | V2.0 steps 4–7, EF-014, EF-015 | Quality gates in CI, observability, and durable job recovery |
| 9 | Agent evaluation | V2.5, EF-016, EF-017 | Trajectories, tool checks, task completion, and human review |
| 10 | Enterprise production | V3.0, EF-018 | Tenancy, identity, governance, recovery, and scale readiness |

---

## Version 1 — Foundation

**Goal:** A developer can run a sample dataset through the engine inside Docker and read stored scores after a restart.

### Features

- Monorepo layout from the PRD: `backend/`, `evaluator/`, `worker/`, `frontend/`, `migrations/`, `sample_datasets/`, `infrastructure/`, `docs/`.
- `docker-compose.yml` with PostgreSQL, Redis, API, and a one-shot `migrate` service. Health checks, persistent Postgres volume, and `.env.example` with no secrets.
- SQLAlchemy models and migrations for workspace, project, dataset, dataset version, test case, target config, evaluator config, evaluation run, case result, and metric result.
- Immutable dataset versions. Unique constraint on case ID within a version. Unique constraint so one case cannot produce duplicate results for the same run and metric.
- Evaluation engine independent of FastAPI: load cases, validate configuration, invoke a target, score, persist, aggregate.
- `TargetAdapter` protocol and a `MockTargetAdapter` used by tests.
- Deterministic evaluators: exact match, normalized match, token F1, JSON schema validation, latency, token usage, and error rate.
- Evaluators declare required fields. Incompatible configurations fail before execution.
- Sample customer-support JSONL dataset and a one-shot container that runs it end to end (`docker compose run --rm runner`).
- Unit tests for metrics, aggregation, dataset validation, and run-state transitions, executed with `docker compose run --rm test`. No paid provider and no network in the core suite. No pytest or Python install on the host.

### Exit criteria

- `docker compose up` applies migrations and the API container becomes healthy. The host did not install Python, Node.js, PostgreSQL, or Redis.
- The sample run writes case results and a summary to PostgreSQL.
- Restarting containers leaves those results readable.
- Metric failures and execution errors are stored as different statuses.

### Out of scope

HTTP product API, login, Celery execution, and the dashboard.

---

## Version 2 — API and access control

**Goal:** An authenticated user can manage datasets and create a queued run through the API.

### Features

- `POST /api/v1/evaluations` plus dataset upload, dataset read, target configuration, run status, and case-result endpoints.
- Consistent error schema for invalid dataset, unknown run, unauthorized access, and unsupported evaluator configuration.
- Request validation with Pydantic. Ownership and quota checks before a run is created.
- Email/password authentication and workspace membership. Authorization on every resource query. Guessing an ID does not expose another workspace.
- JSONL import: size and format checks, streaming parse, required fields, line-numbered errors, normalization, duplicate ID detection, transactional save, and an import summary.
- Run creation stores a configuration snapshot: dataset version, target config, prompt version or hash, evaluator names and versions, and metric settings.
- The API inserts the run as `queued` and returns promptly with `run_id` and status. It does not call the model inside the request.
- Integration tests against the Compose PostgreSQL service for import, transactions, and authorization. The test runner is a container.

### Exit criteria

- A second user cannot read the first user’s dataset or run.
- A malformed JSONL file returns line numbers and writes nothing.
- A valid submission returns a queued run whose snapshot still matches the request after the live target config is edited.

### Out of scope

Background workers and the browser UI. Version 2 may execute a tiny run inline behind a test-only flag so API tests do not need Celery yet. The product path stays queued.

---

## Version 3 — Reliable execution

**Goal:** Workers process runs asynchronously, survive crashes, and report partial failure honestly.

### Features

- Celery worker service using Redis as the broker. Bounded concurrency per run.
- Claim batches of cases in the database. Heartbeats and progress counts stored in PostgreSQL, not only in worker memory.
- Idempotent case-result writes. Duplicate job delivery does not duplicate scores.
- Cancellation checked before each batch. A cancelled run stops claiming new cases and keeps completed results.
- Separate outcomes: target success, provider timeout, provider rate limit, evaluator error, and quality failure.
- Documented completion policy. Example: 91 successes, 5 provider errors, and 4 timeouts finish as `partial`, not as nine wrong answers.
- A run cannot reach `completed` while any case is unresolved.
- Recovery scan for queued runs with no live worker and for running cases whose heartbeat expired. V1 recovery can be a periodic Celery beat task. The transactional outbox arrives in Version 8.
- Reliability tests: kill the worker mid-run, duplicate the job, cancel mid-run, restart Redis, and upload an oversized file.

### Exit criteria

- A 100-case mock run completes through the worker.
- Killing the worker and starting it again finishes the remaining cases once.
- Provider timeouts appear in their own count on the run summary.

### Out of scope

LLM judges, regression comparison, and CI gates.

---

## Version 4 — Inspection dashboard

**Goal:** A developer can complete the evaluation loop in the browser and export a report.

### Features

- React + TypeScript app compiled inside the frontend image. The host never runs npm. The browser talks to the frontend container.
- Pages: overview, datasets, run creation, run detail, and case debugging.
- Loading, empty, and error states on every page.
- Overview shows run counts by status, per-metric averages, median and p95 latency, token usage, and estimated cost. Each summary shows timestamp, scope, and freshness. Missing data stays visible as missing.
- Dataset page: upload, version list, tags, and import errors.
- Run detail: configuration snapshot, progress, metric summary, failed-case table, and filters for status, tag, and score.
- Case view: expected output, actual output, evaluator explanation, latency, tokens, and sanitized error details.
- JSON or CSV report export for a finished run.
- Poll run status until a terminal state. Cancellation control calls the Version 3 API.
- Frontend holds no provider API keys.

### Exit criteria

- From the UI, a user uploads the sample dataset, starts a run, watches progress, opens a failed case, and downloads a report.
- Restarting the stack and signing in again shows the same run.

### Out of scope

Side-by-side experiment comparison. Snapshots stored in Versions 2 and 3 are the data that comparison will use.

---

## Version 5 — Semantic and RAG evaluation

**Goal:** A developer can tell whether a RAG failure came from retrieval, generation, or citations.

### Features

- Rubric-based LLM judges for correctness, answer relevance, and faithfulness.
- Judge calls go through the target-adapter path with timeout, schema validation, and a recorded judge model, rubric, and version.
- Invalid judge JSON is an evaluator error, not a failing answer.
- Dataset fields for retrieved context, relevant-document IDs, and citations.
- Metrics: Recall@K, Precision@K, faithfulness, answer relevance, and citation correctness.
- HTTP RAG target adapter that posts the question to a configured endpoint and stores returned documents, answer, latency, and token usage.
- Run detail shows retrieved context and citations beside the answer.
- Tests use a fake judge that returns fixed schema-valid and schema-invalid payloads. A separate optional suite can call a real provider.

### Exit criteria

- A labeled fixture with missing relevant documents lowers Recall@K and leaves generation errors distinct.
- An unsupported claim fails faithfulness while exact match can still be inspected separately.
- The UI can open the evidence behind a faithfulness failure.

### Out of scope

Safety suites and release policies. Judge scores are evidence, not yet a deployment gate.

---

## Version 6 — Safety, registry, and calibration

**Goal:** Safety is its own dimension, and every evaluator has a contract that can be checked against human labels.

### Features

- Evaluator registry. Each evaluator publishes name, version, required inputs, configuration schema, score range, and failure behavior.
- The API rejects a run whose selected evaluators lack required case fields.
- Versioned safety datasets:
  - instruction override attempts
  - requests for synthetic secrets
  - malicious instructions inside retrieved documents
  - unsupported account or payment claims
  - requests the policy says to refuse
  - valid requests that must not be refused
- SafetyEvaluator reports policy outcome separately from correctness.
- Structured-output compliance evaluator for schema-bound answers.
- Calibration set with human labels for correct, incorrect, unsupported, relevant, irrelevant, and citation validity.
- Agreement report: match rate and a list of disagreements. No automatic rubric rewrite.
- Dashboard safety panel that does not fold safety into the average quality score.

### Exit criteria

- A model that refuses every question fails the valid-request cases.
- An evaluator missing retrieval labels cannot be selected for a dataset that has none.
- Calibration output lists disagreements with case IDs.

### Out of scope

Using calibration as an automatic release gate. Humans still approve rubric changes.

---

## Version 7 — Experiments and release policy

**Goal:** A candidate configuration can be accepted or blocked with a documented reason.

### Features

- Named experiments with a baseline run and a candidate run.
- Comparison only scores cases whose IDs exist in both dataset versions. Different versions show a non-equivalent warning and the matched-case count.
- Regression list: metric deltas, cases that moved from pass to fail, latency change, and cost change.
- Evaluator name, version, and config equality called out when they differ.
- Release policies with separate thresholds: minimum metric scores, maximum error rate, latency budget, and hard safety requirements.
- Decisions: `pass`, `fail`, and `review`. A critical safety miss fails even when average correctness rises.
- Comparison page shows baseline and candidate side by side and links each regression to the case view.
- Policy result stored on the experiment so it can be re-read after the run finishes.

### Exit criteria

- The canonical scenario works: candidate correctness rises, faithfulness regressions appear, and the policy blocks the candidate.
- Comparing two dataset versions never presents the score delta as an unqualified model improvement.

### Out of scope

The CI process that consumes this decision. That is Version 8.

---

## Version 8 — CI and operations

**Goal:** A prompt or code change produces a machine-readable release decision, and operators can see stuck work.

### Features

- CLI image: `docker compose run --rm cli` submits an evaluation, waits for a terminal state, prints the decision, and exits with distinct codes for pass, quality fail, infrastructure fail, and review required.
- GitHub Actions workflow that only calls Docker Compose: unit tests, integration tests, smoke dataset on pull requests, and a larger scheduled suite. The workflow does not install Node.js, Python, PostgreSQL, or Redis on the runner.
- Smoke dataset stays small. The pre-release dataset is the full versioned suite.
- Transactional outbox so a committed run is always picked up by a worker.
- Stuck-job recovery, queue limits, per-workspace concurrency, and a token or cost budget that stops new calls.
- OpenTelemetry traces correlated across API, worker, and engine. Prometheus, Grafana, and Loki run as Compose services. No metrics or log agent is installed on the host.
- Operational metrics: request latency, HTTP errors, queue depth, queue wait, worker utilization, provider timeout rate, database pool usage.
- Quality metrics: score distributions, regression counts, judge disagreement, cost, and safety violations. Raw prompts are omitted unless content capture is explicitly enabled, with redaction.
- Alerts for long queue time, worker failures, sustained provider timeouts, policy regressions, budget breaches, and pool or queue saturation.
- Kafka is optional in this version. Add it only when a second consumer needs durable domain events. If added: versioned events, outbox publication, and idempotent consumers.

### Exit criteria

- A pull request that breaks a safety threshold fails the workflow with the quality-fail code.
- Stopping the provider mock fails the workflow with the infrastructure-fail code, not the quality-fail code.
- A run inserted without a broker publish is still executed after recovery.

### Out of scope

Agent traces and multi-organization SSO.

---

## Version 9 — Agent evaluation

**Goal:** A developer can see the full path an agent took and whether its tool use and task result were acceptable.

### Features

- Workflow adapter for one explicit agent interface, starting with LangGraph.
- Trace capture: nodes, tool calls, inputs, outputs, state transitions, and durations.
- Tool metrics: selection, argument validity, permission boundaries, error recovery, and unnecessary calls.
- Task-completion metric based on the goal and constraints in the test case.
- MCP tool-call capture for supported servers, recorded as trace steps.
- Side-effecting tools run only against mocks or an isolated environment. Workers do not receive production credentials for those tools.
- Human review queue for ambiguous or high-risk cases. Approved labels can be copied into a new dataset version. They do not mutate the version already used by a run.
- Trace view in the UI, linked from a failed task or tool metric.

### Exit criteria

- A fixture agent that calls a forbidden tool fails the permission metric even if the final text looks correct.
- A reviewer approval creates a new dataset version and leaves the previous version unchanged.

### Out of scope

Organization-wide SSO. Production remains the same Compose stack.

---

## Version 10 — Enterprise production

**Goal:** More than one organization can use EvalForge with tested isolation, identity, audit, retention, and recovery.

### Features

- Organization boundary on every workspace resource. Cross-tenant tests for API, workers, exports, and artifact URLs.
- Role-based access for owner, member, and viewer.
- OpenID Connect SSO and service accounts for CI.
- Audit events for login, dataset import, run creation, export, policy change, and deletion.
- Retention policies and authorized deletion that cover database rows, artifacts, and backups.
- Access-controlled exports and an approval step for high-risk dataset downloads.
- SSRF controls on target URLs: allowlists, blocked address ranges, and redirect revalidation, plus a Compose network boundary.
- Secrets outside images, redacted logs, and a documented rotation procedure. Secrets are environment variables passed into containers.
- Backup and restore test, deployment rollback, worker recovery, and a load test against a stated workload. `pg_dump` and `pg_restore` run inside the Postgres image via `docker compose run`.
- Production stays Docker Compose: resource limits, non-root users, health checks, pinned image versions, and additional worker containers when one worker is not enough. kubectl, Helm, and a cluster install are not part of the product.
- Staging and production configuration stay in separate Compose files. Both files use the same images.

### Exit criteria

- Tenant A cannot read tenant B’s run by changing an ID, including from a worker and an export link.
- A restore drill recovers a known run and its report.
- Rollback instructions have been executed once on staging.
- The success list in PRD section 20 is demonstrable on the deployed environment.

---

## Free deployment plan

Deploy the finished application for **$0 per month** as one Docker Compose stack. The VM installs Docker Engine and the Compose plugin, and nothing else. PostgreSQL, Redis, the API, workers, the frontend, Caddy, MinIO, Prometheus, Grafana, and Loki are containers. LLM judge calls are the only usage that can incur a charge, so production defaults to the mock adapter and optional free-tier models with a hard budget.

### Cost boundary

| Piece | Where it runs | Limit to respect |
| --- | --- | --- |
| All application services | Containers on one Oracle Cloud Always Free Ampere VM | Up to 4 OCPU and 24 GB RAM. Keep the account eligible and the instance running. |
| PostgreSQL | `postgres` container with a named volume | Disk on the VM. Backups are dump files in the MinIO container. |
| Frontend | `frontend` image. Node runs only during `docker compose build`. | Static files are served by that image. |
| TLS | `caddy` container | Ports 80 and 443 on the VM. |
| Artifacts, reports, and backups | `minio` container with a named volume | VM disk. Do not add an object-storage CLI on the host. |
| CI | GitHub Actions, jobs that only run Docker Compose | Stay inside the free private-repo minute quota. |
| Metrics and logs | `prometheus`, `grafana`, and `loki` containers | Low cardinality. Do not ship raw prompts. |
| Model calls | Mock adapter by default | Optional Groq or Gemini free tier only when a judge demo is required. |

One always-free VM running Compose is the whole production host. A Celery worker container must stay up. Do not split the frontend, database, or metrics onto services that require extra CLIs or host packages.

### Target architecture

```text
Browser
  -> VM :443 (caddy container)
       -> frontend (built and served by its image)
       -> api (FastAPI)
       -> worker (Celery)
       -> redis
       -> postgres
       -> minio
       -> prometheus
       -> grafana
       -> loki
       -> migrate (one-shot on deploy)
```

### 1. Prepare the app for this host

Do this during Version 10, after the features exist. Earlier versions keep running on local Docker Compose.

- Add `docker-compose.prod.yml` with `frontend`, `api`, `worker`, `postgres`, `redis`, `minio`, `caddy`, `prometheus`, `grafana`, `loki`, and `migrate`.
- Pin image versions. Run containers as non-root. Set memory limits so Redis, Postgres, and the worker cannot exhaust the VM.
- Read `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `CORS_ORIGINS`, and `ARTIFACT_S3_*` from the environment. `DATABASE_URL` points at the `postgres` service. `ARTIFACT_S3_*` points at the `minio` service. Commit `.env.example` only.
- The frontend Dockerfile builds the React app. `VITE_API_BASE_URL` is a build argument. The host never runs npm.
- Add `/health` on the API and a worker heartbeat query so Caddy and the recovery task can see a dead worker.
- Default `EVAL_PROVIDER=mock`. Real provider keys are optional and empty in the free deployment.

### 2. Create the free account

1. Create an Oracle Cloud account and confirm an Always Free Ampere instance in your home region. Ubuntu 24.04 is enough.
2. Create a GitHub repository and push the monorepo.

No Neon, Cloudflare, R2, Grafana Cloud, or Sentry account is required. Those jobs are containers on the VM.

### 3. Provision the VM

On the Oracle instance, the only package install is Docker:

- Open only ports 22, 80, and 443 in both the Oracle security list and the host firewall.
- Install Docker Engine and the Docker Compose plugin. Do not install Node.js, Python, PostgreSQL, Redis, nginx, or Caddy on the host.
- Create a deploy user in the `docker` group. Disable password SSH login after key login works.
- Create `/opt/evalforge` and clone the repository there.
- Create `/opt/evalforge/.env` on the server with `DATABASE_URL` for the `postgres` service, `REDIS_URL=redis://redis:6379/0`, a `SECRET_KEY` generated locally, MinIO credentials, the public origin, and empty provider keys.
- Add a 2 GB swap file so image builds do not get killed on a small free shape.

### 4. TLS and routing

- Point the domain at the VM.
- The Caddy container obtains certificates and routes `/` to the frontend container and `/api` to the API container.
- CORS allows only that public origin.
- Rate limits for `POST /api/v1/evaluations` and the login route live in the Caddy container config, which is a file in the repository.

### 5. Deploy and migrate

From `/opt/evalforge` on the VM:

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d
```

`build` compiles the frontend inside its image and installs Python dependencies inside the API and worker images. The migrate service is the only process that applies migrations. The API refuses to start schema changes on boot.

### 6. GitHub Actions

Workflows call Docker only:

- **Pull request:** `docker compose run` for unit tests and integration tests. Compose starts Postgres and Redis. No deploy, and no `setup-node` or `setup-python` step.
- **Main branch:** `docker compose build` for the pinned images, push them to GitHub Container Registry, which is free for public images and has a free private allowance. Then SSH to the VM and run the migrate and up commands above.
- **Nightly:** `docker compose run --rm cli` against the smoke dataset with `EVAL_PROVIDER=mock`. Fail the job on a quality-fail or infrastructure-fail exit code.

Store `SSH_HOST`, `SSH_KEY`, and registry credentials as Actions secrets. Database credentials stay in the VM `.env` file because Postgres is a container on that VM.

### 7. Backups and rollback

- Once a week, run `pg_dump` inside the Postgres image and upload the dump to the MinIO `backups/` prefix with a one-shot container. A cron container deletes dumps older than 14 days.
- Before each deploy, record the current image digest and git SHA in `/opt/evalforge/releases.log`.
- Rollback is: redeploy the previous image digest with Compose, and restore the dump only if a migration was destructive. Prefer expand-contract migrations so rollback does not need a restore.
- Practice one restore into a second Postgres container. Confirm a known run and report are readable. Then remove that container.

### 8. Operations on the free footprint

- The Prometheus container scrapes the API and worker. The Grafana container alerts on queue age, heartbeat loss, and 5xx rate.
- The API and worker log structured exceptions with prompts, authorization headers, and provider error bodies stripped. Loki collects those logs. No host log agent.
- Log volume stays small: one structured line per request and one per case completion.
- A scheduled container runs `celery inspect ping` every five minutes and restarts the worker container if the ping fails.
- Disk: Docker log rotation at 10 MB × 3 files. `docker system prune` weekly for unused images.

### 9. Prove the deployment

Run this once after the first production deploy and again after Version 10:

1. Sign up on the public URL served by the Caddy and frontend containers, and create a workspace.
2. Upload `sample_datasets/support-qa.jsonl`.
3. Start a mock-adapter run and confirm it leaves `queued`, finishes, and remains after `docker compose restart`.
4. Open a failed case and download the report from the MinIO container.
5. From a second account, request the first account’s run ID and confirm a 403 or 404.
6. Kill the worker container during a run and confirm recovery completes each case once.
7. Run `docker compose run --rm cli` against the public API and confirm the exit code matches the policy decision.
8. Restore the latest dump into a temporary Postgres container and read that run.

### 10. What this free setup can and cannot carry

The free deployment is a real single-organization production environment for portfolio traffic, mock evaluations, and small datasets.

Stay inside these bounds:

- One VM. Add worker capacity by increasing the Compose replica count for the worker service, still on that VM.
- VM disk for Postgres rows, MinIO reports, and backups. Keep datasets in Postgres and put only reports and dumps in MinIO.
- Mock evaluations in CI. A live judge demo uses a free model tier with the Version 8 cost budget set above zero only for that demo, then returned to zero.
- Grafana and Loki on the same VM. Drop high-cardinality labels such as raw case text.

When the VM is too small, the next paid step is a larger VM running the same Compose file, not a new set of host packages.
