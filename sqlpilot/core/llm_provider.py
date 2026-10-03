import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from config import settings


def _clean_and_parse_json(text: str) -> Dict[str, Any]:
    """Clean markdown codeblocks and parse JSON response safely."""
    clean_text = text.strip()
    if clean_text.startswith("```"):
        lines = clean_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_text = "\n".join(lines).strip()

    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        # Fallback: extract substring between first { and last }
        start = clean_text.find("{")
        end = clean_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(clean_text[start : end + 1])
        raise


class LLMProvider(ABC):
    """Abstract interface for LLM provider implementations (Groq, Gemini, local Ollama, etc.)."""

    @abstractmethod
    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured JSON response from prompt."""
        pass


class GroqLLMProvider(LLMProvider):
    """Groq Cloud LLM provider implementation using OpenAI-compatible chat completions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        api_base: str = "https://api.groq.com/openai/v1",
    ):
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model_name = model_name or settings.groq_model
        self.api_base = api_base.rstrip("/")
        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set GROQ_API_KEY environment variable or specify in config."
            )

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Call Groq API requesting JSON structured response."""
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        req_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "SQLPilot/1.2",
        }

        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=req_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                text = resp_json["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                msg = err_body

            # Automatic fallback if configured model is not available for this account
            if e.code == 404 and "does not exist" in msg and self.model_name != "openai/gpt-oss-120b":
                self.model_name = "openai/gpt-oss-120b"
                return self.generate_json(prompt, system_instruction)

            raise RuntimeError(f"Groq API Error ({e.code}): {msg}") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", str(e))
            raise RuntimeError(f"Groq Network Error: Could not connect to API ({reason})") from e
        except Exception as e:
            raise RuntimeError(f"Groq Connection Error: {str(e)}") from e

        return _clean_and_parse_json(text)


class GeminiLLMProvider(LLMProvider):
    """Google Gemini LLM provider implementation using google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY environment variable or specify in config."
            )
        from google import genai
        self.client = genai.Client(api_key=self.api_key)

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Call Gemini API requesting JSON output format."""
        config = {"response_mime_type": "application/json"}
        if system_instruction:
            config["system_instruction"] = system_instruction

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        text = ""
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            parts_text = []
            for part in response.candidates[0].content.parts:
                if getattr(part, "thought", False):
                    continue
                if getattr(part, "text", None):
                    parts_text.append(part.text)
            text = "".join(parts_text).strip()

        if not text:
            try:
                text = response.text or "{}"
            except Exception:
                text = "{}"

        return _clean_and_parse_json(text)


class OpenAILLMProvider(LLMProvider):
    """OpenAI LLM provider implementation using standard chat completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        api_base: str = "https://api.openai.com/v1",
    ):
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model_name = model_name or settings.openai_model
        self.api_base = api_base.rstrip("/")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY environment variable or specify in config."
            )

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Call OpenAI API requesting JSON structured response."""
        is_reasoning_model = any(
            self.model_name.startswith(pfx) for pfx in ("o1", "o3")
        )

        messages = []
        if system_instruction:
            role = "developer" if is_reasoning_model else "system"
            messages.append({"role": role, "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if not is_reasoning_model:
            payload["temperature"] = 0.1

        req_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "SQLPilot/2.0",
        }

        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=req_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                text = resp_json["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                msg = err_body
            raise RuntimeError(f"OpenAI API Error ({e.code}): {msg}") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", str(e))
            raise RuntimeError(f"OpenAI Network Error: Could not connect to API ({reason})") from e
        except Exception as e:
            raise RuntimeError(f"OpenAI Connection Error: {str(e)}") from e

        return _clean_and_parse_json(text)


class ClaudeLLMProvider(LLMProvider):
    """Anthropic Claude LLM provider implementation using messages API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        api_base: str = "https://api.anthropic.com/v1",
    ):
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.api_base = api_base.rstrip("/")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key is required. Set ANTHROPIC_API_KEY environment variable or specify in config."
            )

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Call Anthropic Claude API requesting JSON structured response."""
        sys_inst = system_instruction or ""
        if "JSON" not in sys_inst.upper():
            sys_inst = (sys_inst + "\nYou MUST reply with valid JSON only, without any markdown formatting or commentary.").strip()

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        if sys_inst:
            payload["system"] = sys_inst

        req_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "SQLPilot/2.0",
        }

        req = urllib.request.Request(
            f"{self.api_base}/messages",
            data=req_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                text = ""
                for block in resp_json.get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                msg = err_body
            raise RuntimeError(f"Anthropic Claude API Error ({e.code}): {msg}") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", str(e))
            raise RuntimeError(f"Anthropic Claude Network Error: Could not connect to API ({reason})") from e
        except Exception as e:
            raise RuntimeError(f"Anthropic Claude Connection Error: {str(e)}") from e

        return _clean_and_parse_json(text)


def get_llm_provider() -> LLMProvider:
    """Factory creating configured LLM provider (Groq, OpenAI, Claude, or Gemini)."""
    provider_name = settings.llm_provider.lower()
    if provider_name == "openai" or (settings.openai_api_key and not settings.groq_api_key and not settings.gemini_api_key and not settings.anthropic_api_key):
        return OpenAILLMProvider()
    elif provider_name in ("claude", "anthropic") or (settings.anthropic_api_key and not settings.groq_api_key and not settings.gemini_api_key and not settings.openai_api_key):
        return ClaudeLLMProvider()
    elif provider_name == "gemini" or (settings.gemini_api_key and not settings.groq_api_key):
        return GeminiLLMProvider()
    elif provider_name == "groq" or settings.groq_api_key:
        return GroqLLMProvider()

    raise ValueError(
        "No LLM provider configured. Set GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY in environment or config."
    )
