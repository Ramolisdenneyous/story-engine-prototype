from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .llm import get_provider, log_artifact
from .models import Event, EventRole, MemoryBlock, MemoryBlockType, NarrativeDraft, Session as SessionModel, SessionState, Tab1Inputs

AGENT_COLOR_NAMES = {
    1: "Agent Red",
    2: "Agent Orange",
    3: "Agent Yellow",
    4: "Agent Green",
    5: "Agent Blue",
    6: "Agent Indigo",
    7: "Agent Violet",
}


def _default_name(slot: int) -> str:
    return AGENT_COLOR_NAMES.get(slot, f"Agent {slot}")


def create_session(db: Session) -> SessionModel:
    session = SessionModel(state=SessionState.DRAFT_TAB1, prompt_index=0, last_summarized_prompt_index=0)
    db.add(session)
    db.flush()
    db.add(Tab1Inputs(session_id=session.session_id, world_text="", chapter_text="", agent_identity_text_by_slot={}))
    db.commit()
    db.refresh(session)
    return session


def get_session_or_404(db: Session, session_id: str) -> SessionModel:
    session = db.get(SessionModel, session_id)
    if not session:
        raise ValueError("Session not found")
    return session


def get_tab1_or_create(db: Session, session_id: str) -> Tab1Inputs:
    tab1 = db.get(Tab1Inputs, session_id)
    if not tab1:
        tab1 = Tab1Inputs(session_id=session_id, world_text="", chapter_text="", agent_identity_text_by_slot={})
        db.add(tab1)
        db.flush()
    return tab1


def save_tab1(db: Session, session_id: str, payload: dict) -> tuple[SessionModel, Tab1Inputs]:
    session = get_session_or_404(db, session_id)
    if session.tab1_locked:
        raise ValueError("Tab1 is locked")
    if session.state != SessionState.DRAFT_TAB1:
        raise ValueError("Tab1 edits allowed only in DRAFT_TAB1")

    tab1 = get_tab1_or_create(db, session_id)
    tab1.world_text = payload.get("world_text", "")[:5000]
    tab1.chapter_text = payload.get("chapter_text", "")[:5000]

    slots = sorted(set(payload.get("selected_agent_slots", [1])))
    slots = [s for s in slots if 1 <= s <= 7]
    if not slots:
        slots = [1]
    session.selected_agent_slots = slots

    names_payload = payload.get("agent_names", {})
    normalized_names = {}
    for slot in slots:
        name = names_payload.get(str(slot), names_payload.get(slot, _default_name(slot)))
        normalized_names[str(slot)] = (name or _default_name(slot))[:120]
    session.agent_names = normalized_names

    identity_payload = payload.get("agent_identity_text_by_slot", {})
    normalized_identity = {}
    for slot in slots:
        txt = identity_payload.get(str(slot), identity_payload.get(slot, ""))
        normalized_identity[str(slot)] = (txt or "")[:5000]
    tab1.agent_identity_text_by_slot = normalized_identity

    db.commit()
    db.refresh(session)
    db.refresh(tab1)
    return session, tab1


def lock_tab1(db: Session, session_id: str) -> SessionModel:
    provider = get_provider()
    session = get_session_or_404(db, session_id)
    if session.state != SessionState.DRAFT_TAB1:
        raise ValueError("Session cannot be locked from current state")

    session.state = SessionState.LOCKING
    db.flush()

    tab1 = get_tab1_or_create(db, session_id)
    payload = {
        "world_text": tab1.world_text,
        "chapter_text": tab1.chapter_text,
        "selected_agent_slots": session.selected_agent_slots,
        "agent_names": session.agent_names,
        "agent_identity_text_by_slot": tab1.agent_identity_text_by_slot,
    }
    text = provider.generate("agent0", settings.llm_model_summary, payload)
    log_artifact(db, session_id, "agent0", settings.llm_model_summary, payload, text, provider.provider_name)

    db.add(
        MemoryBlock(
            session_id=session_id,
            type=MemoryBlockType.WORLD_CHAPTER_LOCK,
            from_prompt_index=0,
            to_prompt_index=0,
            json_payload={
                "summary": text,
                "world_text": tab1.world_text,
                "chapter_text": tab1.chapter_text,
                "selected_agent_slots": session.selected_agent_slots,
                "agent_names": session.agent_names,
            },
        )
    )

    session.tab1_locked = True
    session.prompt_index = 0
    session.last_summarized_prompt_index = 0
    session.state = SessionState.ACTIVE

    db.commit()
    db.refresh(session)
    return session


def _run_summarization(db: Session, session: SessionModel, to_prompt_index: int) -> bool:
    if to_prompt_index <= session.last_summarized_prompt_index:
        return False
    provider = get_provider()
    from_idx = session.last_summarized_prompt_index + 1
    events = db.execute(
        select(Event)
        .where(
            Event.session_id == session.session_id,
            Event.prompt_index >= from_idx,
            Event.prompt_index <= to_prompt_index,
        )
        .order_by(Event.prompt_index.asc(), Event.created_at.asc())
    ).scalars().all()

    payload = {
        "from_prompt_index": from_idx,
        "to_prompt_index": to_prompt_index,
        "events": [
            {
                "prompt_index": e.prompt_index,
                "role": e.role.value,
                "agent_slot": e.agent_slot,
                "text": e.text,
            }
            for e in events
        ],
    }
    output = provider.generate("agent8", settings.llm_model_summary, payload)
    log_artifact(db, session.session_id, "agent8", settings.llm_model_summary, payload, output, provider.provider_name)

    db.add(
        MemoryBlock(
            session_id=session.session_id,
            type=MemoryBlockType.TURN_DELTA,
            from_prompt_index=from_idx,
            to_prompt_index=to_prompt_index,
            json_payload={"summary": output, "event_count": len(events)},
        )
    )
    session.last_summarized_prompt_index = to_prompt_index
    return True


def _build_character_payload(db: Session, session: SessionModel, agent_slot: int, user_text: str) -> dict:
    tab1 = get_tab1_or_create(db, session.session_id)

    memory_blocks = db.execute(
        select(MemoryBlock)
        .where(MemoryBlock.session_id == session.session_id)
        .order_by(MemoryBlock.created_at.asc())
    ).scalars().all()

    from_prompt = max(1, session.prompt_index - 7)
    to_prompt = max(0, session.prompt_index - 1)
    recent_events = []
    if to_prompt >= from_prompt:
        recent_events = db.execute(
            select(Event)
            .where(
                Event.session_id == session.session_id,
                Event.prompt_index >= from_prompt,
                Event.prompt_index <= to_prompt,
            )
            .order_by(Event.prompt_index.asc(), Event.created_at.asc())
        ).scalars().all()

    return {
        "agent_identity": {
            "slot": agent_slot,
            "name": session.agent_names.get(str(agent_slot), _default_name(agent_slot)),
            "identity_text": tab1.agent_identity_text_by_slot.get(str(agent_slot), ""),
            "all_agent_names": session.agent_names,
        },
        "structured_memory": [
            {
                "type": mb.type.value,
                "from_prompt_index": mb.from_prompt_index,
                "to_prompt_index": mb.to_prompt_index,
                "json_payload": mb.json_payload,
            }
            for mb in memory_blocks
        ],
        "recent_context": [
            {
                "prompt_index": ev.prompt_index,
                "role": ev.role.value,
                "agent_slot": ev.agent_slot,
                "agent_name": session.agent_names.get(str(ev.agent_slot), None) if ev.agent_slot else None,
                "text": ev.text,
            }
            for ev in recent_events
        ],
        "user_prompt": user_text,
        "meta": {
            "session_id": session.session_id,
            "prompt_index": session.prompt_index,
            "context_prompt_range": [from_prompt, to_prompt] if recent_events else [],
        },
    }


def prompt_agent(db: Session, session_id: str, agent_slot: int, user_text: str) -> tuple[SessionModel, Event, Event, bool]:
    provider = get_provider()
    session = get_session_or_404(db, session_id)
    if session.state != SessionState.ACTIVE:
        raise ValueError("Session is not ACTIVE")
    if agent_slot not in session.selected_agent_slots:
        raise ValueError("Agent slot not selected for this session")

    session.prompt_index += 1

    user_event = Event(
        session_id=session_id,
        prompt_index=session.prompt_index,
        role=EventRole.USER,
        agent_slot=None,
        text=user_text,
    )
    db.add(user_event)
    db.flush()

    agent_payload = _build_character_payload(db, session, agent_slot, user_text)
    agent_text = provider.generate("agent_character", settings.llm_model_character, agent_payload)
    log_artifact(db, session_id, "agent_character", settings.llm_model_character, agent_payload, agent_text, provider.provider_name)

    agent_event = Event(
        session_id=session_id,
        prompt_index=session.prompt_index,
        role=EventRole.AGENT,
        agent_slot=agent_slot,
        text=agent_text,
    )
    db.add(agent_event)

    summary_triggered = False
    if session.prompt_index % settings.chunk_size_prompts == 0:
        session.state = SessionState.SUMMARIZING
        summary_triggered = _run_summarization(db, session, session.prompt_index)
        session.state = SessionState.ACTIVE

    db.commit()
    db.refresh(session)
    db.refresh(user_event)
    db.refresh(agent_event)
    return session, user_event, agent_event, summary_triggered


def end_chapter(db: Session, session_id: str) -> SessionModel:
    session = get_session_or_404(db, session_id)
    if session.state != SessionState.ACTIVE:
        raise ValueError("End chapter allowed only from ACTIVE")

    if session.last_summarized_prompt_index < session.prompt_index:
        session.state = SessionState.SUMMARIZING
        _run_summarization(db, session, session.prompt_index)

    session.state = SessionState.ENDED
    db.commit()
    db.refresh(session)
    return session


def save_narrative_agent(db: Session, session_id: str, text: str) -> SessionModel:
    session = get_session_or_404(db, session_id)
    session.narrative_agent_definition_text = text[:5000]
    db.commit()
    db.refresh(session)
    return session


def build_narrative(db: Session, session_id: str) -> NarrativeDraft:
    provider = get_provider()
    session = get_session_or_404(db, session_id)
    if session.state != SessionState.ENDED:
        raise ValueError("Build narrative allowed only in ENDED state")

    session.state = SessionState.NARRATING

    events = db.execute(select(Event).where(Event.session_id == session_id).order_by(Event.prompt_index.asc(), Event.created_at.asc())).scalars().all()
    blocks = db.execute(select(MemoryBlock).where(MemoryBlock.session_id == session_id).order_by(MemoryBlock.created_at.asc())).scalars().all()

    payload = {
        "narrative_agent_definition_text": session.narrative_agent_definition_text,
        "events": [
            {"prompt_index": e.prompt_index, "role": e.role.value, "agent_slot": e.agent_slot, "text": e.text}
            for e in events
        ],
        "memory_blocks": [
            {
                "block_id": b.block_id,
                "type": b.type.value,
                "from_prompt_index": b.from_prompt_index,
                "to_prompt_index": b.to_prompt_index,
                "json_payload": b.json_payload,
            }
            for b in blocks
        ],
    }
    output = provider.generate("agent9", settings.llm_model_narrative, payload)
    log_artifact(db, session_id, "agent9", settings.llm_model_narrative, payload, output, provider.provider_name)

    draft = NarrativeDraft(
        session_id=session_id,
        narrative_agent_definition_text=session.narrative_agent_definition_text,
        source_snapshot={
            "max_prompt_index_used": session.prompt_index,
            "memory_block_ids_used": [b.block_id for b in blocks],
        },
        chapter_text=output,
    )
    db.add(draft)

    session.state = SessionState.ENDED
    db.commit()
    db.refresh(draft)
    return draft


def reset_session(db: Session, session_id: str) -> SessionModel:
    session = get_session_or_404(db, session_id)
    session.state = SessionState.RESETTING
    db.flush()

    db.execute(delete(Event).where(Event.session_id == session_id))
    db.execute(delete(MemoryBlock).where(MemoryBlock.session_id == session_id))
    db.execute(delete(NarrativeDraft).where(NarrativeDraft.session_id == session_id))

    tab1 = get_tab1_or_create(db, session_id)
    tab1.world_text = ""
    tab1.chapter_text = ""
    tab1.agent_identity_text_by_slot = {}

    session.state = SessionState.DRAFT_TAB1
    session.prompt_index = 0
    session.last_summarized_prompt_index = 0
    session.tab1_locked = False
    session.selected_agent_slots = [1]
    session.agent_names = {"1": _default_name(1)}
    session.narrative_agent_definition_text = ""

    db.commit()
    db.refresh(session)
    return session


def get_session_detail(db: Session, session_id: str) -> dict:
    session = get_session_or_404(db, session_id)
    tab1 = get_tab1_or_create(db, session_id)
    events = db.execute(select(Event).where(Event.session_id == session_id).order_by(Event.prompt_index.asc(), Event.created_at.asc())).scalars().all()
    memory_blocks = db.execute(select(MemoryBlock).where(MemoryBlock.session_id == session_id).order_by(MemoryBlock.created_at.asc())).scalars().all()
    drafts = db.execute(select(NarrativeDraft).where(NarrativeDraft.session_id == session_id).order_by(NarrativeDraft.created_at.asc())).scalars().all()

    return {
        "session": session,
        "tab1": tab1,
        "events": events,
        "memory_blocks": memory_blocks,
        "narrative_drafts": drafts,
    }
