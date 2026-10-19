/**
 * 闲鱼拍卖雷达 API
 *
 * 功能：
 * 1. 链接/商品ID导入
 * 2. 关键词搜索嗅探
 * 3. 分页列表、详情、刷新、删除
 * 4. 基础统计
 */
import { del, get, post } from '@/utils/request'

const PREFIX = '/api/v1/auction'

export interface AuctionItem {
  id: number
  platform: string
  item_id: string
  auction_id: string | null
  title: string
  description: string
  current_price: number | null
  start_price: number | null
  original_price: number | null
  shipping_fee: number | null
  is_free_shipping: boolean
  seller_id: string
  seller_nick: string
  seller_city: string
  seller_good_rate: string
  seller_item_count: number | null
  category_id: string
  category_name: string
  condition: string
  brand: string
  image_url: string
  images: string[]
  detail_url: string
  auction_deposit_url: string
  start_at: string | null
  end_at: string | null
  status: string
  item_status_str: string
  bid_count: number | null
  deposit_amount: number | null
  increment_amount: number | null
  warnings: string[]
  fetched_at: string | null
  source: string
  source_account_id: string | null
  created_at: string | null
  updated_at: string | null
  raw_json?: Record<string, unknown> | null
}

export interface AuctionStats {
  total: number
  online: number
  ended: number
  ending_24h: number
  missing_end_time: number
  warnings: number
}

export interface AuctionListData {
  items: AuctionItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface AuctionApiResponse<T> {
  success: boolean
  code?: number
  message?: string | null
  data: T
}

export interface AuctionListParams {
  status?: string
  keyword?: string
  ending_within_hours?: number
  page?: number
  page_size?: number
}

export interface AuctionDiscoverParams {
  keywords: string[]
  pages?: number
  account_id?: string
  only_active?: boolean
}

export interface AuctionDiscoverResult {
  account_id: string
  keywords: string[]
  pages: number
  scanned: number
  auction_count: number
  active_count: number
  created: number
  updated: number
  skipped: number
  errors: string[]
  duration_ms: number
}

/** 通过短链/商品链接/商品ID导入拍卖商品 */
export async function importAuction(url: string): Promise<AuctionApiResponse<AuctionItem>> {
  return post<AuctionApiResponse<AuctionItem>>(`${PREFIX}/import`, { url })
}

/** 用已登录闲鱼账号按关键词搜索拍卖并自动入库 */
export async function discoverAuction(params: AuctionDiscoverParams): Promise<AuctionApiResponse<AuctionDiscoverResult>> {
  return post<AuctionApiResponse<AuctionDiscoverResult>>(`${PREFIX}/discover`, params)
}

/** 分页查询拍卖商品 */
export async function listAuctionItems(params: AuctionListParams = {}): Promise<AuctionApiResponse<AuctionListData>> {
  return get<AuctionApiResponse<AuctionListData>>(`${PREFIX}/items`, { params })
}

/** 拍卖商品详情 */
export async function getAuctionItem(itemPk: number): Promise<AuctionApiResponse<AuctionItem>> {
  return get<AuctionApiResponse<AuctionItem>>(`${PREFIX}/items/${itemPk}`)
}

/** 刷新拍卖商品 */
export async function refreshAuctionItem(itemPk: number): Promise<AuctionApiResponse<AuctionItem>> {
  return post<AuctionApiResponse<AuctionItem>>(`${PREFIX}/items/${itemPk}/refresh`)
}

/** 软删除拍卖商品 */
export async function deleteAuctionItem(itemPk: number): Promise<AuctionApiResponse<null>> {
  return del<AuctionApiResponse<null>>(`${PREFIX}/items/${itemPk}`)
}

/** 拍卖雷达统计 */
export async function getAuctionStats(): Promise<AuctionApiResponse<AuctionStats>> {
  return get<AuctionApiResponse<AuctionStats>>(`${PREFIX}/stats`)
}
