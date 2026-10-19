from dataclasses import dataclass
from functools import lru_cache

from openai import OpenAI

from breakmyapi.config import get_settings


class LLMConfigError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise LLMConfigError("LLM_API_KEY is empty. Put your Groq key in .env")
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=60,
        max_retries=3,
    )


def ask(prompt: str, *, system: str | None = None, strong: bool = False) -> LLMResult:
    settings = get_settings()
    model = settings.llm_model_strong if strong else settings.llm_model_fast

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = get_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    return LLMResult(
        text=response.choices[0].message.content or "",
        model=model,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )
