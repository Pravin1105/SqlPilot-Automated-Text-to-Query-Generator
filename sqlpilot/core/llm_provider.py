import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from google import genai
from config import settings


class LLMProvider(ABC):
    """Abstract interface for LLM provider implementations (Gemini, local Ollama, etc.)."""

    @abstractmethod
    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured JSON response from prompt."""
        pass


class GeminiLLMProvider(LLMProvider):
    """Google Gemini LLM provider implementation using google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model
        if not self.api_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY environment variable or specify in config."
            )
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

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Clean markdown codeblocks if LLM included ```json wrappers
            clean_text = text.strip()
            if clean_text.startswith("```"):
                lines = clean_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_text = "\n".join(lines).strip()
            return json.loads(clean_text)
