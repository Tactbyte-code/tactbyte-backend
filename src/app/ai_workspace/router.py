from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.app.ai_workspace.model import Source, Workspace, ChatSession, ChatMessage
from src.app.ai_workspace.schema import CreateWorkspace, CreateChatSession, SendMessage
from src.core.database import session
from src.app.middleware.auth import require_user
from src.app.user.model import User

router = APIRouter(prefix="/ai-workspace", tags=["AI Workspace"])


# ─── helpers ────────────────────────────────────────────────────────────────

async def get_workspace_or_404(id: int, user_id, db: AsyncSession) -> Workspace:
    query = await db.execute(
        select(Workspace).where(Workspace.id == id, Workspace.user_id == user_id)
    )
    workspace = query.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


# ─── workspaces ─────────────────────────────────────────────────────────────

@router.get("/")
async def get_workspaces(
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    query = await db.execute(
        select(Workspace)
        .where(Workspace.user_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    )
    return query.scalars().all()


@router.get("/{id}")
async def get_workspace(
    id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    return await get_workspace_or_404(id, current_user.id, db)


@router.post("/")
async def create_workspace(
    body: CreateWorkspace,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    record = Workspace(
        name=body.name,
        description=body.description,
        user_id=current_user.id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


# ─── sources ────────────────────────────────────────────────────────────────

@router.get("/{id}/sources")
async def get_sources(
    id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    query = await db.execute(
        select(Source).where(Source.workspace_id == id).order_by(Source.created_at.desc())
    )
    return query.scalars().all()


@router.post("/{id}/sources")
async def upload_source(
    id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "unknown"

    record = Source(
        workspace_id=id,
        filename=file.filename,
        source_type=ext,
        status="pending",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # TODO: kick off background processing job here

    return record


@router.delete("/{id}/sources/{source_id}")
async def delete_source(
    id: int,
    source_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    query = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == id)
    )
    source = query.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    return {"deleted": True}


# ─── chat sessions ───────────────────────────────────────────────────────────

@router.get("/{id}/sessions")
async def get_sessions(
    id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    query = await db.execute(
        select(ChatSession)
        .where(ChatSession.workspace_id == id)
        .order_by(ChatSession.created_at.desc())
    )
    return query.scalars().all()


@router.post("/{id}/sessions")
async def create_session(
    id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    record = ChatSession(workspace_id=id, title="New chat")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/{id}/sessions/{session_id}")
async def delete_session(
    id: int,
    session_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    query = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.workspace_id == id)
    )
    s = query.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(s)
    await db.commit()
    return {"deleted": True}


@router.get("/{id}/sessions/{session_id}/messages")
async def get_messages(
    id: int,
    session_id: int,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)
    
    query = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return query.scalars().all()

@router.post("/{id}/sessions/{session_id}/messages")
async def send_message(
    id: int,
    session_id: int,
    body: SendMessage,
    db: AsyncSession = Depends(session),
    current_user: User = Depends(require_user),
):
    await get_workspace_or_404(id, current_user.id, db)

    # 1. save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.commit()

    # 2. fetch sources for context
    sources = await db.execute(
        select(Source).where(Source.workspace_id == id, Source.status == "ready")
    )
    sources = sources.scalars().all()

    # 3. call LLM (Sarvam or whatever)
    # answer, citations = await run_rag(body.message, sources)
    answer = "Hello i am uday"
    citations = {
        "source_id": "12",
        "filename": "test_file.pdf",
        "excerpt": "nice to meet you"
    }

    # 4. save assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer,
        citations=citations,  # JSONB — list of {source_id, filename, excerpt}
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    return assistant_msg