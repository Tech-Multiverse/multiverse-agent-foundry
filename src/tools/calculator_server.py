import ast
import operator

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("multiverse-calculator")
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate_expression(expression: str) -> float | int:
    def evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](evaluate(node.operand))
        raise ValueError("Only numeric literals and arithmetic operators are allowed")

    if len(expression) > 200:
        raise ValueError("Expression is too long")
    return evaluate(ast.parse(expression, mode="eval").body)


@mcp.tool(name="calculator")
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression without executing code."""
    return str(evaluate_expression(expression))


if __name__ == "__main__":
    mcp.run(transport="stdio")
