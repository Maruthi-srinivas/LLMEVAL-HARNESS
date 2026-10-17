# EvalForge Product Requirements Document

**Product:** EvalForge  
**Type:** Production-oriented LLM Evaluation and Regression Testing Platform  
**Document status:** Product definition for implementation  
**Development model:** Docker-only monorepo. The only software installed on a developer or operator machine is Docker Engine and the Docker Compose plugin. Node.js, Python, pip, npm, PostgreSQL, Redis, Kafka, MinIO, migration tools, the CLI, test runners, and observability services all run inside containers. No other language runtime, database, broker, or application package is installed on the host.

---

## 1. Product vision

EvalForge helps developers determine whether an AI application is actually improving, whether its answers are reliable, why it fails, how much it costs, and whether a new version is safe enough to deploy.

It converts AI quality from an informal manual judgment into a repeatable, inspectable engineering workflow. A team can change a prompt or retrieval configuration, run both the approved baseline and the candidate against a versioned dataset, inspect regressions case by case, and let a release policy decide whether the candidate may proceed.

The product is approached as real software: identify the problem, define requirements, design the architecture, implement the evaluation engine, build the frontend and backend, test the system, and deploy it.

The most important design choice is to make the evaluation lifecycle work end to end before building advanced features such as Kafka-based event streaming or enterprise SSO.

The first milestone is not to implement every metric or integrate every model provider. It is to make the complete evaluation lifecycle reliable.

---

## 2. Problem statement

### 2.1 The problem with modern AI applications

A company builds a customer-support assistant using an LLM and retrieval-augmented generation (RAG).

1. The application receives a customer question.
2. It retrieves information from company documentation.
3. It sends the relevant context to an LLM.
4. It returns an answer.

Example:

| Step | Content |
| --- | --- |
| Customer question | "How can I reset my account password?" |
| RAG retrieval | Search the knowledge base for relevant instructions. |
| LLM generation | Generate an answer using the retrieved evidence. |
| Final answer | Instructions returned to the customer. |

Initially the application works well. Later the engineering team changes the prompt, replaces the embedding model, modifies the chunking strategy, or upgrades the LLM. Several things might then happen:

- Some answers become more accurate.
- Some previously correct answers become incorrect.
- The retriever returns irrelevant documentation.
- The model invents facts not found in the documentation.
- Response latency increases.
- Token usage and operating costs rise.
- The model ignores instructions or mishandles unsafe requests.

The application can still return HTTP 200 and appear operational even when the quality of its answers has deteriorated. Traditional API monitoring can tell you that the endpoint is responding, but not whether the response is correct. This is the gap EvalForge solves.

### 2.2 What EvalForge does

EvalForge provides a repeatable testing process for AI applications. Instead of manually asking a few questions after every change, a developer creates a dataset of test cases and runs the application against that dataset.

The platform then:

1. Executes the selected AI application against each test case.
2. Captures the generated response and execution metadata.
3. Evaluates the response using configured metrics.
4. Stores individual results and aggregate scores.
5. Compares the results with a previous version.
6. Identifies regressions and explains failures.
7. Produces a report that can be used to decide whether a release should proceed.

For example, an engineer might discover that a new prompt improved answer relevance but reduced faithfulness to retrieved evidence. EvalForge makes that tradeoff visible before the prompt reaches production.

---

## 3. Users and jobs to be done

Primary user: an AI or application engineer responsible for an LLM, RAG, or agent application.

| Job | Outcome |
| --- | --- |
| Know whether a change improved the application | Compare a candidate run with an approved baseline on a versioned dataset. |
| Know whether answers are reliable | Inspect metric scores, explanations, retrieved evidence, and individual failures. |
| Know why it failed | Separate retrieval, generation, citation, safety, provider, and evaluator failures. |
| Know what it costs | See token usage, latency, and estimated cost per run and configuration. |
| Know whether it is safe to deploy | Apply explicit release policies and receive a machine-readable decision. |

---

## 4. End-to-end product workflow

The entire application is understood through one workflow.

1. **Create a workspace and project.** The developer creates a project for a specific AI application, such as a support chatbot or document assistant.
2. **Upload an evaluation dataset.** The developer uploads questions, expected answers, supporting contexts, and optional relevant-document identifiers.
3. **Configure the AI target.** The developer chooses a model provider, registers an application endpoint or configures a supported adapter, and selects a prompt version.
4. **Configure evaluators.** The developer chooses correctness, relevance, faithfulness, latency, cost, and other applicable metrics.
5. **Create an evaluation run.** The API validates the request, creates a run record, and submits an asynchronous job.
6. **Execute the test cases.** Workers invoke the target, record outputs, and calculate scores.
7. **Inspect results.** The dashboard displays aggregate metrics, failed cases, execution traces, costs, and errors.
8. **Compare against a baseline.** The developer compares the candidate run with a previously approved run.
9. **Make a release decision.** Configured policies determine whether the candidate passes, fails, or requires manual review.

### 4.1 Canonical scenario

A team has a RAG-based engineering documentation assistant and wants to change the prompt and retrieval configuration.

They open EvalForge and create an experiment containing two configurations:

- **Baseline:** the currently approved prompt and retrieval settings.
- **Candidate:** the updated prompt and retrieval settings.

EvalForge runs both configurations against a versioned evaluation dataset. It records each answer, the retrieved documents, the evaluator scores, latency, token usage, and estimated cost.

The comparison reveals that the candidate improves correctness but causes several previously passing faithfulness cases to fail. The team opens those cases, inspects the retrieved evidence and generated answers, and determines why the regression occurred.

The configured release policy blocks the candidate because a critical threshold was violated. The developer revises the prompt and reruns the evaluation. Once the candidate meets the policy, the CI pipeline can accept the result and continue the release.

---

## 5. Product scope and version boundaries

EvalForge grows through five major releases. Each release builds on the previous one.

| Release | Main objective | Result |
| --- | --- | --- |
| V1.0 | Core evaluation | A usable web application for running and inspecting evaluations |
| V1.5 | Advanced evaluation | RAG, LLM judges, safety, and robustness metrics |
| V2.0 | Continuous evaluation | Experiments, regressions, background orchestration, and CI quality gates |
| V2.5 | Agent evaluation | LangGraph workflows, MCP tool calls, and trajectory evaluation |
| V3.0 | Enterprise platform | Multi-tenancy, governance, enterprise identity, and production scaling |

Features listed under a later release are out of scope until that release. Do not implement every metric, every model provider, Kafka, or SSO in V1.0. Later releases stay on the same container images and Compose files. They do not add a host toolchain.

---

## 6. Functional requirements

### 6.1 Workspaces and projects

- A user can create a workspace and a project for one AI application.
- A workspace owns projects, members, and shared resources.
- Resource access is authorized on the backend. Changing an ID must not grant access to another workspace's dataset or run.

### 6.2 Datasets

- A user can upload an evaluation dataset of questions, expected answers, supporting contexts, and optional relevant-document identifiers.
- Datasets are versioned and immutable. A run always references a specific version.
- Upload validation checks file size and format, parses records safely, validates required fields, reports malformed records with line numbers, normalizes permitted fields, detects duplicate IDs, saves the version transactionally, and returns an import summary.
- Large imports use bounded memory and do not load arbitrary amounts of data into one process.
- Raw files may be stored as artifacts. Normalized records are stored in PostgreSQL or an appropriately designed dataset store.
- Example record shape (JSONL, one JSON object per line):

```json
{"id":"qa-001","input":"How do I reset my password?","expected_output":"Use the password reset option on the sign-in page.","context":"Users can reset their password using the Forgot Password option.","tags":["support","factual"]}
{"id":"qa-002","input":"Can I change my registered email?","expected_output":"Follow the documented account email change process.","context":"Account email changes require verification of the new address.","tags":["support","account"]}
{"id":"qa-003","input":"What is the refund policy?","expected_output":"The answer must accurately describe the documented refund policy.","context":"Refunds are available within 30 days for eligible purchases.","tags":["support","policy"]}
```

Reference answers in examples are simplified. A real dataset defines exact expected content and evaluation criteria from the application's documented behavior.

A useful customer-support dataset includes ordinary questions, ambiguous questions, unsupported questions, and safety-related cases.

**Versioning rule.** If dataset version 1 has 100 cases and version 2 has 125, comparisons must identify the difference and either use a matched subset or label the comparison as non-equivalent. In-place edits of a dataset make historical comparisons misleading.

### 6.3 Targets

- A user can choose a model provider, register an application endpoint, configure a supported adapter, and select a prompt version.
- The same dataset can be evaluated against two prompts or two target configurations.
- The configuration used by a run is stored as a versioned reference and a reproducible snapshot. Storing only the ID of a mutable configuration is insufficient.
- For provider-hosted models, record the provider and model identifier that was returned or configured. Exact reproducibility may not be possible because providers can update models behind a stable name. The platform states that limitation.

### 6.4 Evaluators

- A user can select applicable metrics such as correctness, relevance, faithfulness, latency, and cost.
- The same output can be evaluated by multiple metrics.
- Each evaluator declares the fields it requires. The engine rejects incompatible configurations before executing expensive jobs.
- A retrieval evaluator needs retrieval information. An exact-match evaluator needs an expected output. A latency evaluator needs timing metadata.

### 6.5 Evaluation runs

`POST /api/v1/evaluations` accepts a dataset version, target configuration, evaluator configuration, and execution limits.

Request lifecycle:

1. Receive the HTTP request.
2. Authenticate and authorize the user.
3. Validate the request schema.
4. Check resource ownership and quotas.
5. Create the evaluation run in PostgreSQL.
6. Submit the job through a reliable queueing workflow.
7. Return the run ID and queued status promptly. The API does not wait for all model calls to finish.

Illustrative response. The API generates unique IDs and uses a consistent response schema:

```json
{
  "run_id": "run_8c21",
  "status": "queued",
  "message": "Evaluation accepted"
}
```

If the database transaction succeeds but job submission fails, the run must not remain queued forever. V1.0 may use a simple queue if failures are detected and recovered. A transactional outbox is introduced as the architecture matures.

### 6.6 Execution and partial failure

Execution pipeline:

1. Load the immutable dataset version.
2. Validate the run configuration.
3. Create or claim a test-case task.
4. Invoke the target adapter.
5. Capture output and execution metadata.
6. Run configured evaluators.
7. Persist the case result and scores.
8. Aggregate metrics and evaluate policies.
9. Finalize the run and generate a report.

Partial failures are first-class. For a run of 100 cases where 91 succeed, 5 fail because of provider errors, and 4 exceed a timeout:

- The nine failures are not treated as incorrect model answers.
- Failures are reported separately.
- Completed results are preserved.
- A documented run-completion policy is applied.

A run is not finalized while cases remain unresolved. Progress is persisted. A worker restart must not destroy the only record of which cases completed.

Worker lifecycle:

1. Claim the run or a batch of eligible test cases.
2. Verify that the run has not been cancelled.
3. Load the immutable dataset version and configuration snapshot.
4. Execute cases within configured concurrency limits.
5. Capture output, timing, usage, and errors.
6. Run the configured evaluators.
7. Persist each case result idempotently.
8. Update progress and heartbeat information.
9. Aggregate metrics when processing is complete.
10. Evaluate release policies and finalize the run.

### 6.7 Results, comparison, and release decisions

- Users inspect aggregate metrics, failed cases, execution traces, costs, and errors.
- Users compare a candidate run with a previously approved baseline.
- Comparison answers: which metrics improved, which regressed, which cases changed from pass to fail, whether datasets are comparable, whether latency or cost increased, whether evaluator versions and configurations were equivalent, and whether the candidate satisfies the release policy.
- If dataset versions differ, the UI warns the user.
- Policies use separate quality dimensions. A high average correctness score does not override a critical safety failure.
- Distinct outcomes are preserved: quality-policy failure, infrastructure or provider failure, human review required, and all gates passed.

### 6.8 Reports and export

- A run produces a report usable for a release decision.
- Users can export reports from the evaluation detail page.
- Later, large artifacts and reports are stored in MinIO.

---

## 7. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Asynchrony | Evaluations of thousands of cases and external API calls run in workers, not inside one HTTP request. |
| Durability | PostgreSQL is the source of truth. Redis is not the only store of important run state. Unfinished work is recoverable after a lost job or worker crash. |
| Idempotency | Case results are written idempotently. Duplicate job requests do not duplicate results. |
| Reproducibility | Every run retains dataset version, prompt or prompt hash, target snapshot, evaluator names and versions, metric configuration, threshold policy, and software version or commit identifier where relevant. |
| Separation of failures | API errors, target execution errors, evaluator errors, and quality failures are different events in the data model and UI. |
| Performance targets | Do not invent arbitrary targets. Establish them from the intended workload, then measure capacity and bottlenecks. |
| Secrets | Provider keys never live in frontend code or committed `.env` files. Credentials are redacted from logs and exceptions. Production uses a secrets manager where appropriate. Rotation is supported. |
| Sensitive content | Prompts, documents, outputs, and traces are potentially sensitive. Content capture is configurable. Sensitive fields are redacted. Raw prompts and responses are not logged automatically. |
| Security boundaries | Authentication and resource-level authorization are required before user data is exposed. Enterprise releases enforce tenant context across API handlers, background jobs, queries, and artifact downloads. |

---

## 8. System architecture

Recommended shape: a modular backend with separate background workers. This keeps the code maintainable without introducing microservices too early.

### 8.1 High-level components

```text
Frontend (React + TypeScript)
  Dashboard · Dataset management · Experiments · Reports
        |
        v
Backend API (FastAPI)
  Authentication · Validation · Authorization · Run orchestration
        |
        +----> PostgreSQL          Persistent state and results
        |
        +----> Redis + Celery      Job queue and workers
                    |
                    v
            Evaluation engine
              Dataset runner · Target adapters · Metric registry · Aggregation
                    |
                    +----> Target applications   LLMs, RAG, and agents
                    +----> Evaluators            Rules, metrics, and LLM judges
```

### 8.2 Component responsibilities

**Frontend.** Control panel for configuring evaluations and understanding results. It does not perform expensive model calls from the browser and does not contain provider API keys.

- Display projects, datasets, and configurations.
- Upload and validate datasets.
- Create evaluation runs.
- Show job progress.
- Display individual case results and metric scores.
- Compare experiment runs.
- Export reports.

**FastAPI backend.** Entry point for client requests. It validates, authorizes, saves the run configuration, creates a queued run, submits a background task, and returns promptly.

**PostgreSQL.** Source of truth for users and workspaces, datasets and dataset versions, target and evaluator configurations, evaluation runs and case results, metric scores and experiment comparisons, and release policies and audit records. A run remains inspectable after the original request completes or the worker restarts.

**Redis and Celery.** Celery workers execute background tasks. Redis is the initial message broker and may be used for selected cache or coordination workloads. The API submits jobs, workers process them, and the database records the results.

**Evaluation engine.** Independent of the API, frontend, and individual LLM provider. It takes a test case, invokes a configured target, evaluates the result, and returns a normalized record. It does not know how the dashboard is rendered or how a user authenticated.

**Supporting services, introduced only when needed:**

| Service | Purpose |
| --- | --- |
| MinIO | Large artifacts and reports |
| Kafka | Durable domain events and independent consumers |
| OpenTelemetry | Traces |
| Prometheus | Metrics |
| Grafana | Dashboards |
| Loki | Centralized logs |
| Extra worker containers | More Celery replicas in Compose when one worker is not enough |

PostgreSQL, Redis, and a worker are sufficient for the initial asynchronous architecture.

### 8.3 Monorepo layout

```text
evalforge/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── main.py
│   └── tests/
├── evaluator/
│   ├── runner.py
│   ├── adapters/
│   ├── metrics/
│   ├── datasets/
│   └── tests/
├── worker/
│   ├── Dockerfile
│   ├── tasks.py
│   └── tests/
├── frontend/
│   └── Dockerfile
├── migrations/
├── sample_datasets/
├── infrastructure/
└── docs/
```

The evaluation engine stays reusable and independent of HTTP-specific types. Business logic does not live only in FastAPI route handlers. The API, worker, evaluator, and frontend share a common release and documentation process.

---

## 9. Evaluation engine

The engine determines whether EvalForge is an evaluation platform or a dashboard that calls an LLM.

### 9.1 Three independently configurable concepts

1. **Evaluation dataset.** A versioned collection of test cases describing what the AI application should handle.
2. **Target application.** The system under test: a model API, a RAG endpoint, a custom Python adapter, or an agent workflow.
3. **Evaluators.** Independent components that measure properties of the target's output and execution.

### 9.2 Target adapter interface

A target adapter provides a common interface. An implementation might call a hosted model, invoke a RAG service over HTTP, or run a supported agent workflow. `context` may be empty for a plain LLM target. The adapter captures execution metadata, token usage, and timing where available.

This is a design sketch. A production implementation defines typed error categories, timeouts, cancellation behavior, and an explicit configuration schema.

```python
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class TargetResult:
    output: str
    context: list[str]
    metadata: dict[str, Any]

class TargetAdapter(Protocol):
    async def invoke(
        self,
        input_text: str,
        metadata: dict[str, Any],
    ) -> TargetResult:
        ...
```

### 9.3 Evaluator interface

An evaluator receives the relevant inputs and returns a standardized score.

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class EvaluationScore:
    metric_name: str
    score: float | None
    passed: bool | None
    explanation: str
    metadata: dict[str, Any]

class Evaluator:
    async def evaluate(
        self,
        case,
        prediction,
        context=None,
    ) -> EvaluationScore:
        raise NotImplementedError
```

Initial evaluator set:

- ExactMatchEvaluator
- SemanticSimilarityEvaluator
- CorrectnessEvaluator
- FaithfulnessEvaluator
- RetrievalRecallEvaluator
- CitationEvaluator
- SafetyEvaluator
- LatencyEvaluator
- StructuredOutputEvaluator

The evaluator registry (V1.5) lets each evaluator declare inputs, configuration schema, score range, failure behavior, and version.

### 9.4 Run record minimum

Every run preserves:

- Run ID and status.
- Dataset ID and version.
- Target configuration snapshot.
- Prompt version or prompt hash.
- Evaluator names and versions.
- Metric configuration and threshold policy.
- Start time and end time.
- Case-level execution outcomes.
- Token usage and latency where available.
- Error categories and sanitized error details.
- Software version or commit identifier where relevant.

---

## 10. Evaluation metrics

No single metric measures every aspect of an LLM application. Each evaluator has a defined purpose. A high score from one evaluator is not proof that an answer is factually correct.

### 10.1 Deterministic metrics

Start here. Results are reproducible for the same inputs.

| Metric | Example use |
| --- | --- |
| Exact match | Strict expected-output matching |
| Normalized match | Matching after defined whitespace or case normalization |
| Token F1 | Comparing overlapping answer tokens |
| JSON schema validation | Verifying structured output |
| Latency | Measuring execution time |
| Token usage | Tracking model input and output consumption |
| Error rate | Tracking failed invocations |

These metrics are limited. Two semantically equivalent answers may fail exact matching, and two answers with substantial token overlap may differ in factual correctness.

### 10.2 LLM-as-a-judge

Use judges for qualities that need semantic assessment. Deterministic metrics remain the default where they apply.

Example: the expected answer is "A load balancer distributes incoming requests across multiple servers." The actual answer is "It spreads traffic among backend instances so that no single server handles all requests." A strict text match fails even though the answer may be correct.

Illustrative judge output. A real judge receives the question, expected answer or rubric, actual answer, and any necessary evidence. The system validates the returned schema and handles judge failures separately from target failures.

```json
{
  "metric": "correctness",
  "score": 0.95,
  "passed": true,
  "explanation": "The response conveys the essential expected behavior.",
  "evidence": [
    "The answer describes distributing traffic among backend instances."
  ]
}
```

For important applications, compare automated judgments with human-labeled examples before trusting them as release gates. Record the judge model, rubric, and version.

### 10.3 RAG metrics

Inspect both retrieval and generation. Example: a knowledge base contains 1,000 documents and only three are relevant. The retriever returns five documents. If none contains the relevant information, the generator might hallucinate or say that it cannot find the answer. EvalForge should show whether the failure originated in retrieval, generation, or both.

| Metric | Question it answers |
| --- | --- |
| Recall@K | Did the top K retrieved results include the labeled relevant documents? |
| Precision@K | What proportion of the top K results were relevant? |
| Faithfulness | Is the generated answer supported by the retrieved evidence? |
| Answer relevance | Does the response address the question? |
| Citation correctness | Do the cited documents support the associated claims? |

These metrics need appropriate ground truth or a clearly specified judge methodology.

### 10.4 Safety metrics

Safety is a separate dimension, not hidden inside average correctness. Test cases include:

- Attempts to override system instructions.
- Requests to reveal synthetic secrets.
- Malicious instructions embedded in retrieved documents.
- Unsupported claims about account or payment information.
- Requests that should be refused under the application's policies.
- Valid requests that should not be incorrectly refused.

The last category matters. A model that refuses every question can appear safe under a simplistic refusal metric while being useless.

### 10.5 Score aggregation

A run might report separate figures such as correctness 91%, faithfulness 96%, retrieval recall@5 88%, schema validity 99%, median latency 620 ms, p95 latency 2.4 seconds, and error rate 1.5%. These are example values, not benchmark claims.

Do not collapse everything into a single average without a documented rationale. Maintain separate quality dimensions and evaluate explicit release policies against them. A higher average can conceal a serious failure in a small group of important test cases.

---

## 11. Database design

The database preserves the full history of experiments and their results. Use transactions for multi-record operations and constraints that prevent duplicate case results.

### 11.1 Entities

| Entity | Responsibility |
| --- | --- |
| Workspace | Owns projects, members, and shared resources |
| Dataset / DatasetVersion | Evaluation collection and its immutable versions |
| TestCase | Input, expected output, context, and tags |
| TargetConfig | Application or model configuration under test |
| EvaluatorConfig | Which metrics to run and how they are configured |
| EvaluationRun | Experiment configuration, state, and summary |
| CaseResult | Target output and execution outcome for a single test case |
| MetricResult | An individual metric's score, status, and explanation |
| Artifact | Reports, trace exports, and other generated files |

Later entities: experiment, comparison (baseline run and candidate run), release policy, and audit record.

### 11.2 Relationships

- One workspace contains many datasets and projects.
- One dataset has multiple immutable versions.
- One dataset version contains many test cases.
- One target configuration can be used in multiple evaluation runs.
- One evaluation run references one dataset version and one explicit evaluation configuration.
- One run contains many case results.
- One case result can have many metric results.
- One experiment comparison can reference a baseline run and a candidate run.

The configuration used by a run is stored as a versioned reference and a reproducible snapshot.

### 11.3 Error model

Persist distinct categories and sanitized details for:

- Invalid dataset.
- Unknown run ID.
- Unauthorized resource access.
- Unsupported evaluator configuration.
- Provider rate limit.
- Provider timeout.
- Worker failure.
- Cancelled run.
- Storage failure.

API request errors, target execution errors, evaluator errors, and quality failures remain distinct.

---

## 12. Frontend requirements

The frontend makes the evaluation workflow understandable and helps developers diagnose problems quickly. Include loading, error, and empty states from the beginning. Integrate with the real API.

### 12.1 Navigation

| Area | Contents |
| --- | --- |
| Overview | Recent runs, quality trends, failures, and cost |
| Datasets | Imports, dataset versions, tags, and test-case editing |
| Targets and evaluators | Model configurations, application adapters, and metric settings |
| Evaluation runs | Start runs, inspect progress, cancel, and review results |
| Experiments | Compare prompts, models, datasets, and baselines |
| Quality gates | Threshold policies and release decisions |

V1.0 pages: overview, dataset management, run creation, run detail, and case debugging. Full experiment comparison and quality-gate management follow the release that implements them, but V1.0 already stores the snapshots those screens need.

### 12.2 Overview dashboard

Show:

- Total evaluation runs.
- Successful, failed, and partially completed runs.
- Average quality scores by metric.
- Recent quality regressions.
- Median and p95 latency.
- Token usage and estimated cost.
- Recent experiment comparisons.

Do not present a single green "healthy" status when important metrics are missing or stale. Display the timestamp, scope, and status of the data being summarized.

### 12.3 Evaluation detail

This is one of the most important screens. A developer should be able to go from "faithfulness decreased" to the exact answer, retrieved context, and supporting evidence.

- Run metadata and configuration.
- Execution progress and case counts.
- Metric summary.
- Failed-case table.
- Filters by category, evaluator, status, and score.
- Expected versus actual output.
- Retrieved context and citations, when available.
- Evaluator explanations.
- Token usage, latency, and error details.
- Export and comparison actions.

### 12.4 Experiment comparison

Display the baseline and candidate side by side and answer the comparison questions in section 6.7. Warn when dataset versions differ. Do not present that difference as an unqualified model improvement.

---

## 13. Development roadmap

Complete the evaluation engine and data model before the dashboard. A reliable engine and a sound data model make every later version easier.

### 13.1 V1.0 — Complete foundation

| Step | Work |
| --- | --- |
| 1. Repository | Docker monorepo for API, worker, evaluator, frontend, and docs |
| 2. Docker environment | Frontend, API, worker, PostgreSQL, and Redis with health checks, persistent database storage, dependency startup, migrations, and environment variables. The frontend image builds the Node application. The backend image installs Python dependencies. Tests, migrations, and the sample runner are `docker compose` commands. |
| 3. Persistence | Models and migrations for users, workspaces, datasets, dataset versions, test cases, target configurations, evaluator configurations, runs, and results |
| 4. Minimal runner | Load a small sample dataset, validate configuration, invoke a mock or real adapter, run deterministic metrics, store results, and calculate a summary. Automated tests use a mock adapter and do not depend on a paid provider or the network. |
| 5. REST API | Dataset management, target configuration, evaluation submission, run status, and case results. Authentication and authorization before exposing user data. Consistent API errors. |
| 6. Workers | Celery and Redis, bounded concurrency, cancellation, task recovery, and idempotent result writes |
| 7. Frontend | Overview, dataset, run-creation, run-detail, and case-debugging pages |
| 8. Regression-ready metadata | Store configuration snapshots and version information even before the full comparison engine |

**V1.0 exit criteria**

- A developer can upload a dataset.
- A run can be created through the API or UI.
- Workers process the test cases.
- Results survive service restarts.
- Metrics and errors are distinguishable.
- A user can inspect individual results and export a report.
- The entire system starts through Docker Compose. The host has Docker Engine and the Compose plugin, and no EvalForge runtime or package installed beside them.

**V1.0 checklist**

- [ ] Create the Docker monorepo.
- [ ] Create database models and migrations.
- [ ] Implement the evaluation runner.
- [ ] Implement the first REST APIs.
- [ ] Add asynchronous execution.
- [ ] Build the first dashboard.
- [ ] Add regression comparison.
- [ ] Add production safeguards: authentication, authorization, observability, CI, and recovery tests.

The recommendation is to complete the first three checklist items before building the dashboard. Regression comparison and production safeguards are listed on the V1.0 checklist and must be present for the production-oriented success bar in section 20. Comparison depth and CI quality gates are specified in full under V2.0.

### 13.2 V1.5 — Make evaluations meaningful

| Step | Work |
| --- | --- |
| 1 | Rubric-based LLM judges for correctness, relevance, and faithfulness. Validate judge output. Record judge model, rubric, and version. |
| 2 | RAG evaluation: retrieved contexts, relevant-document labels, retrieval metrics, and citation checks |
| 3 | Versioned safety and robustness suites: prompt injection, unsupported questions, refusal behavior, and structured-output compliance |
| 4 | Evaluator registry |
| 5 | Calibration against a small human-reviewed dataset measuring agreement with human labels |

**Exit criteria.** A developer can diagnose whether a RAG failure comes from retrieval, generation, citations, or safety behavior, with metric evidence for each case.

### 13.3 V2.0 — Automate quality decisions

| Step | Work |
| --- | --- |
| 1 | Named experiments, candidate configurations, baselines, and comparisons |
| 2 | Regression analysis: matching test cases, score changes, and newly failing cases |
| 3 | Release policies: metric thresholds, hard safety requirements, acceptable error rates, and latency budgets |
| 4 | CLI image, invoked with `docker compose run`, that submits an evaluation, retrieves the final decision, and returns a meaningful exit code. CI jobs use Compose only and do not install Node.js, Python, or databases on the runner. |
| 5 | Worker scaling, scheduling, stuck-job recovery, queue limits, and cost controls |
| 6 | Correlated traces, metrics, and structured logs on the API, workers, and evaluation engine |
| 7 | Kafka only if justified: versioned domain events, outbox, idempotent consumers, and explicit retry policies |

**Exit criteria.** A prompt or code change can trigger an evaluation and produce a defensible, machine-readable release decision.

### 13.4 V2.5 — Evaluate AI agents

| Step | Work |
| --- | --- |
| 1 | Workflow adapters for a LangGraph workflow or another explicitly supported agent interface |
| 2 | Traces of nodes, tool calls, inputs, outputs, state transitions, and durations |
| 3 | Tool behavior: selection, arguments, permission boundaries, error recovery, and unnecessary calls |
| 4 | Task completion against the intended goal and constraints, not only whether the final answer sounds correct |
| 5 | Human review for ambiguous or high-risk cases. Approved labels improve datasets and rubrics. |

**Exit criteria.** A developer can inspect an agent's complete execution trajectory and determine where it failed, whether its tool use was appropriate, and whether it satisfied the task.

### 13.5 V3.0 — Enterprise platform

| Step | Work |
| --- | --- |
| 1 | Organization-scoped resources, role-based access, and cross-tenant isolation tests |
| 2 | OpenID Connect, SSO, and service accounts for automated workloads |
| 3 | Audit events, retention policies, access-controlled exports, approvals, and data handling controls |
| 4 | Scale by running more worker containers and setting Compose resource limits on the same images. Do not require a cluster manager, kubectl, or Helm on the host. |
| 5 | Backup restoration, deployment rollback, worker recovery, disaster recovery, and load capacity tests |

**Exit criteria.** Tested security boundaries, auditable release decisions, documented recovery procedures, and an operational model suitable for multiple organizations.

---

## 14. API and error contract

### 14.1 V1.0 endpoints

| Capability | Behavior |
| --- | --- |
| Dataset upload | Validate, import, and return a summary with line-level errors |
| Dataset retrieval | Read a dataset version and its cases |
| Target configuration | Create and read target configurations and prompt versions |
| Evaluation submission | `POST /api/v1/evaluations` returns queued status and run ID |
| Run status | Progress, counts, and terminal state |
| Case results | Outputs, scores, errors, and explanations |

Every request is validated. Error responses use one consistent schema.

### 14.2 Error classes

| Class | Examples | Meaning |
| --- | --- | --- |
| API request error | Invalid dataset, unknown run, unauthorized access, unsupported evaluator | The request was not accepted |
| Target execution error | Provider rate limit, provider timeout | The model or application did not produce an answer |
| Evaluator error | Judge schema failure, judge timeout | The answer exists but the metric could not be computed |
| Quality failure | Score below threshold, safety violation | The answer was produced and judged, and it did not meet the bar |
| Run control | Cancelled run, worker failure, storage failure | Execution did not complete as requested |

---

## 15. Testing strategy

EvalForge is a testing platform. If the evaluator is incorrect, the release decisions it produces may be misleading. Every test command runs in a container. Developers do not install pytest, Node, or a local database to run the suite.

### 15.1 Unit tests

Test components without external services:

- Exact-match and normalized-match calculations.
- Recall@K and Precision@K calculations.
- Metric aggregation.
- Threshold evaluation.
- Dataset validation.
- Run-state transitions.
- Cost estimation.
- Configuration compatibility.

For deterministic metrics, test normal inputs, empty inputs, malformed inputs, boundary conditions, and known expected results.

### 15.2 Integration tests

Use the Compose PostgreSQL and Redis services to verify dataset import and retrieval, database transactions, API authorization, job submission and consumption, worker result persistence, cancellation, retry behavior, and recovery from interrupted execution. The test process itself is a one-shot container.

Mock external LLM calls in most automated tests. Use a smaller, separately controlled integration suite for real provider behavior.

### 15.3 Evaluator validation tests

Create a labeled dataset where humans have identified correct answers, incorrect answers, answers with unsupported claims, relevant and irrelevant retrieved documents, and valid and invalid citations. Compare evaluator output with those labels. Measure agreement, inspect disagreement patterns, and revise the rubric where needed. A metric returning a number is not evidence that it measures the intended quality reliably.

### 15.4 Reliability tests

Deliberately test:

- Killing a worker while it is processing a run.
- Provider timeouts.
- Rate-limit responses.
- Duplicate job requests.
- Cancelling a run during execution.
- Restarting Redis.
- Making the database temporarily unavailable.
- Uploading malformed or oversized datasets.
- Delivering duplicate domain events.
- Forcing a report-generation failure.

The application must reach a consistent state, must not duplicate results, and must expose failures to users.

### 15.5 Load tests

Measure the complete system under representative workloads:

- API latency and throughput.
- Queue wait time.
- Worker concurrency.
- Database connection saturation.
- Provider throttling.
- Memory and CPU consumption.
- Run completion time.
- Error rate under load.

---

## 16. Security and data protection

Evaluation data can include prompts, retrieved documents, generated answers, and traces. Treat it as potentially sensitive.

### 16.1 Authentication and authorization

Implement authentication and resource-level authorization on the backend before exposing user data. For enterprise versions, enforce tenant context consistently across API handlers, background jobs, database queries, and artifact downloads.

### 16.2 Secrets

- Never put provider keys in frontend code.
- Never commit `.env` files containing secrets. Commit `.env.example` only.
- Redact credentials from logs and exceptions.
- Support credential rotation.
- Use a secrets manager in production where appropriate.
- Avoid returning raw provider errors that may contain sensitive information.
- Keep secrets outside images.

### 16.3 Prompt injection and tool security

Datasets and retrieved documents are untrusted input.

- Treat retrieved content as data, not trusted instructions.
- Test judge prompts against injection attempts.
- Restrict which tools an agent can invoke.
- Sandbox evaluation targets where necessary.
- Disable unsafe external network access by default.
- Avoid giving evaluation workers unnecessary production credentials.
- Use mock or isolated environments for side-effecting tools.

### 16.4 SSRF and configurable endpoints

If users can register arbitrary target URLs, the backend could access internal services. Validate destinations, restrict network access, block prohibited address ranges, and revalidate redirects. Use container or network policies as an additional boundary.

### 16.5 Retention and deletion

Define retention rules for raw uploaded datasets, prompts and model outputs, evaluation traces, judge explanations, reports and exported artifacts, and audit logs. Authorized deletion must account for backups, derived artifacts, and object storage.

---

## 17. Observability

EvalForge needs two kinds of observability.

| Kind | Question |
| --- | --- |
| Operational | Is EvalForge functioning? Are requests slow, workers stuck, queues growing, or providers failing? |
| AI quality | Is the target producing poor answers, hallucinating, using the wrong tools, or becoming more expensive? |

A healthy API can serve a low-quality model. A high-quality model can be unavailable because its provider is down.

### 17.1 Infrastructure metrics

Request count and latency, HTTP error rate, worker utilization, queue depth and queue wait time, evaluation duration, database connection usage, Redis health, provider timeout and rate-limit rates, and CPU, memory, and disk usage.

### 17.2 AI quality metrics

Correctness and faithfulness distributions, quality changes by dataset category, regression counts, retrieval quality, judge disagreement, token usage and estimated cost, latency by target configuration, tool-call failure rate, and safety-policy violations.

### 17.3 Alerts

Useful alerts point operators to the relevant run, trace, or dashboard:

- Evaluation runs remain queued beyond the expected time.
- Worker failure rate exceeds its configured threshold.
- A provider experiences sustained timeouts.
- A quality regression violates a release policy.
- An evaluation budget is exceeded.
- Database connections or queue depth approach operational limits.

---

## 18. CI/CD and release management

Continuous evaluation makes AI quality checks part of normal software development.

When a developer changes a system prompt in a pull request, the pipeline:

1. Builds the application container.
2. Runs unit and integration tests.
3. Launches the evaluation environment.
4. Executes a representative evaluation dataset.
5. Compares the results with the approved baseline.
6. Applies release policies.
7. Publishes the evaluation report.
8. Marks the pipeline successful or failed according to the policy.

```text
Code or prompt change
  -> Build and automated tests
  -> Run evaluation suite
  -> Compare candidate with baseline
  -> Apply quality and safety policies
  -> Pass: continue release
  -> Fail or review: block or request approval
```

Use a smaller smoke-test dataset for rapid pull-request feedback and a larger suite for scheduled or pre-release evaluations.

The pipeline distinguishes:

- A completed evaluation that failed its quality policy.
- An evaluation that could not finish because the provider or infrastructure failed.
- An evaluation requiring human review.
- An evaluation that passed all configured gates.

These states are not collapsed into one generic success or failure response.

---

## 19. Deployment

Docker Compose is the only deployment model for local development, CI, and production. Operators install Docker Engine and the Compose plugin. They do not install Node.js, Python, PostgreSQL, Redis, Kafka, MinIO, Caddy, Prometheus, Grafana, or application packages on the host.

### 19.1 First complete release (Docker Compose)

| Service | Purpose |
| --- | --- |
| frontend | React application, built and served by its image |
| api | FastAPI backend |
| worker | Celery evaluation worker |
| postgres | Persistent application database |
| redis | Job broker and selected caching |
| migrate | One-shot database migration process |

Later additions are extra Compose services, enabled with profiles so everyday development does not start the full stack:

- MinIO for artifact storage.
- Kafka and event consumers for durable domain events.
- OpenTelemetry Collector for telemetry processing.
- Prometheus, Grafana, and Loki for monitoring.
- Caddy for routing and TLS.

All of those are container images. None of them is a host package. Production does not add a cluster manager. Capacity is added by running more worker containers from the same images.

### 19.2 Deployment principles

- Build production images with pinned dependencies.
- Use non-root containers where practical.
- Configure health checks and resource limits.
- Use persistent storage for stateful services.
- Apply database migrations through the `migrate` container.
- Keep secrets outside the image, supplied as Compose environment variables.
- Provide startup, shutdown, and recovery instructions as Compose commands.
- Test backups and restores with one-shot containers, such as `pg_dump` inside the Postgres image.
- Keep staging and production configurations as separate Compose files.
- Roll back by redeploying the previous image digests with Compose.

### 19.3 Local development and CI

`docker compose up` starts the system. `docker compose run` executes tests, migrations, the sample evaluation, and the release-gate CLI. The frontend image runs the Node build. The backend image contains the Python environment. CI uses those same commands and does not install language runtimes or databases on the runner.

---

## 20. Definition of success

EvalForge is complete as a production-oriented portfolio project when it demonstrates:

- A working, containerized full-stack application.
- A modular and extensible evaluation engine.
- Reliable asynchronous execution.
- Multiple deterministic and LLM-based evaluators.
- RAG retrieval, faithfulness, and citation evaluation.
- Versioned datasets, prompts, and experiment configurations.
- Baseline comparison and regression detection.
- Automated CI quality gates.
- Agent and tool evaluation in the advanced release.
- Authentication, authorization, and tenant isolation appropriate to its deployment.
- Correlated logs, metrics, and traces.
- Automated tests for correctness, security, and failure recovery.
- Documented deployment, backups, and operational recovery.

The project demonstrates three kinds of engineering ability: AI evaluation expertise, backend and distributed-systems design, and production deployment discipline.

---

## 21. Mistakes to avoid

1. Building the UI before the engine works.
2. Using only LLM judges. Deterministic metrics are cheaper and often more reproducible. Use LLM judges for qualities that need semantic assessment.
3. Treating every execution error as a quality failure.
4. Adding too many technologies too early. Add Kafka when there is a genuine need for durable event streaming.
5. Ignoring reproducibility. Every run must retain the relevant dataset, prompt, target, and evaluator versions.
6. Using averages without inspecting regressions.
7. Claiming production readiness without recovery tests for worker restarts, retries, duplicate jobs, backup restoration, and authorization failures.
8. Sending sensitive data to external models without controls for prompts, documents, outputs, traces, and API credentials.

---

## 22. Requirement traceability

| ID | Requirement | Release |
| --- | --- | --- |
| EF-001 | Docker Compose is the only install surface: frontend, API, worker, PostgreSQL, Redis, and migrations start as containers, with no host runtimes | V1.0 |
| EF-002 | Immutable versioned datasets with validated JSONL import | V1.0 |
| EF-003 | Target adapter interface with mock adapter for tests | V1.0 |
| EF-004 | Deterministic evaluators and separate error categories | V1.0 |
| EF-005 | Async Celery execution with idempotent results and recovery | V1.0 |
| EF-006 | Run snapshots for dataset, prompt, target, and evaluators | V1.0 |
| EF-007 | Dashboard for datasets, runs, and case inspection, plus report export | V1.0 |
| EF-008 | Authentication and resource authorization | V1.0 |
| EF-009 | LLM judges with schema validation and recorded rubric version | V1.5 |
| EF-010 | RAG recall, precision, faithfulness, relevance, and citations | V1.5 |
| EF-011 | Safety and robustness suites, including valid requests that must not be refused | V1.5 |
| EF-012 | Evaluator registry and human-label calibration | V1.5 |
| EF-013 | Experiments, regression comparison, and release policies | V2.0 |
| EF-014 | CI quality gate with distinct pass, quality-fail, infra-fail, and review states | V2.0 |
| EF-015 | Observability for operations and AI quality | V2.0 |
| EF-016 | Agent trajectory, tool-use, and task-completion evaluation | V2.5 |
| EF-017 | Human review loop for ambiguous or high-risk cases | V2.5 |
| EF-018 | Tenant isolation, SSO, audit, retention, and operational recovery | V3.0 |
