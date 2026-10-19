/**
 * 闲鱼拍卖雷达
 *
 * 功能：
 * 1. 粘贴闲鱼短链/商品链接/商品ID导入拍卖商品
 * 2. 列表查看当前价、起拍价、运费、卖家、类目、结束时间
 * 3. 详情查看图片、描述、数据缺口提示，并跳转闲鱼 App/网页人工查看
 * 4. 支持刷新、软删除和基础统计
 *
 * 说明：当前版本只做“雷达”，出价仍在闲鱼 App 人工完成。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  Clock,
  ExternalLink,
  Eye,
  Package,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import {
  deleteAuctionItem,
  getAuctionItem,
  getAuctionStats,
  importAuction,
  listAuctionItems,
  refreshAuctionItem,
} from '@/api/auction'
import type { AuctionItem, AuctionStats } from '@/api/auction'
import { useUIStore } from '@/store/uiStore'

const PAGE_SIZE = 20

type StatusFilter = '' | 'online' | 'ended'

const statusLabels: Record<string, string> = {
  online: '进行中',
  ended: '已结束',
  unknown: '未知',
}

const statusClasses: Record<string, string> = {
  online: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  ended: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
  unknown: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  return value.replace('T', ' ').slice(0, 16)
}

function formatMoney(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toFixed(2)}`
}

function formatRelativeEnd(value: string | null): string {
  if (!value) return '—'
  const target = new Date(value.replace(' ', 'T')).getTime()
  if (Number.isNaN(target)) return formatTime(value)
  const diff = target - Date.now()
  if (diff <= 0) return '已结束'
  const hours = Math.floor(diff / 3600000)
  const minutes = Math.floor((diff % 3600000) / 60000)
  if (hours >= 24) return `${Math.floor(hours / 24)}天${hours % 24}小时`
  if (hours > 0) return `${hours}小时${minutes}分`
  return `${minutes}分钟`
}

interface StatCardProps {
  icon: typeof Package
  label: string
  value: number
  color: string
}

function StatCard({ icon: Icon, label, value, color }: StatCardProps) {
  return (
    <div className="flex items-center gap-3 p-3 sm:p-4 rounded-xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm">
      <div className={`w-11 h-11 flex items-center justify-center rounded-full shrink-0 ${color}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xl font-bold text-slate-800 dark:text-slate-100">{value}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{label}</p>
      </div>
    </div>
  )
}

export function AuctionRadar() {
  const { addToast } = useUIStore()
  const [items, setItems] = useState<AuctionItem[]>([])
  const [stats, setStats] = useState<AuctionStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importUrl, setImportUrl] = useState('')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [endingHours, setEndingHours] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [detail, setDetail] = useState<AuctionItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [refreshingId, setRefreshingId] = useState<number | null>(null)

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [listResult, statsResult] = await Promise.all([
        listAuctionItems({
          status: statusFilter || undefined,
          keyword: keyword.trim() || undefined,
          ending_within_hours: endingHours ? Number(endingHours) : undefined,
          page,
          page_size: PAGE_SIZE,
        }),
        getAuctionStats(),
      ])
      if (!listResult.success || !listResult.data) {
        throw new Error(listResult.message || '加载拍卖列表失败')
      }
      setItems(listResult.data.items || [])
      setTotal(listResult.data.total || 0)
      if (statsResult.success && statsResult.data) {
        setStats(statsResult.data)
      }
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '加载拍卖列表失败' })
    } finally {
      setLoading(false)
    }
  }, [addToast, endingHours, keyword, page, statusFilter])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleSearch = () => {
    setPage(1)
    setKeyword(keywordInput.trim())
  }

  const handleReset = () => {
    setKeywordInput('')
    setKeyword('')
    setStatusFilter('')
    setEndingHours('')
    setPage(1)
  }

  const handleImport = async () => {
    const value = importUrl.trim()
    if (!value) {
      addToast({ type: 'warning', message: '请先粘贴闲鱼链接或商品ID' })
      return
    }
    setImporting(true)
    try {
      const result = await importAuction(value)
      if (!result.success || !result.data) {
        throw new Error(result.message || '导入失败')
      }
      addToast({ type: 'success', message: `已导入：${result.data.title || result.data.item_id}` })
      setImportUrl('')
      if (page === 1) {
        await loadData()
      } else {
        setPage(1)
      }
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '导入失败' })
    } finally {
      setImporting(false)
    }
  }

  const openDetail = async (itemPk: number) => {
    setDetailLoading(true)
    try {
      const result = await getAuctionItem(itemPk)
      if (!result.success || !result.data) {
        throw new Error(result.message || '加载详情失败')
      }
      setDetail(result.data)
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '加载详情失败' })
    } finally {
      setDetailLoading(false)
    }
  }

  const handleRefresh = async (itemPk: number) => {
    setRefreshingId(itemPk)
    try {
      const result = await refreshAuctionItem(itemPk)
      if (!result.success || !result.data) {
        throw new Error(result.message || '刷新失败')
      }
      addToast({ type: 'success', message: '已刷新' })
      if (detail?.id === itemPk) {
        setDetail(result.data)
      }
      await loadData()
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '刷新失败' })
    } finally {
      setRefreshingId(null)
    }
  }

  const handleDelete = async (itemPk: number) => {
    if (!window.confirm('确定从雷达中删除这条拍卖记录吗？')) return
    try {
      const result = await deleteAuctionItem(itemPk)
      if (!result.success) {
        throw new Error(result.message || '删除失败')
      }
      addToast({ type: 'success', message: '已删除' })
      if (detail?.id === itemPk) setDetail(null)
      await loadData()
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '删除失败' })
    }
  }

  return (
    <div className="space-y-4">
      <div className="page-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">拍卖雷达</h1>
          <p className="page-description">
            导入闲鱼拍卖链接，集中查看当前价、卖家、成色和结束时间；出价仍在闲鱼 App 人工完成。
          </p>
        </div>
        <button className="btn-ios-secondary" onClick={() => void loadData()} disabled={loading}>
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">导入拍卖</h2>
        </div>
        <div className="vben-card-body space-y-2">
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              className="input-ios flex-1"
              placeholder="粘贴闲鱼短链、商品链接或商品ID，例如 https://m.tb.cn/h.xxx?tk=... 或 1091907814736"
              value={importUrl}
              onChange={(event) => setImportUrl(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleImport()
              }}
            />
            <button className="btn-ios-primary whitespace-nowrap" onClick={() => void handleImport()} disabled={importing}>
              <Plus className="w-4 h-4" />
              {importing ? '解析中…' : '导入'}
            </button>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            公开详情能拿到标题、当前价、起拍价、卖家、成色、图片；出价次数/保证金/加价幅度需到闲鱼 App 查看。
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard icon={Package} label="雷达商品" value={stats?.total ?? 0} color="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400" />
        <StatCard icon={Clock} label="进行中" value={stats?.online ?? 0} color="bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400" />
        <StatCard icon={Clock} label="24小时内结束" value={stats?.ending_24h ?? 0} color="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400" />
        <StatCard icon={AlertTriangle} label="缺少结束时间" value={stats?.missing_end_time ?? 0} color="bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400" />
      </div>

      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">筛选</h2>
        </div>
        <div className="vben-card-body">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            <select
              className="input-ios"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as StatusFilter)
                setPage(1)
              }}
            >
              <option value="">全部状态</option>
              <option value="online">进行中</option>
              <option value="ended">已结束</option>
            </select>
            <select
              className="input-ios"
              value={endingHours}
              onChange={(event) => {
                setEndingHours(event.target.value)
                setPage(1)
              }}
            >
              <option value="">结束时间不限</option>
              <option value="1">1小时内结束</option>
              <option value="6">6小时内结束</option>
              <option value="24">24小时内结束</option>
            </select>
            <input
              className="input-ios lg:col-span-2"
              placeholder="标题/卖家/类目/品牌"
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') handleSearch()
              }}
            />
            <div className="flex gap-2">
              <button className="btn-ios-primary flex-1" onClick={handleSearch}>
                <Search className="w-4 h-4" />
                查询
              </button>
              <button className="btn-ios-secondary" onClick={handleReset}>
                重置
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="vben-card overflow-hidden">
        <div className="vben-card-header flex items-center justify-between">
          <h2 className="vben-card-title">拍卖列表</h2>
          <span className="text-xs text-slate-400">共 {total} 条</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 dark:text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium min-w-[260px]">商品</th>
                <th className="text-left px-3 py-2 font-medium whitespace-nowrap">当前价</th>
                <th className="text-left px-3 py-2 font-medium whitespace-nowrap">起拍/运费</th>
                <th className="text-left px-3 py-2 font-medium min-w-[160px]">卖家</th>
                <th className="text-left px-3 py-2 font-medium whitespace-nowrap">类目/成色</th>
                <th className="text-left px-3 py-2 font-medium whitespace-nowrap">结束时间</th>
                <th className="text-left px-3 py-2 font-medium whitespace-nowrap">状态</th>
                <th className="text-right px-3 py-2 font-medium whitespace-nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-t border-slate-100 dark:border-slate-700/60">
                  <td className="px-3 py-2">
                    <div className="flex items-start gap-2">
                      {item.image_url ? (
                        <img
                          src={item.image_url}
                          alt=""
                          className="w-12 h-12 rounded object-cover shrink-0 bg-slate-100"
                          referrerPolicy="no-referrer"
                        />
                      ) : (
                        <div className="w-12 h-12 rounded bg-slate-100 dark:bg-slate-700 shrink-0" />
                      )}
                      <div className="min-w-0">
                        <a
                          href={item.detail_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-slate-800 dark:text-slate-100 hover:text-blue-600 line-clamp-2"
                          title={item.title}
                        >
                          {item.title || item.item_id}
                        </a>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-slate-400">
                          <span>{item.item_id}</span>
                          {item.brand && <span>· {item.brand}</span>}
                          {item.warnings.length > 0 && (
                            <span className="text-amber-600" title={item.warnings.join('；')}>
                              · ⚠ {item.warnings.length}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap font-semibold text-rose-600 dark:text-rose-400">
                    {formatMoney(item.current_price)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-slate-600 dark:text-slate-300">
                    <div>{formatMoney(item.start_price)}</div>
                    <div className="text-[11px] text-slate-400">
                      {item.is_free_shipping ? '包邮' : formatMoney(item.shipping_fee)}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="text-slate-700 dark:text-slate-200 truncate max-w-[180px]">{item.seller_nick || '—'}</div>
                    <div className="text-[11px] text-slate-400">
                      {item.seller_city || '—'} · 好评 {item.seller_good_rate || '—'}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="text-slate-700 dark:text-slate-200">{item.category_name || '—'}</div>
                    <div className="text-[11px] text-slate-400">{item.condition || '—'}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="text-slate-700 dark:text-slate-200">{formatTime(item.end_at)}</div>
                    <div className="text-[11px] text-slate-400">{formatRelativeEnd(item.end_at)}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span className={`inline-flex px-2 py-0.5 rounded text-xs ${statusClasses[item.status] || statusClasses.unknown}`}>
                      {statusLabels[item.status] || item.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className="btn-ios-ghost px-2 py-1 text-xs"
                        onClick={() => void openDetail(item.id)}
                        disabled={detailLoading}
                        title="详情"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        className="btn-ios-ghost px-2 py-1 text-xs"
                        onClick={() => void handleRefresh(item.id)}
                        disabled={refreshingId === item.id}
                        title="刷新"
                      >
                        <RefreshCw className={`w-4 h-4 ${refreshingId === item.id ? 'animate-spin' : ''}`} />
                      </button>
                      <a
                        className="btn-ios-ghost px-2 py-1 text-xs"
                        href={item.detail_url}
                        target="_blank"
                        rel="noreferrer"
                        title="打开闲鱼"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                      <button
                        className="btn-ios-ghost px-2 py-1 text-xs text-rose-600"
                        onClick={() => void handleDelete(item.id)}
                        title="删除"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-slate-400">
                    暂无拍卖商品，先粘贴一条闲鱼链接导入
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-slate-400">
                    加载中…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 dark:border-slate-700/60">
          <span className="text-xs text-slate-400">
            第 {page} / {totalPages} 页
          </span>
          <div className="flex gap-2">
            <button
              className="btn-ios-secondary px-3 py-1 text-xs"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1 || loading}
            >
              上一页
            </button>
            <button
              className="btn-ios-secondary px-3 py-1 text-xs"
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              disabled={page >= totalPages || loading}
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDetail(null)}>
          <div
            className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-4xl max-h-[90vh] overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 p-4 border-b border-slate-100 dark:border-slate-700">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">{detail.title || detail.item_id}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span>商品ID {detail.item_id}</span>
                  <span>拍卖ID {detail.auction_id || '—'}</span>
                  <span className={`inline-flex px-2 py-0.5 rounded ${statusClasses[detail.status] || statusClasses.unknown}`}>
                    {statusLabels[detail.status] || detail.status}
                  </span>
                </div>
              </div>
              <button className="btn-ios-ghost p-1" onClick={() => setDetail(null)}>
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                <div>
                  <p className="text-xs text-slate-400">当前价</p>
                  <p className="font-semibold text-rose-600">{formatMoney(detail.current_price)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">起拍价</p>
                  <p className="font-medium">{formatMoney(detail.start_price)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">运费</p>
                  <p className="font-medium">{detail.is_free_shipping ? '包邮' : formatMoney(detail.shipping_fee)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">出价次数</p>
                  <p className="font-medium">{detail.bid_count ?? '需在 App 查看'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">开始时间</p>
                  <p className="font-medium">{formatTime(detail.start_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">结束时间</p>
                  <p className="font-medium">{formatTime(detail.end_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">保证金</p>
                  <p className="font-medium">{formatMoney(detail.deposit_amount)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">加价幅度</p>
                  <p className="font-medium">{formatMoney(detail.increment_amount)}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-slate-400">卖家</p>
                  <p className="font-medium">
                    {detail.seller_nick || '—'} · {detail.seller_city || '—'} · 好评 {detail.seller_good_rate || '—'}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">类目 / 成色 / 品牌</p>
                  <p className="font-medium">
                    {detail.category_name || '—'} / {detail.condition || '—'} / {detail.brand || '—'}
                  </p>
                </div>
              </div>

              {detail.warnings.length > 0 && (
                <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-700 dark:text-amber-300">
                  <div className="flex items-center gap-1 font-medium">
                    <AlertTriangle className="w-4 h-4" />
                    数据缺口
                  </div>
                  <ul className="mt-1 list-disc list-inside space-y-0.5 text-xs">
                    {detail.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.images.length > 0 && (
                <div>
                  <p className="text-xs text-slate-400 mb-2">商品图片</p>
                  <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                    {detail.images.slice(0, 10).map((image) => (
                      <a key={image} href={image} target="_blank" rel="noreferrer">
                        <img
                          src={image}
                          alt=""
                          className="w-full aspect-square object-cover rounded border border-slate-100 dark:border-slate-700"
                          referrerPolicy="no-referrer"
                        />
                      </a>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs text-slate-400 mb-1">商品描述</p>
                <p className="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {detail.description || '—'}
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <a className="btn-ios-primary" href={detail.detail_url} target="_blank" rel="noreferrer">
                  <ExternalLink className="w-4 h-4" />
                  打开闲鱼详情
                </a>
                {detail.auction_deposit_url && (
                  <a className="btn-ios-secondary" href={detail.auction_deposit_url} target="_blank" rel="noreferrer">
                    保证金页
                  </a>
                )}
                <button className="btn-ios-secondary" onClick={() => void handleRefresh(detail.id)} disabled={refreshingId === detail.id}>
                  <RefreshCw className={`w-4 h-4 ${refreshingId === detail.id ? 'animate-spin' : ''}`} />
                  刷新
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AuctionRadar
