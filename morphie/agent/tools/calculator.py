"""
Calculator tool.

Evaluates arithmetic expressions safely by walking a parsed AST and only
allowing numeric literals, a fixed set of operators, and a small
whitelist of math functions - never a real eval()/exec() of
model-supplied text.

The AST whitelist stops code execution but not resource exhaustion:
`9**9**9**9` is "just arithmetic" yet would pin a server thread and eat
all memory. So the expression length, exponents, and the *size of a
power's result* are all bounded, and complex results are refused.
"""

from __future__ import annotations

import ast
import math
import operator

from .base import Tool

MAX_EXPRESSION_CHARS = 200
MAX_EXPONENT = 10_000
MAX_RESULT_DIGITS = 300  # about the range of a double; anything bigger is refused
_TOO_LARGE = "That number is too large to calculate."


def _safe_pow(base, exponent):
    # 0, 1 and -1 stay trivial however large the exponent is.
    if base not in (0, 1, -1):
        if abs(exponent) > MAX_EXPONENT:
            raise ValueError(_TOO_LARGE)
        # digits in the result ~= |exponent| * log10(|base|); check before computing.
        if abs(exponent) * math.log10(abs(base)) > MAX_RESULT_DIGITS:
            raise ValueError(_TOO_LARGE)
    return operator.pow(base, exponent)


_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _safe_pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Whitelisted functions only - never arbitrary attribute/name resolution.
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "pow": _safe_pow,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
}


def _eval_node(node: ast.AST):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("Only numbers are allowed in expressions.")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("Only sqrt, abs, round, pow, min, max, floor, ceil, log, log10 are allowed.")
        if node.keywords:
            raise ValueError("Keyword arguments are not supported.")
        args = [_eval_node(arg) for arg in node.args]
        return _FUNCTIONS[node.func.id](*args)
    raise ValueError("Unsupported expression - only numbers, + - * / // % ** , parentheses, and the allowed functions are supported.")


def calculate(expression: str) -> str:
    shown = expression[:60] + ("..." if len(expression) > 60 else "")
    if len(expression) > MAX_EXPRESSION_CHARS:
        return f"Could not evaluate that: the expression is too long (max {MAX_EXPRESSION_CHARS} characters)."
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree.body)
        if isinstance(result, complex):
            raise ValueError("The result isn't a real number.")
        return str(result)
    except ZeroDivisionError:
        return f"Cannot evaluate '{shown}': division by zero."
    except (OverflowError, MemoryError):
        return f"Could not evaluate '{shown}': {_TOO_LARGE}"
    except Exception as exc:  # noqa: BLE001 - includes SyntaxError/RecursionError from hostile input
        return f"Could not evaluate '{shown}': {exc}"


calculator_tool = Tool(
    name="calculator",
    description=(
        "Evaluate a plain arithmetic expression. Supports + - * / // ** and "
        "parentheses, and the functions sqrt(), abs(), round(), pow(), min(), "
        "max(), floor(), ceil(), log(), log10(). Convert percentages to decimal "
        "multiplication yourself first (e.g. '18% of 74500' -> '74500 * 0.18') - "
        "'%' here means the modulo operator, not percent. Use this tool for any "
        "math instead of computing it yourself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A math expression, e.g. '(12 + 8) * 3' or 'sqrt(144) + 20'.",
            }
        },
        "required": ["expression"],
    },
    handler=calculate,
)
