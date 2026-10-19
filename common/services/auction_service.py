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

import asyncio
import random
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.auction_item import AuctionItem
from common.models.xy_account import XYAccount
from common.services.xianyu_auction_client import fetch_auction
from common.services.xianyu_search_client import XianyuSearchClient, parse_search_auction
from common.utils.time_utils import get_beijing_now_naive


class AuctionService:
    """闲鱼拍卖雷达服务"""

    # 搜索风控冷却：按账号记录，避免连续嗅探把账号打到 FAIL_SYS_USER_VALIDATE
    _last_discover_at: Dict[str, float] = {}
    _captcha_until: Dict[str, float] = {}

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

    # ------------------------------------------------------------------
    # 关键词搜索嗅探
    # ------------------------------------------------------------------
    async def discover(
        self,
        owner_id: int,
        keywords: List[str] | str,
        *,
        account_id: Optional[str] = None,
        pages: int = 1,
        only_active: bool = True,
    ) -> Dict[str, Any]:
        """用已登录闲鱼账号按关键词搜索拍卖并入库。

        - 只调用搜索接口，不逐条拉详情，避免高频触发 RGV587
        - 默认只保留 end_at > now 的进行中拍卖；同一商品去重
        """
        started = datetime.now()
        cleaned: List[str] = []
        raw_keywords = [keywords] if isinstance(keywords, str) else list(keywords or [])
        for value in raw_keywords:
            for part in re.split(r"[\n\r,，;；]+", str(value or "")):
                keyword = part.strip()
                if keyword and keyword not in cleaned:
                    cleaned.append(keyword)
        if not cleaned:
            raise ValueError("请至少输入一个关键词")
        if len(cleaned) > 6:
            raise ValueError("一次最多 6 个关键词")
        try:
            pages = max(1, min(int(pages or 1), 2))
        except (TypeError, ValueError):
            pages = 1
        if len(cleaned) * pages > 6:
            raise ValueError("一次最多 6 次搜索（关键词×页数），请减少关键词或页数")

        account = await self._get_discovery_account(owner_id, account_id)

        now_ts = time.monotonic()
        captcha_until = self._captcha_until.get(account.account_id, 0)
        if captcha_until > now_ts:
            remaining = max(1, int((captcha_until - now_ts + 59) // 60))
            raise ValueError(
                f"该账号搜索触发风控，冷却中，请约 {remaining} 分钟后再试；IM 连接不受影响"
            )
        last_at = self._last_discover_at.get(account.account_id, 0)
        if last_at and now_ts - last_at < 60:
            raise ValueError("嗅探间隔太短，请 60 秒后再试，避免触发风控")
        self._last_discover_at[account.account_id] = now_ts

        client = XianyuSearchClient(
            account.account_id,
            account.cookie,
            owner_id=owner_id,
            proxy=self._build_proxy_url(account),
        )

        scanned = auction_count = active_count = skipped = requests_sent = 0
        errors: List[str] = []
        parsed_by_id: Dict[str, Dict[str, Any]] = {}

        for keyword in cleaned:
            for page in range(1, pages + 1):
                requests_sent += 1
                try:
                    result = await client.search(keyword, page_number=page, rows_per_page=30)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{keyword} 第{page}页：{exc}")
                    continue

                if not result.get("success"):
                    message = str(result.get("error") or "搜索失败")
                    if result.get("account_invalid") or result.get("punish_url"):
                        self._captcha_until[account.account_id] = time.monotonic() + 1200
                        raise ValueError(
                            f"闲鱼搜索触发滑块/风控（{message}）。已暂停该账号 20 分钟；"
                            "IM 连接不受影响。请减少关键词和页数，稍后再试；若仍失败请重新扫码登录。"
                        )
                    errors.append(f"{keyword} 第{page}页：{message}")
                    continue

                items = result.get("items") or []
                scanned += len(items)
                for entry in items:
                    parsed = parse_search_auction(entry, keyword=keyword)
                    if parsed is None:
                        continue
                    auction_count += 1
                    if parsed.get("status") == "online":
                        active_count += 1
                    if only_active and parsed.get("status") != "online":
                        skipped += 1
                        continue
                    parsed_by_id[parsed["item_id"]] = parsed

                await asyncio.sleep(2.5 + random.random())

        created, updated = await self._upsert_search_items(
            owner_id, list(parsed_by_id.values()), account.account_id
        )
        if client.cookies_str != account.cookie:
            account.cookie = client.cookies_str
            self.session.add(account)
        await self.session.commit()

        if scanned == 0 and errors:
            raise ValueError("搜索失败：" + "；".join(errors[:3]))

        return {
            "account_id": account.account_id,
            "keywords": cleaned,
            "pages": pages,
            "requests_sent": requests_sent,
            "scanned": scanned,
            "auction_count": auction_count,
            "active_count": active_count,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors[:5],
            "duration_ms": int((datetime.now() - started).total_seconds() * 1000),
        }

    async def _get_discovery_account(self, owner_id: int, account_id: Optional[str]) -> XYAccount:
        conditions = [
            XYAccount.owner_id == owner_id,
            XYAccount.status == "active",
            XYAccount.cookie.is_not(None),
            XYAccount.cookie != "",
        ]
        if account_id:
            conditions.append(XYAccount.account_id == str(account_id).strip())
        stmt = select(XYAccount).where(*conditions).order_by(XYAccount.id.asc())
        account = (await self.session.execute(stmt)).scalars().first()
        if account is None:
            if account_id:
                raise ValueError(f"账号 {account_id} 不存在、未登录或已失效")
            raise ValueError("请先在账号管理中添加并扫码登录一个闲鱼账号")
        return account

    def _build_proxy_url(self, account: XYAccount) -> Optional[str]:
        proxy_type = (account.proxy_type or "none").strip().lower()
        if proxy_type in ("", "none") or not account.proxy_host:
            return None
        scheme = proxy_type if "://" in proxy_type else f"{proxy_type}://"
        auth = ""
        if account.proxy_user:
            auth = f"{quote(account.proxy_user, safe='')}:{quote(account.proxy_pass or '', safe='')}@"
        port = f":{account.proxy_port}" if account.proxy_port else ""
        return f"{scheme}{auth}{account.proxy_host}{port}"

    async def _upsert_search_items(
        self,
        owner_id: int,
        parsed_items: List[Dict[str, Any]],
        account_id: str,
    ) -> tuple[int, int]:
        """搜索结果的增量入库：只刷新搜索能拿到的字段，不覆盖详情已有字段。"""
        if not parsed_items:
            return 0, 0

        item_ids = list({str(item.get("item_id")) for item in parsed_items if item.get("item_id")})
        stmt = select(AuctionItem).where(
            AuctionItem.owner_id == owner_id,
            AuctionItem.platform == "xianyu",
            AuctionItem.item_id.in_(item_ids),
        )
        existing = {
            item.item_id: item
            for item in (await self.session.execute(stmt)).scalars().all()
        }

        created = updated = 0
        for parsed in parsed_items:
            item_id = str(parsed.get("item_id") or "")
            if not item_id:
                continue
            item = existing.get(item_id)
            if item is not None and item.is_deleted:
                # 用户主动删除过的记录不自动复活
                continue

            if item is None:
                item = AuctionItem(owner_id=owner_id, platform="xianyu", item_id=item_id)
                self.session.add(item)
                existing[item_id] = item
                created += 1
                item.description = ""
                item.auction_id = None
                item.start_price = None
                item.original_price = None
                item.shipping_fee = None
                item.seller_good_rate = None
                item.seller_item_count = None
                item.category_name = None
                item.item_condition = None
                item.brand = None
                item.auction_deposit_url = None
                item.item_status_str = None
                item.bid_count = None
                item.deposit_amount = None
                item.increment_amount = None
                item.warnings = parsed.get("warnings") or []
                item.raw_json = parsed.get("raw")
                item.source = "search"
                item.source_account_id = account_id
            else:
                updated += 1
                if item.source in (None, "", "search"):
                    item.source = "search"
                item.source_account_id = item.source_account_id or account_id
                if not item.warnings:
                    item.warnings = parsed.get("warnings") or []
                if not item.raw_json:
                    item.raw_json = parsed.get("raw")

            # 搜索能稳定拿到的字段：每次刷新
            item.title = parsed.get("title") or item.title or ""
            if parsed.get("current_price") is not None:
                item.current_price = parsed.get("current_price")
            item.seller_id = parsed.get("seller_id") or item.seller_id
            item.seller_nick = parsed.get("seller_nick") or item.seller_nick
            item.seller_city = parsed.get("seller_city") or item.seller_city
            item.category_id = parsed.get("category_id") or item.category_id
            item.is_free_shipping = bool(parsed.get("is_free_shipping")) or bool(item.is_free_shipping)
            if not item.image_url:
                images = parsed.get("images") or []
                item.image_url = images[0] if images else item.image_url
            if not item.images:
                item.images = parsed.get("images") or []
            item.detail_url = parsed.get("detail_url") or item.detail_url
            item.start_at = parsed.get("start_at") or item.start_at
            item.end_at = parsed.get("end_at") or item.end_at
            if parsed.get("end_at") is not None:
                item.status = parsed.get("status") or item.status
            elif item.status not in ("online", "ended"):
                item.status = parsed.get("status") or item.status
            item.fetched_at = parsed.get("fetched_at") or get_beijing_now_naive()
            item.is_deleted = False

        return created, updated

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
