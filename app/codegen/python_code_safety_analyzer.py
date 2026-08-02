import ast

from app.codegen.code_safety_result import (
    CodeRiskCategory,
    CodeRiskLevel,
    CodeSafetyFinding,
    CodeSafetyResult,
)

MAX_FINDINGS = 100
_RISK_ORDER = {
    CodeRiskLevel.LOW: 0,
    CodeRiskLevel.MEDIUM: 1,
    CodeRiskLevel.HIGH: 2,
    CodeRiskLevel.BLOCKED: 3,
}
_SAFE_IMPORTS = {
    "base64",
    "binascii",
    "collections",
    "hashlib",
    "itertools",
    "math",
    "re",
    "string",
    "struct",
}
_BLOCKED_IMPORTS = {
    "asyncio.subprocess",
    "ctypes",
    "multiprocessing",
    "pty",
    "resource",
    "signal",
    "socket",
    "subprocess",
    "winreg",
}
_HIGH_IMPORTS = {
    "ftplib",
    "glob",
    "http",
    "keyring",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "smtplib",
    "telnetlib",
    "tempfile",
    "urllib",
    "webbrowser",
}
_BLOCKED_CALLS = {
    "__import__": CodeRiskCategory.DYNAMIC_EXECUTION,
    "compile": CodeRiskCategory.DYNAMIC_EXECUTION,
    "eval": CodeRiskCategory.DYNAMIC_EXECUTION,
    "exec": CodeRiskCategory.DYNAMIC_EXECUTION,
    "os.popen": CodeRiskCategory.PROCESS,
    "os.system": CodeRiskCategory.PROCESS,
    "socket.socket": CodeRiskCategory.NETWORK,
    "subprocess.Popen": CodeRiskCategory.PROCESS,
    "subprocess.call": CodeRiskCategory.PROCESS,
    "subprocess.check_call": CodeRiskCategory.PROCESS,
    "subprocess.check_output": CodeRiskCategory.PROCESS,
    "subprocess.run": CodeRiskCategory.PROCESS,
}
_HIGH_CALLS = {
    "ftplib.FTP": CodeRiskCategory.NETWORK,
    "getpass.getpass": CodeRiskCategory.ENVIRONMENT,
    "http.client": CodeRiskCategory.NETWORK,
    "os.remove": CodeRiskCategory.FILE_SYSTEM,
    "os.rename": CodeRiskCategory.FILE_SYSTEM,
    "os.replace": CodeRiskCategory.FILE_SYSTEM,
    "os.rmdir": CodeRiskCategory.FILE_SYSTEM,
    "os.unlink": CodeRiskCategory.FILE_SYSTEM,
    "pathlib.Path.unlink": CodeRiskCategory.FILE_SYSTEM,
    "pathlib.Path.write_bytes": CodeRiskCategory.FILE_SYSTEM,
    "pathlib.Path.write_text": CodeRiskCategory.FILE_SYSTEM,
    "requests.get": CodeRiskCategory.NETWORK,
    "requests.post": CodeRiskCategory.NETWORK,
    "shutil.rmtree": CodeRiskCategory.FILE_SYSTEM,
    "smtplib.SMTP": CodeRiskCategory.NETWORK,
    "urllib.request.urlopen": CodeRiskCategory.NETWORK,
}
_MEDIUM_CALLS = {
    "delattr": CodeRiskCategory.INTROSPECTION,
    "getattr": CodeRiskCategory.INTROSPECTION,
    "globals": CodeRiskCategory.INTROSPECTION,
    "locals": CodeRiskCategory.INTROSPECTION,
    "pathlib.Path.read_bytes": CodeRiskCategory.FILE_SYSTEM,
    "pathlib.Path.read_text": CodeRiskCategory.FILE_SYSTEM,
    "setattr": CodeRiskCategory.INTROSPECTION,
    "vars": CodeRiskCategory.INTROSPECTION,
}


class PythonCodeSafetyAnalyzer:
    """Pythonコードを実行せず、AST上の明確な危険候補を検出する。"""

    def analyze(self, code: str) -> CodeSafetyResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            finding = CodeSafetyFinding(
                category=CodeRiskCategory.SYNTAX,
                risk_level=CodeRiskLevel.BLOCKED,
                message="Python構文を解析できませんでした。",
                line_number=error.lineno,
                symbol=None,
            )
            return CodeSafetyResult(False, CodeRiskLevel.BLOCKED, (finding,))

        visitor = _SafetyVisitor()
        visitor.visit(tree)
        findings = visitor.results()
        overall = max(
            (finding.risk_level for finding in findings),
            key=_RISK_ORDER.__getitem__,
            default=CodeRiskLevel.LOW,
        )
        return CodeSafetyResult(True, overall, findings)


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}
        self._findings: dict[
            tuple[int | None, CodeRiskCategory, str | None], CodeSafetyFinding
        ] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]
            self._aliases[local_name] = (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            self._check_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        self._check_import(module, node.lineno)
        for alias in node.names:
            local_name = alias.asname or alias.name
            self._aliases[local_name] = f"{module}.{alias.name}".strip(".")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        symbol = self._resolved_name(node.func)
        if symbol == "open":
            self._check_open(node)
        elif symbol.endswith((".write", ".writelines")):
            self._add(
                CodeRiskCategory.FILE_SYSTEM,
                CodeRiskLevel.HIGH,
                "ファイル書き込みにつながる呼び出しです。",
                node.lineno,
                symbol,
            )
        elif symbol in _BLOCKED_CALLS:
            self._add(
                _BLOCKED_CALLS[symbol],
                CodeRiskLevel.BLOCKED,
                "実行を禁止すべき危険な呼び出しです。",
                node.lineno,
                symbol,
            )
        elif symbol in _HIGH_CALLS:
            self._add(
                _HIGH_CALLS[symbol],
                CodeRiskLevel.HIGH,
                "高い危険性がある呼び出しです。",
                node.lineno,
                symbol,
            )
        elif symbol in _MEDIUM_CALLS:
            self._add(
                _MEDIUM_CALLS[symbol],
                CodeRiskLevel.MEDIUM,
                "実行環境へアクセスする可能性がある呼び出しです。",
                node.lineno,
                symbol,
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        symbol = self._resolved_name(node)
        if symbol in {"os.environ", "os.getenv"}:
            self._add(
                CodeRiskCategory.ENVIRONMENT,
                CodeRiskLevel.HIGH,
                "環境変数へアクセスします。",
                node.lineno,
                symbol,
            )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        value = node.test.value if isinstance(node.test, ast.Constant) else None
        if value is True or (isinstance(value, (int, float)) and value != 0):
            has_break = any(isinstance(item, ast.Break) for item in ast.walk(node))
            risk = CodeRiskLevel.MEDIUM if has_break else CodeRiskLevel.BLOCKED
            self._add(
                CodeRiskCategory.INFINITE_LOOP,
                risk,
                "終了しない可能性があるwhileループです。",
                node.lineno,
                "while",
            )
        self.generic_visit(node)

    def _check_import(self, module: str, line_number: int) -> None:
        root = module.split(".")[0]
        if module in _BLOCKED_IMPORTS or root in _BLOCKED_IMPORTS:
            risk = CodeRiskLevel.BLOCKED
        elif root in _HIGH_IMPORTS:
            risk = CodeRiskLevel.HIGH
        elif root in _SAFE_IMPORTS:
            return
        else:
            risk = CodeRiskLevel.LOW
        self._add(
            CodeRiskCategory.IMPORT,
            risk,
            "注意が必要なモジュールのimportです。",
            line_number,
            module,
        )

    def _check_open(self, node: ast.Call) -> None:
        mode: str | None = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value if isinstance(node.args[1].value, str) else None
        for keyword in node.keywords:
            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                value = keyword.value.value
                mode = value if isinstance(value, str) else None
        write_mode = mode is not None and any(char in mode for char in "wax+")
        risk = CodeRiskLevel.HIGH if write_mode else CodeRiskLevel.MEDIUM
        operation = "書き込み" if write_mode else "読み込み"
        self._add(
            CodeRiskCategory.FILE_SYSTEM,
            risk,
            f"ファイル{operation}を行う可能性があります。",
            node.lineno,
            "open",
        )

    def _resolved_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self._aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = self._resolved_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        if isinstance(node, ast.Call):
            return self._resolved_name(node.func)
        return ""

    def _add(
        self,
        category: CodeRiskCategory,
        risk_level: CodeRiskLevel,
        message: str,
        line_number: int | None,
        symbol: str | None,
    ) -> None:
        key = (line_number, category, symbol)
        existing = self._findings.get(key)
        if existing is None or _RISK_ORDER[risk_level] > _RISK_ORDER[existing.risk_level]:
            self._findings[key] = CodeSafetyFinding(
                category, risk_level, message, line_number, symbol
            )

    def results(self) -> tuple[CodeSafetyFinding, ...]:
        ordered = sorted(
            self._findings.values(),
            key=lambda finding: (
                finding.line_number if finding.line_number is not None else -1,
                -_RISK_ORDER[finding.risk_level],
                finding.category.value,
                finding.symbol or "",
            ),
        )
        return tuple(ordered[:MAX_FINDINGS])
