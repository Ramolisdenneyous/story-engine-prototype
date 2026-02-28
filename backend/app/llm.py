import hashlib
import json

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import LLMArtifact


class LLMProvider:
    provider_name = "base"

    def generate(self, agent_id: str, model: str, payload: dict) -> str:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    provider_name = "mock"

    def generate(self, agent_id: str, model: str, payload: dict) -> str:
        if agent_id == "agent0":
            slots = payload.get("selected_agent_slots", [])
            names = payload.get("agent_names", {})
            return (
                "World/Chapter lock created. "
                f"Agents: {', '.join([f'{slot}:{names.get(str(slot), names.get(slot, f'Agent {slot}'))}' for slot in slots])}."
            )
        if agent_id == "agent8":
            return (
                f"Turn delta summary for prompts {payload.get('from_prompt_index')}"
                f"-{payload.get('to_prompt_index')}"
            )
        if agent_id == "agent9":
            return "Narrative draft (MVP mock) generated from structured memory and transcript."
        slot = payload.get("agent_identity", {}).get("slot")
        return f"Agent {slot} response to prompt {payload.get('meta', {}).get('prompt_index')}: {payload.get('user_prompt', '')[:120]}"


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, agent_id: str, model: str, payload: dict) -> str:
        system_prompt = self._system_prompt(agent_id)
        user_prompt = self._user_prompt(agent_id, payload)

        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.4,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

    def _system_prompt(self, agent_id: str) -> str:
        if agent_id == "agent0":
            return "Summarize Tab1 world/chapter setup into compact structured narrative memory."
        if agent_id == "agent8":
            return "Summarize the prompt chunk into concise structured memory delta with only new information."
        if agent_id == "agent9":
            return "Write a cohesive chapter draft using structured memory as canon and transcript as detail."
        return (
            "You are a character roleplay agent. Follow your character identity exactly, including gender and voice. "
            "Never contradict structured memory. Use recent context to stay scene-accurate. "
            "Respond only as your character and do not narrate other characters' internal thoughts as facts."
        )

    def _user_prompt(self, agent_id: str, payload: dict) -> str:
        if agent_id != "agent_character":
            return json.dumps(payload, ensure_ascii=True)

        identity = payload.get("agent_identity", {})
        memory = payload.get("structured_memory", [])
        recent = payload.get("recent_context", [])
        user_prompt = payload.get("user_prompt", "")

        recent_lines = []
        for ev in recent:
            if ev.get("role") == "user":
                recent_lines.append(f"{ev.get('prompt_index')}) {ev.get('text')}")
            elif ev.get("role") == "agent":
                name = ev.get("agent_name") or f"Agent {ev.get('agent_slot')}"
                recent_lines.append(f"{name}: {ev.get('text')}")
            else:
                recent_lines.append(f"system: {ev.get('text')}")

        return (
            "[Agent Identity]\n"
            f"{json.dumps(identity, ensure_ascii=True)}\n\n"
            "[Structured Memory]\n"
            f"{json.dumps(memory, ensure_ascii=True)}\n\n"
            "[Current Context: last seven user prompts and agent replies]\n"
            f"{'\n'.join(recent_lines)}\n\n"
            "[User Prompt]\n"
            f"{user_prompt}"
        )


def get_provider() -> LLMProvider:
    if settings.llm_provider == "openai":
        if not settings.llm_external_enabled:
            raise RuntimeError("LLM provider is openai but LLM_EXTERNAL_ENABLED is false")
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAIProvider(settings.openai_api_key, settings.openai_base_url)
    return MockLLMProvider()


def log_artifact(db: Session, session_id: str, agent_id: str, model: str, payload: dict, output: str, provider_name: str) -> None:
    payload_text = json.dumps(payload, sort_keys=True)
    artifact = LLMArtifact(
        session_id=session_id,
        agent_id=agent_id,
        provider=provider_name,
        model=model,
        input_hash=hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        token_counts={"input_chars": len(payload_text), "output_chars": len(output)},
        raw_input_ref=payload_text,
        raw_output_ref=output,
    )
    db.add(artifact)
