from typing import Any


# ============================================================
# Result Object
# ============================================================

class MCPScoringResult:
    """
    Result of 3D scoring for MCP tasks.
    Dimensions:
    - Action Match
    - Argument Match
    - Efficiency
    """

    def __init__(
        self,
        action_score: float,
        argument_score: float,
        efficiency_score: float = 1.0,
        weights: dict[str, float] | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.action_score = action_score
        self.argument_score = argument_score
        self.efficiency_score = efficiency_score

        # Default weights or normalize provided weights
        if weights:
            self.weights = {
                "action": weights.get("action", 0.5),
                "argument": weights.get("argument", weights.get("state", 0.4)),
                "efficiency": weights.get("efficiency", 0.1),
            }
        else:
            self.weights = {
                "action": 0.5,
                "argument": 0.4,
                "efficiency": 0.1,
            }

        self.total_score = (
            self.action_score * self.weights["action"]
            + self.argument_score * self.weights["argument"]
            + self.efficiency_score * self.weights["efficiency"]
        )

        self.success = self.total_score >= 0.5
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_score": round(self.total_score, 4),
            "scores": {
                "action": round(self.action_score, 4),
                "argument": round(self.argument_score, 4),
                "efficiency": round(self.efficiency_score, 4),
            },
            "weights": self.weights,
            "details": self.details,
            "debug_info": {
                "tool_calls_with_args": [
                    {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "has_args": bool(tc["arguments"]),
                    }
                    for tc in self.details.get("tool_calls_full", [])
                ]
            }
        }


# ============================================================
# MCP Scorer
# ============================================================

class MCPScorer:
    """
    Deterministic 2D scorer for MCP-based agents.

    Dimensions:
    - Action Match: Required tools used?
    - Argument Match: Tool arguments correct?
    """

    def __init__(self, task: dict[str, Any]):
        self.task = task
        self.success_criteria = task.get("success_criteria", {})

        self.required_tools = self.success_criteria.get(
            "action_match", {}
        ).get("required_tools", [])

        self.argument_checks = self.success_criteria.get(
            "argument_match", []
        )

        self.efficiency_config = self.success_criteria.get(
            "efficiency", {}
        )

        self.weights = task.get("scoring_weights", {
            "action": 0.5,
            "argument": 0.4,
            "efficiency": 0.1,
        })

        self.tool_calls: list[dict[str, Any]] = []

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any = None,
    ) -> None:
        """
        Record a tool call with its arguments and result.
        
        Args:
            tool_name: Name of the tool that was called
            arguments: Dictionary of arguments passed to the tool
            result: Optional result returned by the tool
        """
        self.tool_calls.append({
            "name": tool_name,
            "arguments": arguments if arguments else {},
            "result": result,
        })

    def calculate_score(self) -> MCPScoringResult:
        action_score, action_details = self._calculate_action_score()
        argument_score, argument_details = self._calculate_argument_score()
        efficiency_score, efficiency_details = self._calculate_efficiency_score()

        return MCPScoringResult(
            action_score=action_score,
            argument_score=argument_score,
            efficiency_score=efficiency_score,
            weights=self.weights,
            details={
                "action": action_details,
                "argument": argument_details,
                "efficiency": efficiency_details,
                "tool_calls": [tc["name"] for tc in self.tool_calls],
                "tool_calls_full": self.tool_calls,
            },
        )

    # --------------------------------------------------------
    # Action Match
    # --------------------------------------------------------

    def _calculate_action_score(self) -> tuple[float, dict[str, Any]]:
        if not self.required_tools:
            return 1.0, {"message": "No required tools specified"}

        actual_tools = {tc["name"] for tc in self.tool_calls}
        required_set = set(self.required_tools)

        matched = required_set & actual_tools
        missing = required_set - actual_tools

        score = len(matched) / len(required_set)

        return score, {
            "required": list(required_set),
            "matched": list(matched),
            "missing": list(missing),
        }

    # --------------------------------------------------------
    # Argument Match
    # --------------------------------------------------------

    def _calculate_argument_score(self) -> tuple[float, dict[str, Any]]:
        if not self.argument_checks:
            return 1.0, {"message": "No argument checks defined"}

        passed = []
        failed = []

        for check in self.argument_checks:
            tool = check["tool"]
            arg = check["arg"]
            operator = check.get("operator", "exists")
            expected = check.get("value")

            calls = [tc for tc in self.tool_calls if tc["name"] == tool]
            if not calls:
                failed.append({
                    "tool": tool,
                    "arg": arg,
                    "reason": "tool_not_called",
                })
                continue

            ok = False
            actual = None
            failure_reason = None

            for tc in calls:
                # Get the actual value from arguments
                actual = self._get_nested_value(tc["arguments"], arg)
                
                # Check if argument exists in the call
                if actual is None and arg not in str(tc["arguments"]):
                    failure_reason = "argument_missing"
                    continue
                
                # Evaluate the argument
                if self._evaluate(actual, operator, expected):
                    ok = True
                    break
                else:
                    failure_reason = f"argument_invalid (expected {operator} {expected})"

            if ok:
                passed.append({"tool": tool, "arg": arg, "value": actual})
            else:
                failed.append({
                    "tool": tool,
                    "arg": arg,
                    "expected": f"{operator} {expected}" if expected else operator,
                    "actual": actual,
                    "reason": failure_reason or "argument_invalid",
                })

        score = len(passed) / len(self.argument_checks)

        return score, {
            "passed": passed,
            "failed": failed,
            "summary": f"{len(passed)}/{len(self.argument_checks)} checks passed",
        }

    # --------------------------------------------------------
    # Efficiency Score
    # --------------------------------------------------------

    def _calculate_efficiency_score(self) -> tuple[float, dict[str, Any]]:
        """Calculate efficiency score based on number of tool calls."""
        if not self.efficiency_config:
            return 1.0, {"message": "No efficiency criteria defined"}

        optimal_steps = self.efficiency_config.get("optimal_steps", 1)
        max_steps = self.efficiency_config.get("max_steps", optimal_steps * 2)
        actual_steps = len(self.tool_calls)

        if actual_steps <= optimal_steps:
            # Perfect or better - 100%
            score = 1.0
        elif actual_steps >= max_steps:
            # At or over max - 0%
            score = 0.0
        else:
            # Linear interpolation between optimal and max
            # optimal = 100%, max = 0%
            score = 1.0 - (actual_steps - optimal_steps) / (max_steps - optimal_steps)

        return score, {
            "optimal_steps": optimal_steps,
            "max_steps": max_steps,
            "actual_steps": actual_steps,
            "score": round(score, 4),
        }

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def _get_nested_value(self, data: dict[str, Any], path: str) -> Any:
        if not path:
            return data

        value = data
        for key in path.split("."):
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _evaluate(self, actual: Any, operator: str, expected: Any) -> bool:
        """Evaluate argument value against expected criteria."""
        match operator:
            case "exists":
                # Argument just needs to exist (can be any value except None)
                return actual is not None
            case "equals":
                # Exact match required
                return actual == expected
            case "contains":
                # String containment check
                return isinstance(actual, str) and expected in actual
            case "not_empty":
                # Value must exist and not be empty
                if actual is None:
                    return False
                if isinstance(actual, str):
                    return len(actual.strip()) > 0
                if isinstance(actual, (list, dict)):
                    return len(actual) > 0
                return actual not in (None, "", [], {})
            case "is_email":
                # Basic email validation
                return isinstance(actual, str) and "@" in actual and "." in actual
            case "is_number":
                # Numeric value check
                return isinstance(actual, (int, float))
            case "greater_than":
                # Numeric comparison
                try:
                    return float(actual) > float(expected)
                except (ValueError, TypeError):
                    return False
            case "less_than":
                # Numeric comparison
                try:
                    return float(actual) < float(expected)
                except (ValueError, TypeError):
                    return False
            case _:
                # Unknown operator - fail safe
                return False


# ============================================================
# Convenience Function
# ============================================================

def score_task(
    task: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    scorer = MCPScorer(task)

    for tc in tool_calls:
        scorer.record_tool_call(
            tool_name=tc.get("name"),
            arguments=tc.get("arguments", {}),
            result=tc.get("result"),
        )

    return scorer.calculate_score().to_dict()
