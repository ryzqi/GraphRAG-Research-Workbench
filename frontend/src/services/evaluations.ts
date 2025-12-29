/**
 * 评测 API 封装
 */

import { apiFetch } from './http';

export type EvaluationStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';

export interface EvaluationRunCreateRequest {
  dataset: {
    questions: Array<{
      id: string;
      question: string;
      reference_answer?: string;
      scoring_criteria?: Record<string, number>;
      tags?: string[];
    }>;
  };
  config: {
    selected_kb_ids: string[];
    allow_external?: boolean;
    timeout_per_question_ms?: number;
  };
}

export interface EvaluationRun {
  id: string;
  status: EvaluationStatus;
  summary: {
    total_questions?: number;
    single_agent?: {
      avg_score: number;
      avg_latency: number;
    };
    multi_agent?: {
      avg_score: number;
      avg_latency: number;
    };
    case_results?: Array<{
      question_id: string;
      question: string;
      single_agent_run_id?: string;
      multi_agent_run_id?: string;
      single_agent_answer?: string;
      multi_agent_answer?: string;
      single_score?: number;
      multi_score?: number;
      reference_answer?: string;
    }>;
  } | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationResults {
  eval_run_id: string;
  status: EvaluationStatus;
  summary: EvaluationRun['summary'];
  case_results: NonNullable<EvaluationRun['summary']>['case_results'];
}

/**
 * 发起对比评测
 */
export async function createEvaluationRun(data: EvaluationRunCreateRequest): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>('/api/v1/evaluations/runs', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * 获取评测状态
 */
export async function getEvaluationRun(evalRunId: string): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>(`/api/v1/evaluations/runs/${evalRunId}`);
}

/**
 * 获取评测结果
 */
export async function getEvaluationResults(evalRunId: string): Promise<EvaluationResults> {
  return apiFetch<EvaluationResults>(`/api/v1/evaluations/runs/${evalRunId}/results`);
}

/**
 * 取消评测任务
 */
export async function cancelEvaluationRun(evalRunId: string): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>(`/api/v1/evaluations/runs/${evalRunId}/cancel`, {
    method: 'POST',
  });
}
