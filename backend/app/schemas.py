from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import SessionState


class SessionCreateResponse(BaseModel):
    session_id: str
    state: SessionState


class Tab1InputPayload(BaseModel):
    world_text: str = ""
    chapter_text: str = ""
    selected_agent_slots: list[int] = Field(default_factory=lambda: [1])
    agent_names: dict[int, str] = Field(default_factory=dict)
    agent_identity_text_by_slot: dict[int, str] = Field(default_factory=dict)


class Tab1InputResponse(Tab1InputPayload):
    tab1_locked: bool


class SessionSummary(BaseModel):
    session_id: str
    state: SessionState
    prompt_index: int
    last_summarized_prompt_index: int
    tab1_locked: bool


class PromptRequest(BaseModel):
    agent_slot: int
    user_text: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    prompt_index: int
    role: Literal["user", "agent", "system"]
    agent_slot: int | None
    text: str
    created_at: datetime


class MemoryBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_id: str
    type: str
    from_prompt_index: int
    to_prompt_index: int
    json_payload: dict
    created_at: datetime


class PromptResponse(BaseModel):
    session: SessionSummary
    user_event: EventOut
    agent_event: EventOut
    summary_triggered: bool


class NarrativeAgentRequest(BaseModel):
    narrative_agent_definition_text: str


class NarrativeBuildResponse(BaseModel):
    draft_id: str
    chapter_text: str


class SessionDetailResponse(BaseModel):
    session: SessionSummary
    tab1: Tab1InputResponse
    events: list[EventOut]
    memory_blocks: list[MemoryBlockOut]
    narrative_drafts: list[NarrativeBuildResponse]
