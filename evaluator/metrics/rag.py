"""Retrieval metrics and rubric judges. Judges use the mock adapter."""

from __future__ import annotations

import json

from evaluator.adapters.judge import JUDGE_MODEL, RUBRIC_VERSION, MockJudgeAdapter
from evaluator.metrics.deterministic import Evaluator, _metric_error
from evaluator.types import EvaluationCase, EvaluationScore, TargetResult

_K = 5


def _top(prediction: TargetResult) -> list[dict]:
    documents = [item for item in prediction.documents if isinstance(item, dict) and isinstance(item.get("id"), str)]
    return documents[:_K]


def _ids(documents: list[dict]) -> list[str]:
    return [item["id"] for item in documents]


def _fraction(name: str, score: float, explanation: str) -> EvaluationScore:
    passed = score == 1.0
    return EvaluationScore(
        metric_name=name,
        score=score,
        passed=passed,
        explanation=explanation,
        status="passed" if passed else "failed",
    )


class RecallAt5Evaluator(Evaluator):
    name = "recall_at_5"
    version = "1"
    required_fields = frozenset({"relevant_document_ids"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        relevant = set(case.relevant_document_ids)
        found = relevant.intersection(_ids(_top(prediction)))
        score = len(found) / len(relevant)
        return _fraction(self.name, score, f"{len(found)} of {len(relevant)} relevant documents were retrieved")


class PrecisionAt5Evaluator(Evaluator):
    name = "precision_at_5"
    version = "1"
    required_fields = frozenset({"relevant_document_ids"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        top = _top(prediction)
        if not top:
            return _metric_error(self.name, "No retrieved documents")
        relevant = set(case.relevant_document_ids)
        found = [item for item in _ids(top) if item in relevant]
        score = len(found) / len(top)
        return _fraction(self.name, score, f"{len(found)} of {len(top)} retrieved documents were relevant")


class CitationCorrectnessEvaluator(Evaluator):
    name = "citation_correctness"
    version = "1"
    required_fields = frozenset({"citations"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        retrieved = set(_ids(_top(prediction)))
        relevant = set(case.relevant_document_ids)
        passed = 0
        for citation in case.citations:
            document_id = citation.get("document_id")
            if document_id in retrieved and document_id in relevant:
                passed += 1
        score = passed / len(case.citations)
        return _fraction(self.name, score, f"{passed} of {len(case.citations)} citations name a retrieved relevant document")


class _JudgeEvaluator(Evaluator):
    version = "1"
    required_fields: frozenset[str] = frozenset()
    config_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "judge_model": {"type": "string"},
            "rubric": {"type": "string"},
            "rubric_version": {"type": "string"},
        },
        "required": ["judge_model", "rubric", "rubric_version"],
    }
    failure_behavior = (
        "The judge boolean passed decides the quality result. "
        "Invalid JSON, a missing passed field, or a judge timeout is metric_error. "
        "Faithfulness with no retrieved documents is metric_error, not an unsupported answer."
    )

    async def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        if self.name == "faithfulness" and not _top(prediction):
            return _metric_error(self.name, "No retrieved documents")
        judged = await MockJudgeAdapter().invoke(
            case.input_text,
            {
                "case_key": case.case_key,
                "metric": self.name,
                "behavior": prediction.metadata.get("behavior"),
            },
        )
        if judged.error_category:
            return _metric_error(self.name, judged.error_detail or judged.error_category)
        try:
            payload = json.loads(judged.output)
        except json.JSONDecodeError:
            return _metric_error(self.name, "Judge returned invalid JSON")
        if not isinstance(payload, dict) or not isinstance(payload.get("passed"), bool):
            return _metric_error(self.name, "Judge JSON is missing passed")
        score = payload.get("score")
        numeric = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        explanation = payload.get("explanation") if isinstance(payload.get("explanation"), str) else ""
        passed = payload["passed"]
        return EvaluationScore(
            metric_name=self.name,
            score=numeric,
            passed=passed,
            explanation=explanation,
            metadata={
                "judge_model": JUDGE_MODEL,
                "rubric": self.name,
                "rubric_version": RUBRIC_VERSION,
                "evidence": evidence,
            },
            status="passed" if passed else "failed",
        )


class TaskCompletionEvaluator(_JudgeEvaluator):
    name = "task_completion"
    required_fields = frozenset()

    async def evaluate(self, case: EvaluationCase, prediction: TargetResult):
        score = await super().evaluate(case, prediction)
        score.metadata = {
            **score.metadata,
            "goal": case.goal,
            "constraints": list(case.constraints),
        }
        return score


class CorrectnessEvaluator(_JudgeEvaluator):
    name = "correctness"


class AnswerRelevanceEvaluator(_JudgeEvaluator):
    name = "answer_relevance"


class FaithfulnessEvaluator(_JudgeEvaluator):
    name = "faithfulness"
