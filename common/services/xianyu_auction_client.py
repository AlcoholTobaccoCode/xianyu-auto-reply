"""
闲鱼拍卖公开详情客户端

功能：
1. 解析闲鱼商品短链 / 商品链接 / 商品ID
2. 使用匿名 mtop 令牌调用闲鱼公开商品详情接口（无需登录 Cookie）
3. 从详情中提取拍卖标识、当前价、起拍价、起止时间、卖家、成色、图片等字段

说明：
- 闲鱼网页端不展示拍卖出价按钮，出价需要到 App 完成；本客户端只负责“看”，不负责“出价”。
- 公开详情里不一定有出价次数、保证金、加价幅度；拿不到的字段会保留 None，并在 warnings 中提示。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from common.utils.xianyu_utils import generate_sign

MTOP_HOST = "https://h5api.m.goofish.com"
DETAIL_API = "mtop.taobao.idle.pc.detail"
DETAIL_VERSION = "1.0"
APP_KEY = "34839810"
BEIJING_TZ = timezone(timedelta(hours=8))

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ITEM_ID_PATTERNS = (
    re.compile(r"[?&]itemId=(\d+)"),
    re.compile(r"[?&]item_id=(\d+)"),
    re.compile(r"[?&]id=(\d+)"),
    re.compile(r"/item/(\d+)"),
    re.compile(r'"itemId"\s*:\s*"?(\d+)"?'),
)


class AuctionError(RuntimeError):
    """拍卖客户端基础异常"""


class AuctionResolveError(AuctionError):
    """短链 / 商品链接解析失败"""


class AuctionFetchError(AuctionError):
    """闲鱼接口调用失败"""


class NotAuctionItemError(AuctionError):
    """商品不是拍卖商品"""


def _to_decimal(value: Any) -> Optional[Decimal]:
    """把接口里的金额字符串转成 Decimal；非法值返回 None。"""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    """把接口里的整数字符串转成 int；非法值返回 None。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ms_to_beijing_naive(value: Any) -> Optional[datetime]:
    """毫秒时间戳转北京时间 naive datetime，和项目其它任务的时间口径保持一致。"""
    if value in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=BEIJING_TZ).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _extract_item_id(text: str) -> Optional[str]:
    """从链接 / HTML / JSON 文本里提取商品 ID。"""
    for pattern in _ITEM_ID_PATTERNS:
        matched = pattern.search(text or "")
        if matched:
            return matched.group(1)
    return None


async def resolve_item_id(value: str) -> str:
    """把闲鱼短链、商品链接或纯商品 ID 统一解析成商品 ID。

    Args:
        value: 例如 https://m.tb.cn/h.xxx?tk=...、https://www.goofish.com/item?id=123、123

    Returns:
        纯数字商品 ID

    Raises:
        AuctionResolveError: 无法从输入中解析出商品 ID
    """
    raw = (value or "").strip()
    if not raw:
        raise AuctionResolveError("链接或商品ID为空")

    if raw.isdigit():
        return raw

    direct = _extract_item_id(raw)
    if direct:
        return direct

    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raise AuctionResolveError(f"无法识别的链接或商品ID: {raw}")

    timeout = aiohttp.ClientTimeout(total=25)
    headers = {"User-Agent": _MOBILE_UA, "Accept": "text/html,application/xhtml+xml"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(raw, allow_redirects=True) as response:
                text = await response.text(errors="ignore")
                final_url = str(response.url)
    except Exception as exc:  # noqa: BLE001
        raise AuctionResolveError(f"短链请求失败: {type(exc).__name__}: {exc}") from exc

    for candidate in (final_url, text):
        item_id = _extract_item_id(candidate)
        if item_id:
            return item_id

    raise AuctionResolveError("链接里没有解析到闲鱼商品ID")


class XianyuAuctionClient:
    """闲鱼拍卖公开详情客户端（匿名令牌，无需登录）"""

    def __init__(self, *, timeout_seconds: int = 25):
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: Optional[aiohttp.ClientSession] = None
        self._headers = {
            "User-Agent": _DESKTOP_UA,
            "Accept": "application/json",
            "Origin": "https://www.goofish.com",
            "Referer": "https://www.goofish.com/",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers=self._headers,
                cookie_jar=aiohttp.CookieJar(),
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "XianyuAuctionClient":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _current_token(self) -> str:
        """从 aiohttp CookieJar 里读取 _m_h5_tk 的签名部分。"""
        if self._session is None:
            return ""
        try:
            for cookie in self._session.cookie_jar:
                if cookie.key == "_m_h5_tk":
                    return str(cookie.value).split("_")[0]
        except Exception:  # noqa: BLE001
            return ""
        return ""

    async def _call_once(self, api: str, version: str, data: Dict[str, Any]) -> Dict[str, Any]:
        session = await self._get_session()
        token = self._current_token()
        timestamp = str(int(time.time() * 1000))
        data_value = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        sign = generate_sign(timestamp, token, data_value, app_key=APP_KEY)
        params = {
            "jsv": "2.7.2",
            "appKey": APP_KEY,
            "t": timestamp,
            "sign": sign,
            "v": version,
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": "20000",
            "api": api,
            "sessionOption": "AutoLoginOnly",
        }
        url = f"{MTOP_HOST}/h5/{api}/{version}/"
        async with session.post(url, params=params, data={"data": data_value}) as response:
            text = await response.text()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AuctionFetchError(f"闲鱼接口返回非JSON: {text[:200]}") from exc
        if not isinstance(payload, dict):
            raise AuctionFetchError(f"闲鱼接口返回结构异常: {type(payload).__name__}")
        return payload

    async def call(self, api: str, version: str, data: Dict[str, Any], retries: int = 4) -> Dict[str, Any]:
        """调用 mtop 接口；自动处理首次令牌为空、令牌过期和轻量风控重试。"""
        last_error = ""
        for attempt in range(retries):
            payload = await self._call_once(api, version, data)
            ret = payload.get("ret") or []
            first = ret[0] if ret else ""
            if first.startswith("SUCCESS"):
                return payload

            last_error = first or json.dumps(payload, ensure_ascii=False)[:200]
            if any(marker in first for marker in ("TOKEN_EMPTY", "TOKEN_EXPIRED", "TOKEN_EXOIRED", "令牌为空", "令牌过期")):
                await asyncio.sleep(0.4)
                continue
            if "RGV587" in first or "被挤爆" in first or "FAIL_SYS_USER_VALIDATE" in first:
                await asyncio.sleep(0.8 + attempt * 0.5)
                continue
            break
        raise AuctionFetchError(f"闲鱼接口失败: {last_error}")

    async def get_detail(self, item_id: str) -> Dict[str, Any]:
        """获取商品公开详情原始 data。"""
        payload = await self.call(DETAIL_API, DETAIL_VERSION, {"itemId": str(item_id)})
        data = payload.get("data") or {}
        if not isinstance(data, dict) or not data.get("itemDO"):
            raise AuctionFetchError("商品详情为空（商品可能已删除/下架/风控）")
        return data


def _find_bid_item_attrs(seller: Dict[str, Any], auction_id: Any) -> Dict[str, Any]:
    """在卖家其它商品里找到当前拍卖对应的 bidItem 属性。

    闲鱼公开详情没有直接的结束时间字段，但 sellerDO.sellerItems[*].attributeMap
    里可能带有 bidItemId / bidItemBeginTime / bidItemEndTime / firstPrice。
    只有 bidItemId 与当前 auctionId 相同时才采用，避免拿到同卖家其它拍卖的时间。
    """
    if auction_id in (None, ""):
        return {}
    for seller_item in seller.get("sellerItems") or []:
        attribute_map = seller_item.get("attributeMap") or {}
        if str(attribute_map.get("bidItemId")) == str(auction_id):
            return attribute_map
    return {}


def parse_auction_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """把闲鱼商品详情 data 解析成拍卖雷达需要的标准字段。

    Raises:
        NotAuctionItemError: 商品不是拍卖商品
        AuctionFetchError: 详情缺少关键结构
    """
    item = data.get("itemDO") or {}
    seller = data.get("sellerDO") or {}
    auction = item.get("auctionDO") or {}

    item_id = str(item.get("itemId") or "").strip()
    if not item_id:
        raise AuctionFetchError("详情缺少 itemId")

    item_type = str(item.get("itemType") or "")
    auction_id = auction.get("auctionId")
    if item_type != "detailAuction" and auction_id in (None, ""):
        raise NotAuctionItemError(f"商品不是拍卖商品（itemType={item_type or '空'}）")

    bid_attrs = _find_bid_item_attrs(seller, auction_id)
    labels: Dict[str, str] = {}
    for label in item.get("itemLabelExtList") or []:
        key = label.get("propertyText") or label.get("text")
        value = label.get("valueText")
        if key and value:
            labels[str(key)] = str(value)

    shipping_fee = _to_decimal(item.get("transportFee"))
    free_shipping_tag = any(
        str((tag or {}).get("text") or "") == "包邮"
        for tag in (item.get("commonTags") or [])
        if isinstance(tag, dict)
    )
    is_free_shipping = bool(free_shipping_tag or (shipping_fee is not None and shipping_fee == 0))

    start_price = _to_decimal(bid_attrs.get("firstPrice"))
    if start_price is None:
        matched = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*元?\s*起拍", str(item.get("title") or ""))
        if matched:
            start_price = _to_decimal(matched.group(1))

    images: List[str] = []
    for image in item.get("imageInfos") or []:
        if isinstance(image, dict) and image.get("url"):
            images.append(str(image["url"]))
        elif isinstance(image, str):
            images.append(image)
        if len(images) >= 20:
            break

    end_at = _ms_to_beijing_naive(bid_attrs.get("bidItemEndTime"))
    start_at = _ms_to_beijing_naive(bid_attrs.get("bidItemBeginTime"))
    item_status_str = str(item.get("itemStatusStr") or "").strip()
    status = "online" if item_status_str == "在线" else (item_status_str or "unknown")
    now_beijing = datetime.now(BEIJING_TZ).replace(tzinfo=None)
    if end_at is not None and end_at <= now_beijing:
        status = "ended"

    warnings: List[str] = []
    if not bid_attrs:
        warnings.append("公开详情未返回结束时间，需在闲鱼 App 查看")
    if auction_id in (None, ""):
        warnings.append("公开详情未返回拍卖ID")
    warnings.append("出价次数/保证金/加价幅度公开详情不返回，需在闲鱼 App 查看")

    raw = {
        "itemDO": {
            "itemId": item.get("itemId"),
            "itemType": item.get("itemType"),
            "title": item.get("title"),
            "desc": item.get("desc"),
            "soldPrice": item.get("soldPrice"),
            "originalPrice": item.get("originalPrice"),
            "transportFee": item.get("transportFee"),
            "itemStatus": item.get("itemStatus"),
            "itemStatusStr": item.get("itemStatusStr"),
            "categoryId": item.get("categoryId"),
            "itemCatDTO": item.get("itemCatDTO"),
            "gmtCreate": item.get("gmtCreate"),
            "commonTags": item.get("commonTags"),
            "itemLabelExtList": item.get("itemLabelExtList"),
        },
        "auctionDO": auction,
        "sellerDO": {
            "sellerId": seller.get("sellerId"),
            "nick": seller.get("nick"),
            "city": seller.get("city"),
            "newGoodRatioRate": seller.get("newGoodRatioRate"),
            "itemCount": seller.get("itemCount"),
            "hasSoldNumInteger": seller.get("hasSoldNumInteger"),
            "zhimaAuth": seller.get("zhimaAuth"),
        },
        "bidItem": bid_attrs or None,
    }

    return {
        "platform": "xianyu",
        "item_id": item_id,
        "auction_id": str(auction_id) if auction_id not in (None, "") else None,
        "title": str(item.get("title") or ""),
        "description": str(item.get("desc") or ""),
        "current_price": _to_decimal(item.get("soldPrice")),
        "start_price": start_price,
        "original_price": _to_decimal(item.get("originalPrice")),
        "shipping_fee": shipping_fee,
        "is_free_shipping": is_free_shipping,
        "seller_id": str(seller.get("sellerId") or ""),
        "seller_nick": str(seller.get("nick") or ""),
        "seller_city": str(seller.get("city") or ""),
        "seller_good_rate": str(seller.get("newGoodRatioRate") or ""),
        "seller_item_count": _to_int(seller.get("itemCount")),
        "category_id": str(item.get("categoryId") or ""),
        "category_name": labels.get("分类", ""),
        "condition": labels.get("成色", ""),
        "brand": labels.get("品牌", ""),
        "images": images,
        "detail_url": f"https://www.goofish.com/item?id={item_id}",
        "auction_deposit_url": str(auction.get("auctionDepositUrl") or ""),
        "start_at": start_at,
        "end_at": end_at,
        "status": status,
        "item_status_str": item_status_str,
        # 公开详情拿不到，后续通过登录态搜索接口或 App 补齐
        "bid_count": None,
        "deposit_amount": None,
        "increment_amount": None,
        "fetched_at": now_beijing,
        "warnings": warnings,
        "raw": raw,
    }


async def fetch_auction(value: str, *, client: Optional[XianyuAuctionClient] = None) -> Dict[str, Any]:
    """解析链接 / 商品ID 并返回标准化的拍卖详情。"""
    item_id = await resolve_item_id(value)
    owns_client = client is None
    auction_client = client or XianyuAuctionClient()
    try:
        detail = await auction_client.get_detail(item_id)
        return parse_auction_detail(detail)
    finally:
        if owns_client:
            await auction_client.close()
