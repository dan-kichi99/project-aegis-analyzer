import re

from app.agents.agent import BaseAgent
from app.agents.agent_input import AgentInput
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.analyzer.analyzer import Category
from app.client.base_client import BaseAIClient
from app.judge.flag_extractor import FlagExtractor
from app.prompt.prompt_manager import PromptManager

MAX_CONTEXT_CHARACTERS = 20_000
MAX_KNOWLEDGE_ITEMS = 10
MAX_KNOWLEDGE_ITEM_CHARACTERS = 2_000
MAX_KNOWLEDGE_TOTAL_CHARACTERS = 10_000
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_DETAIL_CHARACTERS = 500
MAX_SUMMARY_CHARACTERS = 500
MAX_ENDPOINTS = 10
MAX_PARAMETERS = 15
MAX_TECHNOLOGIES = 10
MAX_VULNERABILITIES = 10

_REQUEST = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+\S+\s+HTTP/\S+", re.IGNORECASE | re.MULTILINE)
_RESPONSE = re.compile(r"^HTTP/(?:1\.[01]|2)\s+\d{3}(?:\s+[^\r\n]+)?", re.IGNORECASE | re.MULTILINE)
_HEADER_NAMES = (
    "Host", "Cookie", "Set-Cookie", "Authorization", "Content-Type",
    "Content-Length", "Location", "Origin", "Referer", "User-Agent",
    "X-Forwarded-For", "X-Real-IP", "Access-Control-Allow-Origin",
)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_ENDPOINT = re.compile(r"/(?:login|admin|api(?:/[^\s?'\"<>]*)?|upload|download|debug|graphql|robots\.txt|flag|secret)(?:[^\s?'\"<>]*)?", re.IGNORECASE)
_PARAMETER = re.compile(
    r"(?:[?&]|\b|[\"'])(username|password|email|id|query|search|url|redirect|"
    r"file|path|template|command|cmd|token|role|admin)[\"']?\s*[:=]\s*([^&\s,}\r\n]+)",
    re.IGNORECASE,
)
_TECHNOLOGIES = (
    "PHP", "Flask", "Django", "FastAPI", "Express", "Node.js", "Laravel",
    "Spring", "ASP.NET", "Ruby on Rails", "Apache", "nginx", "IIS",
    "Werkzeug", "gunicorn", "MySQL", "PostgreSQL", "SQLite", "MongoDB",
    "Redis", "Jinja2", "Twig", "Smarty", "EJS", "Handlebars", "JWT",
    "session", "OAuth", "Basic Auth", "Bearer",
)
_VULNERABILITIES = (
    ("SQL Injection", ("union select", "sql syntax", "mysql_fetch", "select ", "' or '1'='1")),
    ("XSS", ("<script", "onerror=", "javascript:")),
    ("SSTI", ("{{7*7}}", "{{ config", "jinja2", "template=")),
    ("LFI", ("/etc/passwd", "php://filter", "file=")),
    ("Path Traversal", ("../",)),
    ("Command Injection", ("; id", "&& whoami", "command=", "cmd=")),
    ("SSRF", ("url=", "localhost", "127.0.0.1", "169.254.169.254")),
    ("Open Redirect", ("redirect=",)),
    ("IDOR", ("idor", "user_id=", "account_id=")),
    ("CSRF", ("csrf",)),
    ("JWT misconfiguration", ("alg=none", "jwt secret", "weak jwt")),
    ("Insecure File Upload", ("upload", "multipart/form-data")),
    ("Authentication Bypass", ("auth bypass", "login bypass")),
    ("CORS misconfiguration", ("access-control-allow-origin: *",)),
    ("XXE", ("<!doctype", "<!entity",)),
    ("Deserialization", ("deserialize", "unserialize",)),
)
_SECRET_KEYS = {"password", "token"}


class WebAgent(BaseAgent):
    """提供済みテキストだけを静的に整理するWeb専門Agent。"""

    def __init__(self, ai_client: BaseAIClient, flag_extractor: FlagExtractor | None = None, prompt_manager: PromptManager | None = None) -> None:
        self._ai_client = ai_client
        self._flag_extractor = flag_extractor or FlagExtractor()
        self._prompt_manager = prompt_manager or PromptManager()

    @property
    def agent_type(self) -> AgentType:
        return AgentType.WEB

    def with_ai_client(self, ai_client: BaseAIClient) -> "WebAgent":
        return WebAgent(ai_client, self._flag_extractor, self._prompt_manager)

    def analyze(self, agent_input: AgentInput) -> AgentResult:
        matches_target = (
            agent_input.target_agent is self.agent_type
            if agent_input.target_agent is not None
            else agent_input.category.casefold() == Category.WEB.casefold()
        )
        if not matches_target:
            return AgentResult(self.agent_type, AgentStatus.SKIPPED, f"カテゴリ「{agent_input.category}」はWeb対象外です。", None, None, None, (), (), None)

        evidence = self._evidence(agent_input)
        local_flags = self._file_flags(agent_input)
        if local_flags:
            return AgentResult(self.agent_type, AgentStatus.COMPLETED, "添付ファイルの静的情報からFlag候補を検出しました。", "候補を問題内容と手動で照合してください。", local_flags[0], 90, tuple(evidence), ("Flag候補を問題内容と手動で照合する",), None)

        response = self._ai_client.generate(self._build_prompt(agent_input, evidence))
        ai_flag = self._flag_extractor.extract(response)
        evidence = evidence[: MAX_EVIDENCE_ITEMS - 1]
        evidence.append(AgentEvidence("ai_analysis", self._limit(response), 60 if ai_flag else 40))
        return AgentResult(self.agent_type, AgentStatus.COMPLETED, response[:MAX_SUMMARY_CHARACTERS], response, ai_flag, 60 if ai_flag else 40, tuple(evidence), ("入力点とレスポンス差分を手動で検証する",), None)

    def _texts(self, agent_input: AgentInput) -> list[str]:
        texts = [agent_input.challenge.question, agent_input.context]
        for file_result in agent_input.challenge.files:
            if file_result.text_content:
                texts.append(file_result.text_content)
            texts.extend(file_result.strings)
        return texts

    def _evidence(self, agent_input: AgentInput) -> list[AgentEvidence]:
        text = "\n".join(self._texts(agent_input))
        masked = self._mask(text)
        buckets: list[list[AgentEvidence]] = [[] for _ in range(7)]
        seen: set[tuple[str, str]] = set()

        for file_result in agent_input.challenge.files:
            file_values = [file_result.text_content or "", *file_result.strings]
            for value in file_values:
                for flag in self._flag_extractor.extract_all(value):
                    self._add(
                        buckets[0],
                        seen,
                        "local_flag_candidate",
                        f"添付ファイル「{file_result.name}」内のFlag候補: {flag}",
                        90,
                    )

        for name, hints in _VULNERABILITIES:
            matches = [hint for hint in hints if hint in text.casefold()]
            if matches:
                confidence = 85 if len(matches) > 1 else 70
                self._add(buckets[1], seen, "vulnerability_candidate", f"{name}に関連する可能性がある文字列を検出しました: {', '.join(matches)}", confidence)
                if len(buckets[1]) >= MAX_VULNERABILITIES:
                    break

        for header in _HEADER_NAMES:
            pattern = re.compile(rf"^{re.escape(header)}\s*:\s*[^\r\n]*", re.IGNORECASE | re.MULTILINE)
            for match in pattern.finditer(masked):
                bucket = buckets[2] if header.casefold() in {"cookie", "set-cookie", "authorization"} else buckets[3]
                self._add(bucket, seen, "http_header", match.group(0), 50)
        for match in _REQUEST.finditer(masked):
            self._add(buckets[3], seen, "http_request", match.group(0), 70)
        for match in _RESPONSE.finditer(masked):
            self._add(buckets[3], seen, "http_response", match.group(0), 70)

        endpoints = list(_URL.finditer(masked)) + list(_ENDPOINT.finditer(masked))
        for match in endpoints[:MAX_ENDPOINTS]:
            self._add(buckets[4], seen, "url_endpoint", match.group(0)[:300], 50)
        for match in list(_PARAMETER.finditer(masked))[:MAX_PARAMETERS]:
            key = match.group(1)
            value = "[REDACTED]" if key.casefold() in _SECRET_KEYS else match.group(2)
            self._add(buckets[4], seen, "parameter", f"{key}={value}", 50)

        lower = text.casefold()
        for technology in _TECHNOLOGIES:
            if technology.casefold() in lower:
                self._add(buckets[5], seen, "web_technology", technology, 50)
                if len(buckets[5]) >= MAX_TECHNOLOGIES:
                    break
        return [item for bucket in buckets for item in bucket][:MAX_EVIDENCE_ITEMS]

    def _add(self, bucket: list[AgentEvidence], seen: set[tuple[str, str]], source: str, detail: str, confidence: int) -> None:
        detail = self._limit(detail)
        key = (source, detail.casefold())
        if key not in seen:
            seen.add(key)
            bucket.append(AgentEvidence(source, detail, confidence))

    def _file_flags(self, agent_input: AgentInput) -> list[str]:
        flags: list[str] = []
        for file_result in agent_input.challenge.files:
            flags.extend(self._flag_extractor.extract_all(file_result.text_content or ""))
            for value in file_result.strings:
                flags.extend(self._flag_extractor.extract_all(value))
        return list(dict.fromkeys(flags))

    def _mask(self, text: str) -> str:
        text = re.sub(
            r"^(Authorization|Cookie|Set-Cookie)\s*:\s*([^\r\n]*)",
            self._mask_header,
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        return re.sub(r"\b(password|token)\s*[:=]\s*([^&\s,}\r\n]+)", lambda match: f"{match.group(1)}=[REDACTED]", text, flags=re.IGNORECASE)

    def _mask_header(self, match: re.Match[str]) -> str:
        header = match.group(1)
        if header.casefold() == "authorization":
            return f"{header}: [REDACTED]"
        names = []
        for part in match.group(2).split(";"):
            name = part.strip().split("=", 1)[0]
            if name:
                names.append(f"{name}=[REDACTED]")
        return f"{header}: {'; '.join(names) or '[REDACTED]'}"

    def _build_prompt(self, agent_input: AgentInput, evidence: list[AgentEvidence]) -> str:
        evidence_text = "\n".join(f"- [{item.source}] {item.detail}" for item in evidence) or "- Web静的Evidenceはありません。"
        question = (
            "Web Security / CTF専門家として、提供済みの静的情報だけを分析してください。\n"
            "確定事実と仮説を区別し、Flag候補を正解と断定しないでください。\n"
            "外部サイトへアクセスせず、攻撃を自動実行しないでください。\n"
            "次に手動確認する入力点・レスポンス差分を示し、PayloadはCTF用の最小例にしてください。\n"
            "URL、Header名、Cookie名、Parameter名を改変しないでください。\n\n"
            f"問題コンテキスト:\n{self._mask(agent_input.context[:MAX_CONTEXT_CHARACTERS])}\n\n"
            f"静的Web Evidence:\n{evidence_text}"
        )
        return self._prompt_manager.build(question, Category.WEB, self._limited_knowledge(agent_input.local_knowledge))

    def _limited_knowledge(self, knowledge: tuple[str, ...]) -> list[str]:
        limited: list[str] = []
        total = 0
        for item in knowledge[:MAX_KNOWLEDGE_ITEMS]:
            remaining = MAX_KNOWLEDGE_TOTAL_CHARACTERS - total
            if remaining <= 0:
                break
            value = item[: min(MAX_KNOWLEDGE_ITEM_CHARACTERS, remaining)]
            limited.append(value)
            total += len(value)
        return limited

    def _limit(self, value: str) -> str:
        return value[:MAX_EVIDENCE_DETAIL_CHARACTERS]
