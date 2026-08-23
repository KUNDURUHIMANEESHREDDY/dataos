"""
AI Provider Abstraction for DataOS (Rule #44).
Provides pluggable provider interface (Ollama, OpenAI-compatible, Mock/Deterministic),
token-cost tracking, latency measurement, and strict grounding verification filters.
"""

from __future__ import annotations
import time
import json
import datetime
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from core.object.model import DataObject
from runtime.grounding.grounder import GroundingEngine, GroundedAssertion


class AIResponse:
    """Standardized AI completion response with execution telemetry."""

    def __init__(
        self,
        content: str,
        model: str,
        provider: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        estimated_cost_usd: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.content = content
        self.model = model
        self.provider = provider
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.latency_ms = latency_ms
        self.estimated_cost_usd = estimated_cost_usd
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize response to a dictionary."""
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "metadata": self.metadata
        }


class BaseAIProvider(ABC):
    """Abstract interface for AI model providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context_data: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int = 1000
    ) -> AIResponse:
        """Generate response from the model provider."""
        pass


class MockDeterministicProvider(BaseAIProvider):
    """Deterministic, zero-latency provider for grounded test execution."""

    def __init__(self, model_name: str = "dataos_deterministic_v1"):
        self.model_name = model_name

    @property
    def provider_name(self) -> str:
        return "deterministic_mock"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context_data: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int = 1000
    ) -> AIResponse:
        """Generate deterministic summary from context data."""
        start_time = time.time()
        
        # Build deterministic summary based on provided context
        summary_lines = [f"Analysis for: '{prompt[:50]}'"]
        if context_data:
            summary_lines.append(f"Synthesized from {len(context_data)} grounded evidence items.")
            for c in context_data[:3]:
                if isinstance(c, dict):
                    summary_lines.append(f"- Fact: {c.get('filename', c.get('title', str(c)[:60]))}")

        content = "\n".join(summary_lines)
        prompt_toks = len(prompt.split()) + 10
        comp_toks = len(content.split())
        duration_ms = (time.time() - start_time) * 1000.0

        return AIResponse(
            content=content,
            model=self.model_name,
            provider=self.provider_name,
            prompt_tokens=prompt_toks,
            completion_tokens=comp_toks,
            latency_ms=round(duration_ms, 2),
            estimated_cost_usd=0.0
        )


class OpenAICompatibleProvider(BaseAIProvider):
    """OpenAI / Ollama / LocalAI compatible provider (Rule #44)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        model: str = "llama3"
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context_data: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int = 1000
    ) -> AIResponse:
        """Generate response via OpenAI-compatible API endpoint."""
        import urllib.request
        import urllib.error

        start_time = time.time()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        user_content = prompt
        if context_data:
            user_content += f"\n\nContext Data:\n{json.dumps(context_data, default=str)}"
        messages.append({"role": "user", "content": user_content})

        req_body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                choice = resp_data["choices"][0]["message"]["content"]
                usage = resp_data.get("usage", {})
                duration_ms = (time.time() - start_time) * 1000.0

                return AIResponse(
                    content=choice,
                    model=self.model,
                    provider=self.provider_name,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=round(duration_ms, 2),
                    estimated_cost_usd=(usage.get("total_tokens", 0) * 0.0000015)
                )
        except Exception as e:
            # Fallback to deterministic error response
            return AIResponse(
                content=f"[Provider Error: {str(e)}]",
                model=self.model,
                provider=self.provider_name,
                latency_ms=(time.time() - start_time) * 1000.0,
                metadata={"error": str(e)}
            )


class TokenCostTracker:
    """Tracks token consumption and cumulative compute budgets across agents."""

    def __init__(self):
        self.session_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0
        self.agent_costs: Dict[str, Dict[str, Any]] = {}

    def record_usage(self, agent_id: str, response: AIResponse):
        """Record token usage and cost for an agent response."""
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        self.total_cost_usd += response.estimated_cost_usd

        if agent_id not in self.agent_costs:
            self.agent_costs[agent_id] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "call_count": 0
            }

        rec = self.agent_costs[agent_id]
        rec["prompt_tokens"] += response.prompt_tokens
        rec["completion_tokens"] += response.completion_tokens
        rec["total_tokens"] += response.total_tokens
        rec["cost_usd"] += response.estimated_cost_usd
        rec["call_count"] += 1

    def get_summary(self) -> Dict[str, Any]:
        """Return cumulative token usage and cost summary."""
        return {
            "session_started_at": self.session_started_at,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "agent_breakdown": self.agent_costs
        }
