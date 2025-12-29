/**
 * 对比评测页面
 */

import { useCallback, useEffect, useState } from 'react';
import { createExport, pollExportUntilDone } from '../services/exports';
import {
  type EvaluationRun,
  type EvaluationRunCreateRequest,
  createEvaluationRun,
  getEvaluationRun,
} from '../services/evaluations';
import { type KnowledgeBase, listKnowledgeBases } from '../services/knowledgeBases';

const DEFAULT_DATASET = {
  questions: [
    {
      id: 'q001',
      question: '什么是知识图谱？它与传统数据库有什么区别？',
      reference_answer: '知识图谱是一种用图结构表示实体及其关系的知识库。',
    },
  ],
};

export function EvaluationsPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [datasetJson, setDatasetJson] = useState(JSON.stringify(DEFAULT_DATASET, null, 2));
  const [evalRun, setEvalRun] = useState<EvaluationRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listKnowledgeBases()
      .then((res) => setKnowledgeBases(res.items))
      .catch((e) => setError(e.message));
  }, []);

  // 轮询评测状态
  useEffect(() => {
    if (!evalRun || !['queued', 'running'].includes(evalRun.status)) return;

    const interval = setInterval(async () => {
      try {
        const updated = await getEvaluationRun(evalRun.id);
        setEvalRun(updated);
      } catch (e: any) {
        setError(e.message);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [evalRun]);

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startEvaluation = useCallback(async () => {
    if (selectedKbIds.length === 0) {
      setError('请选择至少一个知识库');
      return;
    }

    let dataset;
    try {
      dataset = JSON.parse(datasetJson);
    } catch {
      setError('数据集 JSON 格式错误');
      return;
    }

    setLoading(true);
    setError(null);
    setEvalRun(null);

    try {
      const req: EvaluationRunCreateRequest = {
        dataset,
        config: {
          selected_kb_ids: selectedKbIds,
          allow_external: false,
        },
      };
      const run = await createEvaluationRun(req);
      setEvalRun(run);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds, datasetJson]);

  const handleExport = useCallback(async () => {
    if (!evalRun) return;

    setExporting(true);
    setError(null);

    try {
      const job = await createExport({ type: 'evaluation', run_id: evalRun.id });
      const completed = await pollExportUntilDone(job.id);

      if (completed.status === 'succeeded' && completed.download_url) {
        window.open(completed.download_url, '_blank');
      } else {
        setError(completed.error_message || '导出失败');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  }, [evalRun]);

  const reset = useCallback(() => {
    setEvalRun(null);
    setError(null);
  }, []);

  const summary = evalRun?.summary;

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>对比评测</h1>
      <p style={{ color: '#6b7280', marginBottom: 24 }}>
        在同一问题集下运行单智能体与多智能体协作，对比评测效果
      </p>

      {!evalRun ? (
        <div>
          {/* 知识库选择 */}
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 12 }}>选择知识库范围</h2>
            {knowledgeBases.length === 0 ? (
              <div style={{ color: '#6b7280', padding: 16 }}>暂无可用知识库</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {knowledgeBases.map((kb) => (
                  <label
                    key={kb.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '8px 12px',
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
                    <span>{kb.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* 数据集编辑 */}
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 12 }}>评测数据集 (JSON)</h2>
            <textarea
              value={datasetJson}
              onChange={(e) => setDatasetJson(e.target.value)}
              rows={12}
              style={{
                width: '100%',
                padding: 12,
                border: '1px solid #d1d5db',
                borderRadius: 8,
                fontFamily: 'monospace',
                fontSize: 13,
                resize: 'vertical',
              }}
            />
          </div>

          <button
            onClick={startEvaluation}
            disabled={selectedKbIds.length === 0 || loading}
            style={{
              padding: '10px 20px',
              background: selectedKbIds.length === 0 || loading ? '#9ca3af' : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: selectedKbIds.length === 0 || loading ? 'not-allowed' : 'pointer',
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {loading ? '创建中...' : '开始评测'}
          </button>
        </div>
      ) : (
        <div>
          {/* 状态栏 */}
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontWeight: 500 }}>状态：</span>
              <span
                style={{
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontSize: 13,
                  background:
                    evalRun.status === 'running' || evalRun.status === 'queued'
                      ? '#fef3c7'
                      : evalRun.status === 'succeeded'
                        ? '#d1fae5'
                        : '#fee2e2',
                  color:
                    evalRun.status === 'running' || evalRun.status === 'queued'
                      ? '#92400e'
                      : evalRun.status === 'succeeded'
                        ? '#065f46'
                        : '#991b1b',
                }}
              >
                {evalRun.status === 'queued'
                  ? '排队中...'
                  : evalRun.status === 'running'
                    ? '评测中...'
                    : evalRun.status === 'succeeded'
                      ? '已完成'
                      : '失败'}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {evalRun.status === 'succeeded' && (
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
                  {exporting ? '导出中...' : '导出结果'}
                </button>
              )}
              <button
                onClick={reset}
                style={{
                  padding: '6px 12px',
                  background: '#fff',
                  border: '1px solid #d1d5db',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                新评测
              </button>
            </div>
          </div>

          {/* 汇总指标 */}
          {summary && (
            <div
              style={{
                marginBottom: 16,
                padding: 16,
                border: '1px solid #e5e7eb',
                borderRadius: 8,
              }}
            >
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>对比汇总</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <div style={{ padding: 16, background: '#f0f9ff', borderRadius: 8 }}>
                  <div style={{ fontWeight: 500, marginBottom: 8 }}>单智能体</div>
                  <div style={{ fontSize: 14, color: '#6b7280' }}>
                    <div>平均得分: {summary.single_agent?.avg_score?.toFixed(1) ?? 'N/A'}</div>
                    <div>平均耗时: {summary.single_agent?.avg_latency?.toFixed(0) ?? 'N/A'}ms</div>
                  </div>
                </div>
                <div style={{ padding: 16, background: '#f0fdf4', borderRadius: 8 }}>
                  <div style={{ fontWeight: 500, marginBottom: 8 }}>多智能体协作</div>
                  <div style={{ fontSize: 14, color: '#6b7280' }}>
                    <div>平均得分: {summary.multi_agent?.avg_score?.toFixed(1) ?? 'N/A'}</div>
                    <div>平均耗时: {summary.multi_agent?.avg_latency?.toFixed(0) ?? 'N/A'}ms</div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 题目明细 */}
          {summary?.case_results && summary.case_results.length > 0 && (
            <div
              style={{
                padding: 16,
                border: '1px solid #e5e7eb',
                borderRadius: 8,
              }}
            >
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>题目明细</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {summary.case_results.map((c, i) => (
                  <div
                    key={c.question_id}
                    style={{
                      padding: 12,
                      background: '#fafafa',
                      borderRadius: 8,
                      border: '1px solid #e5e7eb',
                    }}
                  >
                    <div style={{ fontWeight: 500, marginBottom: 8 }}>
                      {i + 1}. {c.question}
                    </div>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: 12,
                        fontSize: 13,
                      }}
                    >
                      <div>
                        <div style={{ color: '#3b82f6', fontWeight: 500 }}>
                          单智能体 (得分: {c.single_score?.toFixed(1) ?? 'N/A'})
                        </div>
                        <div style={{ color: '#6b7280', marginTop: 4 }}>
                          {c.single_agent_answer || '无回答'}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: '#10b981', fontWeight: 500 }}>
                          多智能体 (得分: {c.multi_score?.toFixed(1) ?? 'N/A'})
                        </div>
                        <div style={{ color: '#6b7280', marginTop: 4 }}>
                          {c.multi_agent_answer || '无回答'}
                        </div>
                      </div>
                    </div>
                    {c.reference_answer && (
                      <div style={{ marginTop: 8, fontSize: 12, color: '#9ca3af' }}>
                        参考答案: {c.reference_answer}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
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

export default EvaluationsPage;
