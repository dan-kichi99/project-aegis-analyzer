import math
from dataclasses import replace

from app.judge.flag_extractor import FlagExtractor
from app.solver.rsa_result import RsaAttempt, RsaParameters, RsaResult

MAX_MODULUS_BITS = 4_096
MAX_TRIAL_DIVISOR = 1_000_000
MAX_FERMAT_ATTEMPTS = 100_000
MAX_ATTEMPTS = 10


class RsaSolver:
    """明示鍵または安全な上限内の因数分解だけでRSAを診断する。"""

    def __init__(self) -> None:
        self._flag_extractor = FlagExtractor()

    def solve(self, parameters: RsaParameters) -> RsaResult:
        if parameters.n is None or parameters.c is None:
            return self._failure(parameters, "必須パラメータ確認", "nまたはcが不足しています。")
        if parameters.n <= 1 or parameters.n.bit_length() > MAX_MODULUS_BITS:
            return self._failure(
                parameters,
                "入力上限確認",
                "nが許容範囲外です。",
            )

        if parameters.p is not None or parameters.q is not None:
            return self._solve_with_given_factors(parameters)
        if parameters.d is not None:
            return self._decrypt(parameters, "与えられたdを使用")
        if parameters.e is None:
            return self._failure(parameters, "必須パラメータ確認", "eまたはdが不足しています。")

        factors = self._trial_factor(parameters.n)
        if factors is not None:
            return self._solve_with_factors(
                parameters,
                *factors,
                method="小さいnの試し割り",
            )
        if math.isqrt(parameters.n) <= MAX_TRIAL_DIVISOR:
            return self._failure(
                parameters,
                "小さいnの試し割り",
                "上限内の試し割りで因数を特定できませんでした。",
            )

        factors, fermat_detail = self._fermat_factor(parameters.n)
        if factors is not None:
            return self._solve_with_factors(
                parameters,
                *factors,
                method="Fermat因数分解",
            )
        return self._failure(parameters, "Fermat因数分解", fermat_detail)

    def _solve_with_given_factors(self, parameters: RsaParameters) -> RsaResult:
        if parameters.p is None or parameters.q is None:
            return self._failure(parameters, "与えられたp・qを使用", "pまたはqが不足しています。")
        if parameters.p < 2 or parameters.q < 2:
            return self._failure(parameters, "与えられたp・qを使用", "pとqは2以上である必要があります。")
        if parameters.p * parameters.q != parameters.n:
            return self._failure(parameters, "与えられたp・qを使用", "p * qがnと一致しません。")
        return self._solve_with_factors(
            parameters,
            parameters.p,
            parameters.q,
            method="与えられたp・qを使用",
        )

    def _solve_with_factors(
        self,
        parameters: RsaParameters,
        p: int,
        q: int,
        method: str,
    ) -> RsaResult:
        if parameters.e is None:
            return self._failure(parameters, method, "eが不足しています。")
        phi = (p - 1) * (q - 1)
        if math.gcd(parameters.e, phi) != 1:
            return self._failure(parameters, method, "gcd(e, phi) != 1です。")
        d = pow(parameters.e, -1, phi)
        completed = replace(parameters, p=p, q=q, phi=phi, d=d)
        return self._decrypt(completed, method)

    def _decrypt(self, parameters: RsaParameters, method: str) -> RsaResult:
        assert parameters.n is not None
        assert parameters.c is not None
        assert parameters.d is not None
        if parameters.d < 1:
            return self._failure(parameters, method, "dは1以上である必要があります。")
        plaintext_integer = pow(parameters.c, parameters.d, parameters.n)
        if parameters.e is not None and (
            pow(plaintext_integer, parameters.e, parameters.n)
            != parameters.c % parameters.n
        ):
            return self._failure(parameters, method, "再暗号化検証に失敗しました。")

        length = max(1, (plaintext_integer.bit_length() + 7) // 8)
        plaintext_bytes = plaintext_integer.to_bytes(length, "big")
        try:
            plaintext = plaintext_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self._failure(
                parameters,
                method,
                f"復号結果はUTF-8ではありません（hex={plaintext_bytes.hex()}）。",
            )
        contains_flag = self._flag_extractor.extract(plaintext) is not None
        attempt = RsaAttempt(
            method=method,
            success=True,
            detail="復号と正当性確認に成功しました。",
            plaintext=plaintext,
            contains_flag=contains_flag,
        )
        return RsaResult(
            parameters=parameters,
            attempts=(attempt,),
            plaintext=plaintext,
            contains_flag=contains_flag,
        )

    def _trial_factor(self, n: int) -> tuple[int, int] | None:
        limit = math.isqrt(n)
        if limit > MAX_TRIAL_DIVISOR:
            return None
        if n % 2 == 0:
            return (2, n // 2) if n > 2 else None
        for divisor in range(3, limit + 1, 2):
            if n % divisor == 0:
                return divisor, n // divisor
        return None

    def _fermat_factor(
        self,
        n: int,
    ) -> tuple[tuple[int, int] | None, str]:
        if n % 2 == 0:
            return None, "偶数nはFermat法の対象外です。"
        a = math.isqrt(n)
        if a * a < n:
            a += 1
        for attempts in range(1, MAX_FERMAT_ATTEMPTS + 1):
            difference = a * a - n
            b = math.isqrt(difference)
            if b * b == difference:
                p, q = a - b, a + b
                if p > 1 and p * q == n:
                    return (p, q), f"Fermat法を{attempts}回試行しました。"
            a += 1
        return None, f"Fermat法を{MAX_FERMAT_ATTEMPTS}回試行し、上限で停止しました。"

    def _failure(
        self,
        parameters: RsaParameters,
        method: str,
        detail: str,
    ) -> RsaResult:
        return RsaResult(
            parameters=parameters,
            attempts=(
                RsaAttempt(
                    method=method,
                    success=False,
                    detail=detail,
                    plaintext=None,
                    contains_flag=False,
                ),
            )[:MAX_ATTEMPTS],
            plaintext=None,
            contains_flag=False,
        )
