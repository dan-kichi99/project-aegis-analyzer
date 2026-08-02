from dataclasses import replace

from app.codegen.code_block_extractor import CodeBlockExtractor
from app.codegen.code_safety_result import (
    CodeRiskCategory,
    CodeRiskLevel,
    CodeSafetyFinding,
    CodeSafetyResult,
)
from app.codegen.generated_code_result import (
    GeneratedCodeLanguage,
    GeneratedCodeResult,
)
from app.codegen.python_code_safety_analyzer import PythonCodeSafetyAnalyzer
from app.judge.confidence_estimator import ConfidenceEstimator
from app.judge.flag_extractor import FlagExtractor
from app.judge.gemini_prompt_generator import GeminiPromptGenerator
from app.judge.hypothesis_extractor import HypothesisExtractor
from app.judge.judge_result import JudgeResult
from app.judge.next_action_extractor import NextActionExtractor
from app.judge.reason_extractor import ReasonExtractor


class Judge:
    """AI生成された回答の評価を行うジャッジクラス"""

    def __init__(
        self,
        flag_extractor: FlagExtractor,
        confidence_estimator: ConfidenceEstimator,
        reason_extractor: ReasonExtractor,
        next_action_extractor: NextActionExtractor,
        hypothesis_extractor: HypothesisExtractor,
        gemini_prompt_generator: GeminiPromptGenerator,
        code_block_extractor: CodeBlockExtractor | None = None,
        code_safety_analyzer: PythonCodeSafetyAnalyzer | None = None,
    ) -> None:
        self._flag_extractor = flag_extractor
        self._confidence_estimator = confidence_estimator
        self._reason_extractor = reason_extractor
        self._next_action_extractor = next_action_extractor
        self._hypothesis_extractor = hypothesis_extractor
        self._gemini_prompt_generator = gemini_prompt_generator
        self._code_block_extractor = code_block_extractor or CodeBlockExtractor()
        self._code_safety_analyzer = (
            code_safety_analyzer or PythonCodeSafetyAnalyzer()
        )

    def evaluate(
        self,
        category: str,
        response: str,
    ) -> JudgeResult:
        """
        カテゴリとAIからの応答を受け取り、
        各抽出・推定処理を行ってJudgeResultを返す。
        """
        flag = self._flag_extractor.extract(response)

        confidence = self._confidence_estimator.estimate(
            category,
            response,
            flag,
        )

        reason = self._reason_extractor.extract(response)

        next_actions = self._next_action_extractor.extract(
            category,
            response,
        )

        hypothesis = self._hypothesis_extractor.extract(
            category,
            response,
        )

        gemini_prompt = self._gemini_prompt_generator.generate(
            category,
            response,
        )
        extracted_code = self._code_block_extractor.extract(response)
        generated_code = self._inspect_generated_code(extracted_code)

        # Flagが見つかった場合は「解決済み」として結果を統一する
        if flag is not None:
            raw_confidence = (
                confidence
                if confidence is not None
                else 0
            )

            confidence = max(raw_confidence, 90)
            hypothesis = None
            next_actions = []
            gemini_prompt = None

        return JudgeResult(
            category=category,
            answer=response,
            flag=flag,
            confidence=confidence,
            reason=reason,
            next_actions=next_actions,
            hypothesis=hypothesis,
            gemini_prompt=gemini_prompt,
            generated_code=generated_code,
        )

    def _inspect_generated_code(
        self,
        extracted: GeneratedCodeResult,
    ) -> GeneratedCodeResult | None:
        if not extracted.items:
            return None
        inspected = []
        for item in extracted.items:
            if item.language is GeneratedCodeLanguage.PYTHON:
                safety = self._code_safety_analyzer.analyze(item.code)
            else:
                safety = CodeSafetyResult(
                    parseable=False,
                    overall_risk=CodeRiskLevel.BLOCKED,
                    findings=(
                        CodeSafetyFinding(
                            category=CodeRiskCategory.UNKNOWN,
                            risk_level=CodeRiskLevel.BLOCKED,
                            message="Python以外のため静的検査の対象外です。",
                            line_number=None,
                            symbol=None,
                        ),
                    ),
                )
            inspected.append(replace(item, safety=safety))
        return GeneratedCodeResult(items=tuple(inspected))
