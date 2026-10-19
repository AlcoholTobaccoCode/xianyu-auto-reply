"""
闲鱼拍卖雷达服务

功能：
1. 链接/商品ID导入：解析并抓取闲鱼公开详情，按 (owner_id, platform, item_id) 去重更新
2. 列表/详情/刷新/软删除
3. 基础统计

说明：
- 只做“雷达”，不做自动出价；出价仍在闲鱼 App 人工完成。
- 公开详情拿不到出价次数/保证金/加价幅度时保留空值，并在 warnings 中提示。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.auction_item import AuctionItem
from common.services.xianyu_auction_client import fetch_auction
from common.utils.time_utils import get_beijing_now_naive


class AuctionService:
    """闲鱼拍卖雷达服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # 导入 / 刷新
    # ------------------------------------------------------------------
    async def import_url(self, owner_id: int, url: str, *, source_account_id: Optional[str] = None) -> Dict[str, Any]:
        """通过闲鱼链接/短链/商品ID导入拍卖商品。"""
        parsed = await fetch_auction(url)
        item = await self._upsert(owner_id, parsed, source="url", source_account_id=source_account_id)
        return self.serialize(item, include_raw=True)

    async def refresh_item(self, owner_id: int, item_pk: int) -> Dict[str, Any]:
        """重新抓取并更新一条拍卖商品。"""
        item = await self.get_model(owner_id, item_pk)
        if item is None:
            raise ValueError("拍卖商品不存在")
        parsed = await fetch_auction(item.detail_url or item.item_id)
        item = await self._upsert(
            owner_id, parsed, source=item.source or "url", source_account_id=item.source_account_id
        )
        return self.serialize(item, include_raw=True)

    async def _upsert(
        self,
        owner_id: int,
        parsed: Dict[str, Any],
        *,
        source: str,
        source_account_id: Optional[str],
    ) -> AuctionItem:
        platform = parsed.get("platform") or "xianyu"
        item_id = str(parsed.get("item_id") or "").strip()
        if not item_id:
            raise ValueError("解析结果缺少商品ID")

        stmt = select(AuctionItem).where(
            AuctionItem.owner_id == owner_id,
            AuctionItem.platform == platform,
            AuctionItem.item_id == item_id,
        )
        item = (await self.session.execute(stmt)).scalars().first()
        if item is None:
            item = AuctionItem(owner_id=owner_id, platform=platform, item_id=item_id)
            self.session.add(item)

        images = parsed.get("images") or []
        item.auction_id = parsed.get("auction_id")
        item.title = parsed.get("title") or ""
        item.description = parsed.get("description") or ""
        item.current_price = parsed.get("current_price")
        item.start_price = parsed.get("start_price")
        item.original_price = parsed.get("original_price")
        item.shipping_fee = parsed.get("shipping_fee")
        item.is_free_shipping = bool(parsed.get("is_free_shipping"))
        item.seller_id = parsed.get("seller_id") or None
        item.seller_nick = parsed.get("seller_nick") or None
        item.seller_city = parsed.get("seller_city") or None
        item.seller_good_rate = parsed.get("seller_good_rate") or None
        item.seller_item_count = parsed.get("seller_item_count")
        item.category_id = parsed.get("category_id") or None
        item.category_name = parsed.get("category_name") or None
        item.item_condition = parsed.get("condition") or None
        item.brand = parsed.get("brand") or None
        item.image_url = images[0] if images else None
        item.images = images
        item.detail_url = parsed.get("detail_url") or f"https://www.goofish.com/item?id={item_id}"
        item.auction_deposit_url = parsed.get("auction_deposit_url") or None
        item.start_at = parsed.get("start_at")
        item.end_at = parsed.get("end_at")
        item.status = parsed.get("status") or "unknown"
        item.item_status_str = parsed.get("item_status_str") or None
        item.bid_count = parsed.get("bid_count")
        item.deposit_amount = parsed.get("deposit_amount")
        item.increment_amount = parsed.get("increment_amount")
        item.warnings = parsed.get("warnings") or []
        item.raw_json = parsed.get("raw") or None
        item.fetched_at = parsed.get("fetched_at") or get_beijing_now_naive()
        item.source = source
        item.source_account_id = source_account_id
        item.is_deleted = False

        await self.session.commit()
        await self.session.refresh(item)
        return item

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get_model(self, owner_id: int, item_pk: int) -> Optional[AuctionItem]:
        stmt = select(AuctionItem).where(
            AuctionItem.id == item_pk,
            AuctionItem.owner_id == owner_id,
            AuctionItem.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_item(self, owner_id: int, item_pk: int) -> Optional[Dict[str, Any]]:
        item = await self.get_model(owner_id, item_pk)
        return self.serialize(item, include_raw=True) if item else None

    async def list_items(
        self,
        owner_id: int,
        *,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        ending_within_hours: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        conditions = [AuctionItem.owner_id == owner_id, AuctionItem.is_deleted.is_(False)]
        if status:
            conditions.append(AuctionItem.status == status)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AuctionItem.title.like(like_value),
                    AuctionItem.seller_nick.like(like_value),
                    AuctionItem.category_name.like(like_value),
                    AuctionItem.brand.like(like_value),
                )
            )
        if ending_within_hours is not None and ending_within_hours > 0:
            now = get_beijing_now_naive()
            conditions.append(AuctionItem.end_at.is_not(None))
            conditions.append(AuctionItem.end_at >= now)
            conditions.append(AuctionItem.end_at <= now + timedelta(hours=ending_within_hours))

        total_stmt = select(func.count()).select_from(AuctionItem).where(*conditions)
        total = int((await self.session.execute(total_stmt)).scalar() or 0)

        offset = (page - 1) * page_size
        stmt = (
            select(AuctionItem)
            .where(*conditions)
            .order_by(
                AuctionItem.status == "ended",
                AuctionItem.end_at.is_(None),
                AuctionItem.end_at.asc(),
                AuctionItem.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        items = (await self.session.execute(stmt)).scalars().all()
        total_pages = (total + page_size - 1) // page_size if page_size else 0
        return {
            "items": [self.serialize(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def delete_item(self, owner_id: int, item_pk: int) -> bool:
        item = await self.get_model(owner_id, item_pk)
        if item is None:
            return False
        item.is_deleted = True
        await self.session.commit()
        return True

    async def stats(self, owner_id: int) -> Dict[str, Any]:
        now = get_beijing_now_naive()
        base = [AuctionItem.owner_id == owner_id, AuctionItem.is_deleted.is_(False)]

        async def _count(*extra) -> int:
            stmt = select(func.count()).select_from(AuctionItem).where(*base, *extra)
            return int((await self.session.execute(stmt)).scalar() or 0)

        return {
            "total": await _count(),
            "online": await _count(AuctionItem.status == "online"),
            "ended": await _count(AuctionItem.status == "ended"),
            "ending_24h": await _count(
                AuctionItem.end_at.is_not(None),
                AuctionItem.end_at >= now,
                AuctionItem.end_at <= now + timedelta(hours=24),
            ),
            "missing_end_time": await _count(AuctionItem.end_at.is_(None)),
            "warnings": await _count(AuctionItem.warnings.is_not(None)),
        }

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def serialize(self, item: AuctionItem, *, include_raw: bool = False) -> Dict[str, Any]:
        def amount(value: Optional[Decimal]) -> Optional[float]:
            return float(value) if value is not None else None

        def dt(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if value is not None else None

        data: Dict[str, Any] = {
            "id": item.id,
            "platform": item.platform,
            "item_id": item.item_id,
            "auction_id": item.auction_id,
            "title": item.title or "",
            "description": item.description or "",
            "current_price": amount(item.current_price),
            "start_price": amount(item.start_price),
            "original_price": amount(item.original_price),
            "shipping_fee": amount(item.shipping_fee),
            "is_free_shipping": bool(item.is_free_shipping),
            "seller_id": item.seller_id or "",
            "seller_nick": item.seller_nick or "",
            "seller_city": item.seller_city or "",
            "seller_good_rate": item.seller_good_rate or "",
            "seller_item_count": item.seller_item_count,
            "category_id": item.category_id or "",
            "category_name": item.category_name or "",
            "condition": item.item_condition or "",
            "brand": item.brand or "",
            "image_url": item.image_url or "",
            "images": item.images or [],
            "detail_url": item.detail_url or "",
            "auction_deposit_url": item.auction_deposit_url or "",
            "start_at": dt(item.start_at),
            "end_at": dt(item.end_at),
            "status": item.status,
            "item_status_str": item.item_status_str or "",
            "bid_count": item.bid_count,
            "deposit_amount": amount(item.deposit_amount),
            "increment_amount": amount(item.increment_amount),
            "warnings": item.warnings or [],
            "fetched_at": dt(item.fetched_at),
            "source": item.source,
            "source_account_id": item.source_account_id,
            "created_at": dt(item.created_at),
            "updated_at": dt(item.updated_at),
        }
        if include_raw:
            data["raw_json"] = item.raw_json
        return data
