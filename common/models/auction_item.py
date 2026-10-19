"""
闲鱼拍卖雷达商品模型

功能：
1. 存储通过链接导入 / 后续搜索采集到的闲鱼拍卖商品
2. 保留当前价、起拍价、起止时间、卖家、成色、图片等雷达字段
3. 按 owner_id 做多用户隔离

说明：
- 闲鱼公开详情不返回出价次数/保证金/加价幅度，这些字段允许为空，后续通过登录态接口补齐。
- 同一用户同一平台的同一商品只保留一条记录，重复导入做更新。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


class AuctionItem(TimestampMixin, Base):
    """闲鱼拍卖雷达商品表"""

    __tablename__ = "xy_auction_items"
    __table_args__ = (
        UniqueConstraint("owner_id", "platform", "item_id", name="uk_auction_owner_platform_item"),
        Index("idx_auction_owner_end", "owner_id", "end_at"),
        Index("idx_auction_owner_status", "owner_id", "status"),
        Index("idx_auction_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="归属用户ID")
    platform: Mapped[str] = mapped_column(
        String(16), nullable=False, default="xianyu", server_default="xianyu", comment="平台：xianyu"
    )
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="闲鱼商品ID")
    auction_id: Mapped[str | None] = mapped_column(String(64), comment="闲鱼拍卖ID")

    title: Mapped[str | None] = mapped_column(Text, comment="商品标题")
    description: Mapped[str | None] = mapped_column(Text, comment="商品描述")

    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="当前价")
    start_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="起拍价")
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="原价")
    shipping_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="运费")
    is_free_shipping: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0", comment="是否包邮"
    )

    seller_id: Mapped[str | None] = mapped_column(String(64), comment="卖家ID")
    seller_nick: Mapped[str | None] = mapped_column(String(120), comment="卖家昵称")
    seller_city: Mapped[str | None] = mapped_column(String(120), comment="卖家城市")
    seller_good_rate: Mapped[str | None] = mapped_column(String(32), comment="卖家好评率")
    seller_item_count: Mapped[int | None] = mapped_column(Integer, comment="卖家在售商品数")

    category_id: Mapped[str | None] = mapped_column(String(64), comment="类目ID")
    category_name: Mapped[str | None] = mapped_column(String(120), comment="类目名称")
    item_condition: Mapped[str | None] = mapped_column("item_condition", String(64), comment="成色")
    brand: Mapped[str | None] = mapped_column(String(120), comment="品牌")

    image_url: Mapped[str | None] = mapped_column(String(1000), comment="主图URL")
    images: Mapped[list | None] = mapped_column(JSON, comment="图片URL列表")
    detail_url: Mapped[str | None] = mapped_column(String(1000), comment="商品详情URL")
    auction_deposit_url: Mapped[str | None] = mapped_column(String(1000), comment="保证金缴纳页URL")

    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="拍卖开始时间")
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="拍卖结束时间")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="online", server_default="online", comment="状态：online/ended/unknown"
    )
    item_status_str: Mapped[str | None] = mapped_column(String(32), comment="闲鱼原始状态文本")

    bid_count: Mapped[int | None] = mapped_column(Integer, comment="出价次数（公开详情可能为空）")
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="保证金（公开详情可能为空）")
    increment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), comment="加价幅度（公开详情可能为空）")

    warnings: Mapped[list | None] = mapped_column(JSON, comment="数据缺口提示")
    raw_json: Mapped[dict | None] = mapped_column(JSON, comment="解析后的原始详情（精简）")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最近抓取时间")

    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="url", server_default="url", comment="来源：url-链接导入，search-搜索采集"
    )
    source_account_id: Mapped[str | None] = mapped_column(String(80), comment="采集使用的账号ID")
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0", comment="是否软删除"
    )
