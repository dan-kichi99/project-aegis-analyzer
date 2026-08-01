import pytest

from app.analyzer.analyzer import Category
from app.prompt.prompt_manager import PromptManager


def build_prompt(
    category: str,
    knowledge: list[str] | None = None,
) -> str:
    return PromptManager().build(
        question="Find flag{sample} with: python solve.py",
        category=category,
        knowledge=knowledge or [],
    )


def test_crypto_prompt_requests_japanese_response():
    assert "Respond in Japanese." in build_prompt(Category.CRYPTO)


def test_web_prompt_requests_japanese_response():
    assert "Respond in Japanese." in build_prompt(Category.WEB)


def test_rev_prompt_requests_japanese_response():
    assert "Respond in Japanese." in build_prompt(Category.REV)


def test_misc_prompt_requests_japanese_response():
    assert "Respond in Japanese." in build_prompt(Category.MISC)


def test_unknown_prompt_requests_japanese_response():
    assert "Respond in Japanese." in build_prompt(Category.UNKNOWN)


def test_prompt_requires_code_flags_and_commands_to_remain_unchanged():
    prompt = build_prompt(Category.CRYPTO)

    assert (
        "Preserve code, commands, URLs, file paths, flags, variable names, "
        "and cryptographic parameters exactly as provided."
    ) in prompt


@pytest.mark.parametrize(
    ("category", "original_template_text"),
    [
        (
            Category.CRYPTO,
            "You are an expert in Cryptography and CTF challenges.",
        ),
        (
            Category.WEB,
            "You are an expert in Web Security and CTF challenges.",
        ),
        (
            Category.REV,
            "You are an expert in Reverse Engineering and CTF challenges.",
        ),
        (
            Category.MISC,
            (
                "You are an expert in Miscellaneous CTF challenges "
                "(Forensics, OSINT, Steganography, etc.)."
            ),
        ),
        (
            Category.UNKNOWN,
            "You are an expert in Cybersecurity and CTF challenges.",
        ),
    ],
)
def test_existing_category_templates_are_preserved(
    category: str,
    original_template_text: str,
):
    assert original_template_text in build_prompt(category)


def test_prompt_preserves_existing_local_knowledge():
    knowledge = "Use RSA modulus n=3233 and exponent e=17."
    prompt = build_prompt(Category.CRYPTO, [knowledge])

    assert "Relevant local knowledge:" in prompt
    assert knowledge in prompt


def test_prompt_preserves_no_local_knowledge_message():
    prompt = build_prompt(Category.UNKNOWN)

    assert "No local knowledge available." in prompt
