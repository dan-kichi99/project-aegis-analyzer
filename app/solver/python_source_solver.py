import ast
import string

from app.judge.flag_extractor import FlagExtractor
from app.solver.python_source_result import (
    MAX_PYTHON_SOURCE_CANDIDATES,
    MAX_PYTHON_SOURCE_PREVIEW,
    PythonSourceCandidate,
    PythonSourceResult,
)
from app.solver.universal_encoding_solver import UniversalEncodingSolver

MAX_PYTHON_SOURCE_INPUT = 100_000
MAX_PYTHON_ASSIGNMENTS = 100
MAX_PYTHON_EVALUATION_DEPTH = 10
MAX_PYTHON_GENERATED_TEXT = 10_000
_PYTHON_MARKERS = (
    "def ", "import ", "from ", "if __name__", "print(", "input(",
    "return ", "for ", "while ", "bytes(", "bytearray(", "chr(",
    "ord(", "base64", "codecs", ".decode(", ".encode(", "[::-1]",
    "join(",
)
_TRUSTED_NAMES = ("flag", "secret", "password", "answer", "token")


class PythonSourceSolver:
    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()
        self._encoding_solver = UniversalEncodingSolver()

    def solve(
        self, text: str, source: str, *, python_extension: bool = False
    ) -> PythonSourceResult | None:
        if not text:
            return None
        truncated = len(text) > MAX_PYTHON_SOURCE_INPUT
        bounded = text[:MAX_PYTHON_SOURCE_INPUT]
        if not python_extension and sum(item in bounded for item in _PYTHON_MARKERS) < 2:
            return None
        try:
            tree = ast.parse(bounded)
        except SyntaxError:
            return None
        assignments = sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Assign)),
            key=lambda node: (node.lineno, node.col_offset),
        )[:MAX_PYTHON_ASSIGNMENTS]
        truncated = truncated or len(assignments) >= MAX_PYTHON_ASSIGNMENTS
        environment: dict[str, object] = {}
        methods: dict[str, str] = {}
        prefixes = self._infer_prefixes(tree)
        candidates: list[PythonSourceCandidate] = []
        seen_flags: set[str] = set()
        for assignment in assignments:
            if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
                continue
            name = assignment.targets[0].id
            evaluated = self._evaluate(assignment.value, environment, 0)
            if evaluated is None:
                continue
            value, method = evaluated
            environment[name] = value
            methods[name] = method
            if not isinstance(value, str):
                continue
            flag = self._flag(value)
            if (
                flag is not None
                and method == "python_direct_flag"
                and not self._trusted(name)
            ):
                flag = None
            prefix = self._prefix(value) if flag else None
            if flag is None and self._trusted(name):
                for inferred in prefixes:
                    flag = self._flag(f"{inferred}{value}}}")
                    if flag is not None:
                        prefix = inferred
                        break
            if flag is None or flag in seen_flags:
                continue
            seen_flags.add(flag)
            body = flag[len(prefix) : -1] if prefix else None
            preview = value[:MAX_PYTHON_SOURCE_PREVIEW]
            candidates.append(
                PythonSourceCandidate(
                    source=source,
                    method=method,
                    expression_type=type(assignment.value).__name__,
                    variable_name=name,
                    value_preview=preview,
                    prefix=prefix,
                    body=body,
                    flag_candidate=flag,
                    line_number=assignment.lineno,
                    confidence=95 if method == "python_direct_flag" else 90,
                    truncated=(
                        truncated or len(value) > MAX_PYTHON_SOURCE_PREVIEW
                    ),
                )
            )
            if len(candidates) >= MAX_PYTHON_SOURCE_CANDIDATES:
                return PythonSourceResult(tuple(candidates), True)
        if not candidates:
            return None
        return PythonSourceResult(tuple(candidates), truncated)

    def _evaluate(
        self, node: ast.AST, environment: dict[str, object], depth: int
    ) -> tuple[object, str] | None:
        if depth > MAX_PYTHON_EVALUATION_DEPTH:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
            return node.value, "python_direct_flag"
        if isinstance(node, ast.Name):
            value = environment.get(node.id)
            return (value, "python_string_concat") if value is not None else None
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [self._evaluate(item, environment, depth + 1) for item in node.elts]
            if any(item is None or not isinstance(item[0], int) for item in values):
                return None
            return [item[0] for item in values if item is not None], "python_bytes"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._evaluate(node.left, environment, depth + 1)
            right = self._evaluate(node.right, environment, depth + 1)
            if left and right and isinstance(left[0], str) and isinstance(right[0], str):
                value = left[0] + right[0]
                if len(value) <= MAX_PYTHON_GENERATED_TEXT:
                    return value, "python_string_concat"
            return None
        if isinstance(node, ast.Subscript) and self._is_reverse_slice(node.slice):
            value = self._evaluate(node.value, environment, depth + 1)
            if value and isinstance(value[0], str):
                return value[0][::-1], "python_reverse"
            return None
        if isinstance(node, ast.Call):
            return self._evaluate_call(node, environment, depth + 1)
        return None

    def _evaluate_call(self, node: ast.Call, environment, depth):
        if isinstance(node.func, ast.Name) and node.func.id == "chr" and len(node.args) == 1:
            item = self._evaluate(node.args[0], environment, depth)
            if item and isinstance(item[0], int) and 0 <= item[0] <= 0x10FFFF:
                char = chr(item[0])
                if char.isprintable():
                    return char, "python_chr_join"
            return None
        if self._is_join(node):
            return self._evaluate_join(node, environment, depth)
        if self._call_name(node.func) in {"bytes", "bytearray"} and len(node.args) == 1:
            return self._evaluate_bytes(node.args[0], environment, depth)
        if self._call_name(node.func) in {"bytes.fromhex", "bytearray.fromhex"}:
            return self._evaluate_fromhex(node, environment, depth)
        if self._call_name(node.func).startswith("base64.") and len(node.args) == 1:
            return self._evaluate_base(node, environment, depth)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "decode":
            if node.args and not (
                len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "utf-8"
            ):
                return None
            return self._evaluate(node.func.value, environment, depth)
        return None

    def _evaluate_join(self, node, environment, depth):
        if len(node.args) != 1:
            return None
        values = []
        argument = node.args[0]
        if isinstance(argument, (ast.List, ast.Tuple)):
            values = [self._evaluate(item, environment, depth) for item in argument.elts]
        elif isinstance(argument, ast.GeneratorExp) and len(argument.generators) == 1:
            generator = argument.generators[0]
            source = self._evaluate(generator.iter, environment, depth)
            if not source or not isinstance(source[0], list) or generator.ifs:
                return None
            if not isinstance(generator.target, ast.Name):
                return None
            for item in source[0]:
                local = dict(environment)
                local[generator.target.id] = item
                values.append(self._evaluate(argument.elt, local, depth))
        if not values or any(item is None or not isinstance(item[0], str) for item in values):
            return None
        value = "".join(item[0] for item in values if item is not None)
        return (value, "python_chr_join") if len(value) <= MAX_PYTHON_GENERATED_TEXT else None

    def _evaluate_bytes(self, argument, environment, depth):
        xor_value = self._evaluate_xor_generator(argument, environment, depth)
        if xor_value is not None:
            return xor_value, "python_xor"
        values = self._evaluate(argument, environment, depth)
        if values and isinstance(values[0], list) and all(
            isinstance(item, int) and 0 <= item <= 255 for item in values[0]
        ):
            try:
                return bytes(values[0]).decode("utf-8"), "python_bytes"
            except UnicodeDecodeError:
                return None
        return None

    def _evaluate_xor_generator(self, node, environment, depth):
        if not isinstance(node, ast.GeneratorExp) or len(node.generators) != 1:
            return None
        generator = node.generators[0]
        if generator.ifs or not isinstance(generator.target, ast.Name):
            return None
        if not isinstance(node.elt, ast.BinOp) or not isinstance(node.elt.op, ast.BitXor):
            return None
        values = self._evaluate(generator.iter, environment, depth)
        if not values or not isinstance(values[0], list):
            return None
        variable = generator.target.id
        if isinstance(node.elt.left, ast.Name) and node.elt.left.id == variable:
            key_node = node.elt.right
        elif isinstance(node.elt.right, ast.Name) and node.elt.right.id == variable:
            key_node = node.elt.left
        else:
            return None
        key = self._evaluate(key_node, environment, depth)
        if not key or not isinstance(key[0], int) or not 0 <= key[0] <= 255:
            return None
        if not all(isinstance(item, int) and 0 <= item <= 255 for item in values[0]):
            return None
        try:
            return bytes(item ^ key[0] for item in values[0]).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _evaluate_fromhex(self, node, environment, depth):
        if len(node.args) != 1:
            return None
        value = self._evaluate(node.args[0], environment, depth)
        if not value or not isinstance(value[0], str):
            return None
        try:
            return bytes.fromhex(value[0]).decode("utf-8"), "python_fromhex"
        except (UnicodeDecodeError, ValueError):
            return None

    def _evaluate_base(self, node, environment, depth):
        value = self._evaluate(node.args[0], environment, depth)
        if not value or not isinstance(value[0], str):
            return None
        expected = self._call_name(node.func).removeprefix("base64.").replace("decode", "")
        for method, output in self._encoding_solver.decode(value[0]):
            aliases = {"base64": "b64", "urlsafe_base64": "urlsafe_b64", "base32": "b32", "base85": "b85", "ascii85": "a85"}
            if aliases.get(method) == expected:
                return output, "python_base64"
        return None

    def _infer_prefixes(self, tree: ast.AST) -> tuple[str, ...]:
        values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                prefix = node.value
                if self._valid_prefix(prefix) and prefix not in values:
                    values.append(prefix)
        return tuple(values)

    def _flag(self, value: str) -> str | None:
        known = self._flag_extractor.extract(value)
        if known == value:
            return known
        prefix = self._prefix(value)
        return value if prefix is not None else None

    def _prefix(self, value: str) -> str | None:
        if not value.endswith("}") or "{" not in value:
            return None
        prefix, body = value.split("{", 1)
        prefix += "{"
        if not body[:-1] or "{" in body or not self._valid_prefix(prefix):
            return None
        return prefix

    @staticmethod
    def _valid_prefix(value: str) -> bool:
        if not value.endswith("{") or not 3 <= len(value) - 1 <= 32:
            return False
        return all(char in string.ascii_letters + string.digits + "_-" for char in value[:-1])

    @staticmethod
    def _trusted(name: str) -> bool:
        lowered = name.casefold()
        return any(marker in lowered for marker in _TRUSTED_NAMES)

    @staticmethod
    def _is_reverse_slice(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Slice)
            and node.lower is None
            and node.upper is None
            and isinstance(node.step, ast.UnaryOp)
            and isinstance(node.step.op, ast.USub)
            and isinstance(node.step.operand, ast.Constant)
            and node.step.operand.value == 1
        )

    @staticmethod
    def _is_join(node: ast.Call) -> bool:
        return isinstance(node.func, ast.Attribute) and node.func.attr == "join"

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = PythonSourceSolver._call_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""
