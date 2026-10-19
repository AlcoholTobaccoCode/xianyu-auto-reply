import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ExternalLink, RefreshCw, Search, X } from 'lucide-react'
import { getAuctionReferencePrices } from '@/api/auction'
import type { AuctionItem, AuctionReferenceData } from '@/api/auction'

interface ReferencePriceModalProps {
  item: AuctionItem | null
  onClose: () => void
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toFixed(2)}`
}

export function ReferencePriceModal({ item, onClose }: ReferencePriceModalProps) {
  const [data, setData] = useState<AuctionReferenceData | null>(null)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(
    async (refresh = false, query?: string) => {
      if (!item) return
      setLoading(true)
      setError('')
      try {
        const result = await getAuctionReferencePrices(item.id, {
          keyword: query?.trim() || undefined,
          refresh,
        })
        if (!result.success || !result.data) {
          throw new Error(result.message || '参考价查询失败')
        }
        setData(result.data)
        setKeyword(result.data.keyword)
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '参考价查询失败')
      } finally {
        setLoading(false)
      }
    },
    [item],
  )

  useEffect(() => {
    setData(null)
    setKeyword('')
    setError('')
    if (item) {
      void load(false)
    }
  }, [item, load])

  if (!item) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        className="w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-xl bg-white dark:bg-slate-800 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 p-4 border-b border-slate-100 dark:border-slate-700">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">同款在售参考价</h3>
            <p className="mt-1 text-xs text-slate-400 line-clamp-2">{item.title || item.item_id}</p>
            <p className="mt-1 text-[11px] text-slate-400">
              只展示普通在售商品，不写入拍卖雷达；价格受成色/版本/配件影响，仅供人工参考。
            </p>
          </div>
          <button className="btn-ios-ghost p-1" onClick={onClose}>
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              className="input-ios flex-1"
              placeholder="搜索词，例如：TAITO 初音未来 miku 新四季"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void load(false, keyword)
              }}
            />
            <button className="btn-ios-primary whitespace-nowrap" onClick={() => void load(false, keyword)} disabled={loading}>
              <Search className="w-4 h-4" />
              搜索
            </button>
            <button className="btn-ios-secondary whitespace-nowrap" onClick={() => void load(true, keyword)} disabled={loading}>
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-rose-50 dark:bg-rose-900/20 p-3 text-sm text-rose-700 dark:text-rose-300">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {data && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <div className="rounded-lg border border-slate-100 dark:border-slate-700 p-3">
                  <p className="text-[11px] text-slate-400">样本数</p>
                  <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{data.stats.count}</p>
                </div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-700 p-3">
                  <p className="text-[11px] text-slate-400">最低在售价</p>
                  <p className="text-lg font-semibold text-emerald-600">{money(data.stats.min)}</p>
                </div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-700 p-3">
                  <p className="text-[11px] text-slate-400">中位数</p>
                  <p className="text-lg font-semibold text-blue-600">{money(data.stats.median)}</p>
                </div>
                <div className="rounded-lg border border-slate-100 dark:border-slate-700 p-3">
                  <p className="text-[11px] text-slate-400">平均价</p>
                  <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{money(data.stats.avg)}</p>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
                <span className="truncate max-w-full">搜索词：{data.keyword}</span>
                <span>
                  {data.cached ? '30 分钟缓存' : '实时查询'} · 扫描 {data.scanned} 条 · 排除拍卖 {data.auction_skipped} 条
                </span>
              </div>

              {data.items.length === 0 ? (
                <div className="py-10 text-center text-sm text-slate-400">
                  未找到同款普通在售商品，试试修改搜索词，或稍后再试
                </div>
              ) : (
                <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-slate-100 dark:border-slate-700">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 dark:text-slate-400 sticky top-0">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium min-w-[260px]">商品</th>
                        <th className="text-left px-3 py-2 font-medium whitespace-nowrap">在售价</th>
                        <th className="text-left px-3 py-2 font-medium min-w-[130px]">卖家</th>
                        <th className="text-right px-3 py-2 font-medium whitespace-nowrap">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.items.map((row) => (
                        <tr key={row.item_id} className="border-t border-slate-100 dark:border-slate-700/60">
                          <td className="px-3 py-2">
                            <div className="flex items-start gap-2">
                              {row.pic_url ? (
                                <img
                                  src={row.pic_url}
                                  alt=""
                                  className="w-10 h-10 rounded object-cover shrink-0 bg-slate-100"
                                  referrerPolicy="no-referrer"
                                />
                              ) : (
                                <div className="w-10 h-10 rounded bg-slate-100 dark:bg-slate-700 shrink-0" />
                              )}
                              <div className="min-w-0">
                                <a
                                  href={row.detail_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-slate-800 dark:text-slate-100 hover:text-blue-600 line-clamp-2"
                                  title={row.title}
                                >
                                  {row.title || row.item_id}
                                </a>
                                <div className="mt-0.5 text-[11px] text-slate-400">
                                  {row.item_id}
                                  {row.tags ? ` · ${row.tags.slice(0, 40)}` : ''}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-2 whitespace-nowrap font-semibold text-rose-600 dark:text-rose-400">
                            {money(row.price)}
                          </td>
                          <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                            <div className="truncate max-w-[130px]">{row.seller_nick || '—'}</div>
                            <div className="text-[11px] text-slate-400">{row.area || '—'}</div>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <a
                              className="btn-ios-ghost px-2 py-1 text-xs inline-flex"
                              href={row.detail_url}
                              target="_blank"
                              rel="noreferrer"
                              title="打开闲鱼"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {loading && !data && (
            <div className="py-10 text-center text-sm text-slate-400">正在搜索同款在售商品…</div>
          )}

          <p className="text-[11px] text-slate-400">
            查询结果缓存 30 分钟，避免频繁请求闲鱼；这里展示的是普通在售商品，不是拍卖。
          </p>
        </div>
      </div>
    </div>
  )
}
