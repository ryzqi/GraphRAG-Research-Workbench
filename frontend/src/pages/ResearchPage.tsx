/**
 * 深度研究页面
 */

import { useCallback, useEffect, useState } from 'react';
import { KnowledgeUpdateSubmit } from '../components/KnowledgeUpdateSubmit';
import type { AgentRun } from '../services/chats';
import { createExport, pollExportUntilDone } from '../services/exports';
import { type KnowledgeBase, listKnowledgeBases } from '../services/knowledgeBases';
import {
  type ResearchReport,
  createResearchRun,
  getResearchReport,
  getResearchRun,
} from '../services/research';
import { safeOpenDownloadUrl } from '../utils/urlValidation';

export function ResearchPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [run, setRun] = useState<AgentRun | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载知识库列表
  useEffect(() => {
    listKnowledgeBases()
      .then((res) => setKnowledgeBases(res.items))
      .catch((e) => setError(e.message));
  }, []);

  // 轮询研究状态
  useEffect(() => {
    if (!run || run.status !== 'running') return;

    const interval = setInterval(async () => {
      try {
        const updated = await getResearchRun(run.id);
        setRun(updated);

        if (updated.status === 'succeeded') {
          const rpt = await getResearchReport(run.id);
          setReport(rpt);
        }
      } catch (e: any) {
        setError(e.message);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [run]);

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startResearch = useCallback(async () => {
    if (selectedKbIds.length === 0 || !question.trim()) {
      setError('请选择知识库并输入研究问题');
      return;
    }

    setLoading(true);
    setError(null);
    setRun(null);
    setReport(null);

    try {
      const newRun = await createResearchRun({
        question: question.trim(),
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        mode: 'single_agent',
      });
      setRun(newRun);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds, question]);

  const handleExport = useCallback(async () => {
    if (!run) return;

    setExporting(true);
    setError(null);

    try {
      const job = await createExport({ type: 'research', run_id: run.id });
      const completed = await pollExportUntilDone(job.id);

      if (completed.status === 'succeeded' && completed.download_url) {
        if (!safeOpenDownloadUrl(completed.download_url)) {
          setError('下载链接来自不受信任的域名');
        }
      } else {
        setError(completed.error_message || '导出失败');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  }, [run]);

  const reset = useCallback(() => {
    setRun(null);
    setReport(null);
    setQuestion('');
    setError(null);
  }, []);

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>深度研究</h1>

      {!run ? (
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 16 }}>
            选择知识库范围
          </h2>

          {knowledgeBases.length === 0 ? (
            <div style={{ color: '#6b7280', padding: 16 }}>
              暂无可用知识库
            </div>
          ) : (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                marginBottom: 24,
              }}
            >
              {knowledgeBases.map((kb) => (
                <label
                  key={kb.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: 12,
                    border: '1px solid #e5e7eb',
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: selectedKbIds.includes(kb.id) ? '#eff6ff' : '#fff',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedKbIds.includes(kb.id)}
                    onChange={() => toggleKb(kb.id)}
                  />
                  <div>
                    <div style={{ fontWeight: 500 }}>{kb.name}</div>
                    {kb.description && (
                      <div style={{ fontSize: 14, color: '#6b7280' }}>
                        {kb.description}
                      </div>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}

          <div style={{ marginBottom: 24 }}>
            <label style={{ display: 'block', fontSize: 14, marginBottom: 8 }}>
              研究问题
            </label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="输入需要深度研究的问题..."
              rows={4}
              style={{
                width: '100%',
                padding: '10px 14px',
                border: '1px solid #d1d5db',
                borderRadius: 8,
                fontSize: 14,
                resize: 'vertical',
              }}
            />
          </div>

          <button
            onClick={startResearch}
            disabled={selectedKbIds.length === 0 || !question.trim() || loading}
            style={{
              padding: '10px 20px',
              background:
                selectedKbIds.length === 0 || !question.trim() || loading
                  ? '#9ca3af'
                  : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor:
                selectedKbIds.length === 0 || !question.trim() || loading
                  ? 'not-allowed'
                  : 'pointer',
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {loading ? '创建中...' : '开始研究'}
          </button>
        </div>
      ) : (
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 16,
              padding: 12,
              background: '#f3f4f6',
              borderRadius: 8,
            }}
          >
            <div>
              <div style={{ fontWeight: 500 }}>研究问题</div>
              <div style={{ fontSize: 14, color: '#6b7280' }}>{run.question}</div>
            </div>
            <button
              onClick={reset}
              style={{
                padding: '6px 12px',
                background: '#fff',
                border: '1px solid #d1d5db',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              新研究
            </button>
          </div>

          {/* 状态与阶段摘要 */}
          <div
            style={{
              marginBottom: 16,
              padding: 16,
              border: '1px solid #e5e7eb',
              borderRadius: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ fontWeight: 500 }}>状态：</span>
              <span
                style={{
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontSize: 13,
                  background:
                    run.status === 'running'
                      ? '#fef3c7'
                      : run.status === 'succeeded'
                        ? '#d1fae5'
                        : '#fee2e2',
                  color:
                    run.status === 'running'
                      ? '#92400e'
                      : run.status === 'succeeded'
                        ? '#065f46'
                        : '#991b1b',
                }}
              >
                {run.status === 'running'
                  ? '研究中...'
                  : run.status === 'succeeded'
                    ? '已完成'
                    : '失败'}
              </span>
            </div>

            {run.stage_summaries && Object.keys(run.stage_summaries).length > 0 && (
              <div>
                <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
                  阶段摘要
                </div>
                <div style={{ fontSize: 13, color: '#6b7280' }}>
                  {Object.entries(run.stage_summaries).map(([stage, summary]) => (
                    <div key={stage} style={{ marginBottom: 4 }}>
                      <span style={{ fontWeight: 500 }}>{stage}：</span>
                      {typeof summary === 'object'
                        ? JSON.stringify(summary)
                        : String(summary)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 研究报告 */}
          {report && (
            <div
              style={{
                marginBottom: 16,
                padding: 16,
                border: '1px solid #e5e7eb',
                borderRadius: 8,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 12,
                }}
              >
                <h3 style={{ fontSize: 16, fontWeight: 600 }}>研究报告</h3>
                <button
                  onClick={handleExport}
                  disabled={exporting}
                  style={{
                    padding: '6px 12px',
                    background: exporting ? '#9ca3af' : '#10b981',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 6,
                    cursor: exporting ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                  }}
                >
                  {exporting ? '导出中...' : '导出报告'}
                </button>
              </div>

              <div
                style={{
                  padding: 16,
                  background: '#fafafa',
                  borderRadius: 8,
                  whiteSpace: 'pre-wrap',
                  fontSize: 14,
                  lineHeight: 1.6,
                  maxHeight: 500,
                  overflowY: 'auto',
                }}
              >
                {report.content_md}
              </div>

              {report.citations && report.citations.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <h4 style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
                    引用 ({report.citations.length})
                  </h4>
                  <div style={{ fontSize: 13, color: '#6b7280' }}>
                    {report.citations.map((c, i) => (
                      <div key={i} style={{ marginBottom: 4 }}>
                        [{c.index || i + 1}] {(c.excerpt as string)?.slice(0, 100)}...
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 提交沉淀 */}
          {run.status === 'succeeded' && (
            <KnowledgeUpdateSubmit
              runId={run.id}
              kbIds={run.selected_kb_ids || []}
              reportContent={report?.content_md}
            />
          )}
        </div>
      )}

      {error && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 8,
            color: '#dc2626',
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
