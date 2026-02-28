from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .schemas import (
    NarrativeAgentRequest,
    NarrativeBuildResponse,
    PromptRequest,
    PromptResponse,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionSummary,
    Tab1InputPayload,
    Tab1InputResponse,
)
from .services import (
    build_narrative,
    create_session,
    end_chapter,
    get_session_detail,
    lock_tab1,
    prompt_agent,
    reset_session,
    save_narrative_agent,
    save_tab1,
)

app = FastAPI(title="Story Engine MVP", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/session", response_model=SessionCreateResponse)
def create_session_endpoint(db: Session = Depends(get_db)):
    session = create_session(db)
    return SessionCreateResponse(session_id=session.session_id, state=session.state)


@app.put("/session/{session_id}/tab1", response_model=Tab1InputResponse)
def save_tab1_endpoint(session_id: str, payload: Tab1InputPayload, db: Session = Depends(get_db)):
    try:
        session, tab1 = save_tab1(db, session_id, payload.model_dump())
        return Tab1InputResponse(
            world_text=tab1.world_text,
            chapter_text=tab1.chapter_text,
            selected_agent_slots=session.selected_agent_slots,
            agent_names={int(k): v for k, v in session.agent_names.items()},
            agent_identity_text_by_slot={int(k): v for k, v in tab1.agent_identity_text_by_slot.items()},
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/session/{session_id}/tab1", response_model=Tab1InputResponse)
def get_tab1_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        data = get_session_detail(db, session_id)
        session = data["session"]
        tab1 = data["tab1"]
        return Tab1InputResponse(
            world_text=tab1.world_text,
            chapter_text=tab1.chapter_text,
            selected_agent_slots=session.selected_agent_slots,
            agent_names={int(k): v for k, v in session.agent_names.items()},
            agent_identity_text_by_slot={int(k): v for k, v in tab1.agent_identity_text_by_slot.items()},
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/session/{session_id}/lock", response_model=SessionSummary)
def lock_session_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        session = lock_tab1(db, session_id)
        return SessionSummary(
            session_id=session.session_id,
            state=session.state,
            prompt_index=session.prompt_index,
            last_summarized_prompt_index=session.last_summarized_prompt_index,
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/session/{session_id}/prompt", response_model=PromptResponse)
def prompt_endpoint(session_id: str, payload: PromptRequest, db: Session = Depends(get_db)):
    try:
        session, user_event, agent_event, summary_triggered = prompt_agent(db, session_id, payload.agent_slot, payload.user_text)
        return PromptResponse(
            session=SessionSummary(
                session_id=session.session_id,
                state=session.state,
                prompt_index=session.prompt_index,
                last_summarized_prompt_index=session.last_summarized_prompt_index,
                tab1_locked=session.tab1_locked,
            ),
            user_event=user_event,
            agent_event=agent_event,
            summary_triggered=summary_triggered,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/session/{session_id}/end", response_model=SessionSummary)
def end_chapter_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        session = end_chapter(db, session_id)
        return SessionSummary(
            session_id=session.session_id,
            state=session.state,
            prompt_index=session.prompt_index,
            last_summarized_prompt_index=session.last_summarized_prompt_index,
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/session/{session_id}/narrative-agent", response_model=SessionSummary)
def save_narrative_agent_endpoint(session_id: str, payload: NarrativeAgentRequest, db: Session = Depends(get_db)):
    try:
        session = save_narrative_agent(db, session_id, payload.narrative_agent_definition_text)
        return SessionSummary(
            session_id=session.session_id,
            state=session.state,
            prompt_index=session.prompt_index,
            last_summarized_prompt_index=session.last_summarized_prompt_index,
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/session/{session_id}/build-narrative", response_model=NarrativeBuildResponse)
def build_narrative_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        draft = build_narrative(db, session_id)
        return NarrativeBuildResponse(draft_id=draft.draft_id, chapter_text=draft.chapter_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/session/{session_id}/reset", response_model=SessionSummary)
def reset_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        session = reset_session(db, session_id)
        return SessionSummary(
            session_id=session.session_id,
            state=session.state,
            prompt_index=session.prompt_index,
            last_summarized_prompt_index=session.last_summarized_prompt_index,
            tab1_locked=session.tab1_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/session/{session_id}", response_model=SessionDetailResponse)
def get_session_endpoint(session_id: str, db: Session = Depends(get_db)):
    try:
        data = get_session_detail(db, session_id)
        session = data["session"]
        tab1 = data["tab1"]
        return SessionDetailResponse(
            session=SessionSummary(
                session_id=session.session_id,
                state=session.state,
                prompt_index=session.prompt_index,
                last_summarized_prompt_index=session.last_summarized_prompt_index,
                tab1_locked=session.tab1_locked,
            ),
            tab1=Tab1InputResponse(
                world_text=tab1.world_text,
                chapter_text=tab1.chapter_text,
                selected_agent_slots=session.selected_agent_slots,
                agent_names={int(k): v for k, v in session.agent_names.items()},
                agent_identity_text_by_slot={int(k): v for k, v in tab1.agent_identity_text_by_slot.items()},
                tab1_locked=session.tab1_locked,
            ),
            events=data["events"],
            memory_blocks=data["memory_blocks"],
            narrative_drafts=[
                NarrativeBuildResponse(draft_id=d.draft_id, chapter_text=d.chapter_text) for d in data["narrative_drafts"]
            ],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
