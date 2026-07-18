from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AuditLog, SavedFilter, UserRole
from app.routers.auth import TenantContext, get_tenant_context
from app.schemas import CreateSavedFilterRequest, UpdateSavedFilterRequest

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])


def serialize_filter(saved_filter: SavedFilter, context: TenantContext) -> dict:
    can_manage = (
        saved_filter.user_id == context.user.id
        or context.user.role in (UserRole.admin, UserRole.super_admin)
    )
    return {
        "id": saved_filter.id,
        "name": saved_filter.name,
        "data": saved_filter.data,
        "creator_user_id": saved_filter.user_id,
        "can_edit": can_manage,
        "can_delete": can_manage,
    }


@router.get("/")
async def list_saved_filters(
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(SavedFilter)
        .where(SavedFilter.tahfiz_id == context.tahfiz_id)
        .order_by(SavedFilter.created_at.desc())
    )
    return [
        serialize_filter(saved_filter, context)
        for saved_filter in result.scalars().all()
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
    return serialize_filter(sf, context)


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
            SavedFilter.tahfiz_id == context.tahfiz_id,
        )
    )
    sf = result.scalar_one_or_none()
    if not sf:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    if sf.user_id != context.user.id and context.user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can edit this filter")

    if body.name is not None:
        sf.name = body.name
    if body.data is not None:
        sf.data = body.data
    await db.commit()
    return serialize_filter(sf, context)


@router.delete("/{filter_id}")
async def delete_saved_filter(
    filter_id: int,
    db: AsyncSession = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    result = await db.execute(
        select(SavedFilter).where(
            SavedFilter.id == filter_id,
            SavedFilter.tahfiz_id == context.tahfiz_id,
        )
    )
    sf = result.scalar_one_or_none()
    if not sf:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    if sf.user_id != context.user.id and context.user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can delete this filter")

    db.add(AuditLog(
        actor_user_id=context.user.id,
        tahfiz_id=context.tahfiz_id,
        action="saved_filter.deleted",
        details=f"filter={sf.id}; name={sf.name}",
    ))
    await db.delete(sf)
    await db.commit()
    return {"message": "Filter deleted"}
