#!/usr/bin/env python3
"""闲鱼拍卖详情解析 POC

用法：
    python scripts/poc_xianyu_auction.py
    python scripts/poc_xianyu_auction.py 1091907814736 1093057053936
    python scripts/poc_xianyu_auction.py "https://m.tb.cn/h.xxx?tk=..."

说明：
- 只读公开详情，不登录、不出价、不写数据库。
- 用于确认链接解析、拍卖字段和字段缺口。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.services.xianyu_auction_client import (  # noqa: E402
    XianyuAuctionClient,
    fetch_auction,
    parse_auction_detail,
    resolve_item_id,
)

DEFAULT_ITEMS = [
    "1091907814736",
    "1093057053936",
    "1092700768764",
]


def _print_item(parsed: dict) -> None:
    print("=" * 80)
    print(f"商品ID: {parsed['item_id']}  拍卖ID: {parsed['auction_id']}")
    print(f"标题: {parsed['title']}")
    print(
        f"当前价: {parsed['current_price']}  起拍价: {parsed['start_price']}  "
        f"运费: {parsed['shipping_fee']}  包邮: {parsed['is_free_shipping']}"
    )
    print(f"开始: {parsed['start_at']}  结束: {parsed['end_at']}  状态: {parsed['status']}")
    print(
        f"卖家: {parsed['seller_nick']} / {parsed['seller_city']} / "
        f"好评率 {parsed['seller_good_rate']} / 在售 {parsed['seller_item_count']}"
    )
    print(f"分类: {parsed['category_name']}  品牌: {parsed['brand']}  成色: {parsed['condition']}")
    print(f"链接: {parsed['detail_url']}")
    print(f"保证金页: {parsed['auction_deposit_url']}")
    print(f"图片数: {len(parsed['images'])}")
    for warning in parsed.get("warnings") or []:
        print(f"⚠️  {warning}")
    print("-" * 80)
    print(json.dumps(parsed, ensure_ascii=False, indent=2, default=str))


async def main(values: list[str]) -> int:
    if not values:
        values = DEFAULT_ITEMS

    failed = 0
    async with XianyuAuctionClient() as client:
        for value in values:
            try:
                item_id = await resolve_item_id(value)
                detail = await client.get_detail(item_id)
                parsed = parse_auction_detail(detail)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("=" * 80)
                print(f"解析失败: {value}")
                print(f"{type(exc).__name__}: {exc}")
                continue

            _print_item(parsed)

    print("=" * 80)
    print(f"完成：成功 {len(values) - failed} 个，失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
