from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SavedFilter
from app.routers.auth import TenantContext, get_tenant_context
from app.schemas import CreateSavedFilterRequest, SavedFilterOut, UpdateSavedFilterRequest

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])


@router.get("/")
async def list_saved_filters(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(SavedFilter)
        .where(
            SavedFilter.user_id == context.user.id,
            SavedFilter.tahfiz_id == context.tahfiz_id,
        )
        .order_by(SavedFilter.created_at.desc())
    )
    return [
        SavedFilterOut.model_validate(f).model_dump()
        for f in result.scalars().all()
    ]


@router.post("/")
async def create_saved_filter(
    body: CreateSavedFilterRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    sf = SavedFilter(user_id=context.user.id, tahfiz_id=context.tahfiz_id, name=body.name, data=body.data)
    db.add(sf)
    await db.commit()
    await db.refresh(sf)
    return SavedFilterOut.model_validate(sf).model_dump()


@router.put("/{filter_id}")
async def update_saved_filter(
    filter_id: int,
    body: UpdateSavedFilterRequest,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(SavedFilter).where(
            SavedFilter.id == filter_id,
            SavedFilter.user_id == context.user.id,
            SavedFilter.tahfiz_id == context.tahfiz_id,
        )
    )
    sf = result.scalar_one_or_none()
    if not sf:
        raise HTTPException(status_code=404, detail="Saved filter not found")

    if body.name is not None:
        sf.name = body.name
    if body.data is not None:
        sf.data = body.data
    await db.commit()
    return SavedFilterOut.model_validate(sf).model_dump()


@router.delete("/{filter_id}")
async def delete_saved_filter(
    filter_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(SavedFilter).where(
            SavedFilter.id == filter_id,
            SavedFilter.user_id == context.user.id,
            SavedFilter.tahfiz_id == context.tahfiz_id,
        )
    )
    sf = result.scalar_one_or_none()
    if not sf:
        raise HTTPException(status_code=404, detail="Saved filter not found")

    await db.delete(sf)
    await db.commit()
    return {"message": "Filter deleted"}
