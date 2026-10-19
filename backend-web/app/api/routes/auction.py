"""闲鱼拍卖雷达路由"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from common.models.user import User
from common.schemas.common import ApiResponse
from common.services.auction_service import AuctionService
from common.services.xianyu_auction_client import AuctionError

router = APIRouter(tags=["拍卖雷达"])


class AuctionImportRequest(BaseModel):
    """拍卖链接导入请求"""

    url: str = Field(..., min_length=1, max_length=2000, description="闲鱼短链、商品链接或商品ID")


def get_auction_service(
    session: AsyncSession = Depends(deps.get_db_session),
) -> AuctionService:
    return AuctionService(session)


@router.post("/import", response_model=ApiResponse)
async def import_auction(
    payload: AuctionImportRequest,
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """通过链接/短链/商品ID导入一条闲鱼拍卖商品。"""
    try:
        data = await service.import_url(current_user.id, payload.url)
    except AuctionError as exc:
        return ApiResponse(success=False, code=40001, message=str(exc), data=None)
    except ValueError as exc:
        return ApiResponse(success=False, code=40002, message=str(exc), data=None)
    except Exception as exc:  # noqa: BLE001
        return ApiResponse(success=False, code=500, message=f"导入失败: {exc}", data=None)
    return ApiResponse(success=True, message="导入成功", data=data)


@router.get("/items", response_model=ApiResponse)
async def list_auction_items(
    status_filter: str | None = Query(default=None, alias="status", description="online/ended/unknown"),
    keyword: str | None = Query(default=None, max_length=100, description="标题/卖家/类目/品牌关键字"),
    ending_within_hours: int | None = Query(default=None, ge=1, le=720, description="仅看 N 小时内结束"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """分页查询拍卖雷达商品。"""
    data = await service.list_items(
        current_user.id,
        status=status_filter,
        keyword=keyword,
        ending_within_hours=ending_within_hours,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(success=True, data=data)


@router.get("/stats", response_model=ApiResponse)
async def auction_stats(
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """拍卖雷达基础统计。"""
    return ApiResponse(success=True, data=await service.stats(current_user.id))


@router.get("/items/{item_pk}", response_model=ApiResponse)
async def get_auction_item(
    item_pk: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """拍卖商品详情。"""
    item = await service.get_item(current_user.id, item_pk)
    if item is None:
        return ApiResponse(success=False, code=40400, message="拍卖商品不存在", data=None)
    return ApiResponse(success=True, data=item)


@router.post("/items/{item_pk}/refresh", response_model=ApiResponse)
async def refresh_auction_item(
    item_pk: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """重新抓取并更新拍卖商品。"""
    try:
        data = await service.refresh_item(current_user.id, item_pk)
    except AuctionError as exc:
        return ApiResponse(success=False, code=40001, message=str(exc), data=None)
    except ValueError as exc:
        return ApiResponse(success=False, code=40400, message=str(exc), data=None)
    except Exception as exc:  # noqa: BLE001
        return ApiResponse(success=False, code=500, message=f"刷新失败: {exc}", data=None)
    return ApiResponse(success=True, message="刷新成功", data=data)


@router.delete("/items/{item_pk}", response_model=ApiResponse)
async def delete_auction_item(
    item_pk: int,
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """软删除一条拍卖商品。"""
    deleted = await service.delete_item(current_user.id, item_pk)
    if not deleted:
        return ApiResponse(success=False, code=40400, message="拍卖商品不存在", data=None)
    return ApiResponse(success=True, message="已删除")
