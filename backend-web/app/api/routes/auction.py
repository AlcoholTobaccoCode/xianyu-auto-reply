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


class AuctionDiscoverRequest(BaseModel):
    """关键词搜索嗅探请求"""

    keywords: list[str] = Field(..., min_length=1, max_length=6, description="关键词列表")
    account_id: str | None = Field(default=None, max_length=80, description="指定闲鱼账号；不传则用第一个可用账号")
    pages: int = Field(default=1, ge=1, le=2, description="每个关键词搜索页数")
    only_active: bool = Field(default=True, description="只入库进行中的拍卖")


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


@router.post("/discover", response_model=ApiResponse)
async def discover_auctions(
    payload: AuctionDiscoverRequest,
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """用已登录闲鱼账号按关键词搜索拍卖，自动入库。"""
    try:
        data = await service.discover(
            current_user.id,
            payload.keywords,
            account_id=payload.account_id,
            pages=payload.pages,
            only_active=payload.only_active,
        )
    except ValueError as exc:
        return ApiResponse(success=False, code=40002, message=str(exc), data=None)
    except Exception as exc:  # noqa: BLE001
        return ApiResponse(success=False, code=500, message=f"嗅探失败: {exc}", data=None)

    message = (
        f"扫描 {data['scanned']} 条，发现 {data['auction_count']} 场拍卖，"
        f"新增 {data['created']}，更新 {data['updated']}"
    )
    if data.get("errors"):
        message += f"；{len(data['errors'])} 个关键词失败"
    return ApiResponse(success=True, message=message, data=data)


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


@router.get("/items/{item_pk}/references", response_model=ApiResponse)
async def auction_reference_prices(
    item_pk: int,
    keyword: str | None = Query(default=None, max_length=80, description="自定义同款搜索词"),
    refresh: bool = Query(default=False, description="跳过 30 分钟缓存，强制重新搜索"),
    current_user: User = Depends(deps.get_current_active_user),
    service: AuctionService = Depends(get_auction_service),
) -> ApiResponse:
    """查询同款普通在售商品，作为拍卖出价的参考价。"""
    try:
        data = await service.get_reference_prices(
            current_user.id,
            item_pk,
            keyword=keyword,
            refresh=refresh,
        )
    except ValueError as exc:
        return ApiResponse(success=False, code=40002, message=str(exc), data=None)
    except Exception as exc:  # noqa: BLE001
        return ApiResponse(success=False, code=500, message=f"参考价查询失败: {exc}", data=None)

    count = (data.get("stats") or {}).get("count", 0)
    return ApiResponse(success=True, message=f"找到 {count} 条同款在售", data=data)


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
