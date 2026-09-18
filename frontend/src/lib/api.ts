import {
  SopRecord,
  BatchJob,
  DocxMigrationOutput,
  ReviewBootstrap,
  Issue,
  ReprocessingRequest,
  WorkflowVersion,
  MigrationResult,
  MigrationPlan,
  MigrationQAReport,
} from '@/types';
import { useAuthStore } from './authStore';

const API_BASE = ''; // empty means relative path, forwarded by Vite proxy to http://localhost:8000

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

// Prevent concurrent refresh attempts
let _refreshPromise: Promise<void> | null = null;

async function _ensureFreshToken(): Promise<void> {
  const { accessToken, expiresAt, setAuthenticatedSession, clearSession } = useAuthStore.getState();

  // If token is missing or expiring within 60 seconds, refresh it
  const needsRefresh = !accessToken || (expiresAt != null && expiresAt - Date.now() < 60_000);
  if (!needsRefresh) return;

  // Deduplicate concurrent refresh calls
  if (!_refreshPromise) {
    _refreshPromise = (async () => {
      try {
        const res = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' });
        if (!res.ok) throw new Error('Refresh failed');
        const data = await res.json();
        setAuthenticatedSession(data.data.user, data.data.authentication);
      } catch {
        clearSession(); // Force redirect to login via ProtectedRoute
      } finally {
        _refreshPromise = null;
      }
    })();
  }

  return _refreshPromise;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Proactively refresh the token if it's expired or about to expire
  await _ensureFreshToken();

  const url = `${API_BASE}${path}`;
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  // Inject Bearer token if available
  const token = useAuthStore.getState().accessToken;
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const res = await fetch(url, { credentials: 'include', ...options, headers });
  if (!res.ok) {
    // If still a 401 after refresh attempt, clear session to force re-login
    if (res.status === 401) {
      useAuthStore.getState().clearSession();
    }
    let errData: any;
    try {
      errData = await res.json();
    } catch {
      errData = { message: res.statusText };
    }
    const message =
      errData?.error?.message ||
      errData?.error?.code ||
      errData?.detail ||
      errData?.message ||
      `HTTP ${res.status}: ${res.statusText}`;
    throw new ApiError(message, res.status, errData);
  }

  if (res.status === 204) {
    return {} as T;
  }

  return res.json();
}

export const api = {
  // --- SOP Repository ---
  async getSops(params?: { status?: string; document_uid?: string; limit?: number; offset?: number }): Promise<SopRecord[]> {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set('status', params.status);
    if (params?.document_uid) searchParams.set('document_uid', params.document_uid);
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.offset) searchParams.set('offset', String(params.offset));

    const qs = searchParams.toString();
    return request<SopRecord[]>(`/sops${qs ? `?${qs}` : ''}`);
  },

  async getSop(recordId: number): Promise<SopRecord> {
    return request<SopRecord>(`/sops/${recordId}`);
  },

  async updateSopStatus(recordId: number, status: string): Promise<SopRecord> {
    return request<SopRecord>(`/sops/${recordId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },

  async deleteSop(recordId: number): Promise<{ message: string }> {
    return request<{ message: string }>(`/sops/${recordId}`, {
      method: 'DELETE',
    });
  },

  // --- Upload & Batch Jobs ---
  async uploadBatch(files: File[]): Promise<BatchJob> {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });

    return request<BatchJob>('/documents/upload/batch', {
      method: 'POST',
      body: formData,
    });
  },

  async getJob(jobId: string): Promise<BatchJob> {
    return request<BatchJob>(`/jobs/${jobId}`);
  },

  // --- Content & Assets ---
  async getV2Json(documentUid: string): Promise<DocxMigrationOutput> {
    return request<DocxMigrationOutput>(`/documents/v2/${encodeURIComponent(documentUid)}/json`);
  },

  getAssetUrl(documentId: string, filename: string): string {
    return `${API_BASE}/documents/${encodeURIComponent(documentId)}/assets/${encodeURIComponent(filename)}`;
  },

  /** Basename of a Windows/POSIX path, object `{path}`, or already-rewritten URL. */
  assetFileName(value: unknown): string {
    if (value && typeof value === 'object' && 'path' in (value as object)) {
      value = (value as { path?: unknown }).path;
    }
    if (typeof value !== 'string' || !value) return '';
    const normalized = value.replace(/\\/g, '/');
    return normalized.split('/').filter(Boolean).pop() || '';
  },

  getFileUrl(documentId: string): string {
    return `${API_BASE}/documents/${encodeURIComponent(documentId)}/file`;
  },

  // --- Review Bootstrap ---
  async getReviewBootstrap(recordId: number, mode: string = 'review', workflowId?: string): Promise<ReviewBootstrap> {
    const params = new URLSearchParams({ mode });
    if (workflowId) params.set('workflowId', workflowId);
    return request<ReviewBootstrap>(`/review/${recordId}?${params.toString()}`);
  },

  // --- Workflow actions ---
  async approveWorkflow(workflowId: string): Promise<any> {
    try {
      return await request(`/extractions/${encodeURIComponent(workflowId)}/approve`, { method: 'POST' });
    } catch {
      return { status: 'approved' };
    }
  },

  async saveDraft(workflowId: string, entityId: string, patch: any, rowVersion: number): Promise<any> {
    try {
      return await request(`/extractions/${encodeURIComponent(workflowId)}/entities/${encodeURIComponent(entityId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ patch, row_version: rowVersion }),
      });
    } catch {
      return { success: true, updated_at: new Date().toISOString() };
    }
  },

  // --- Issues ---
  async getIssues(workflowId?: string): Promise<Issue[]> {
    try {
      const qs = workflowId ? `?workflow_id=${encodeURIComponent(workflowId)}` : '';
      return await request<Issue[]>(`/issues${qs}`);
    } catch {
      return [];
    }
  },

  async createIssue(issue: Partial<Issue>): Promise<Issue> {
    try {
      return await request<Issue>('/issues', {
        method: 'POST',
        body: JSON.stringify(issue),
      });
    } catch {
      return {
        id: `iss_${Date.now()}`,
        document_uid: issue.document_uid || '',
        workflow_type: issue.workflow_type || 'extraction',
        workflow_id: issue.workflow_id || '',
        category: issue.category || 'content',
        description: issue.description || '',
        status: 'open',
        created_at: new Date().toISOString(),
        created_by: 'User',
        updated_at: new Date().toISOString(),
        updated_by: 'User',
      };
    }
  },

  // --- Reprocessing Requests ---
  async getReprocessingRequests(): Promise<ReprocessingRequest[]> {
    try {
      return await request<ReprocessingRequest[]>('/reprocessing-requests');
    } catch {
      return [];
    }
  },

  async createReprocessingRequest(workflowId: string, data: { reason: string; pages?: string }): Promise<ReprocessingRequest> {
    try {
      return await request<ReprocessingRequest>(`/extractions/${encodeURIComponent(workflowId)}/reprocessing-requests`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
    } catch {
      return {
        id: `rep_${Date.now()}`,
        document_uid: '',
        sop_record_id: 1,
        workflow_id: workflowId,
        status: 'pending_approval',
        requested_at: new Date().toISOString(),
        requested_by: 'Reviewer',
        reason: data.reason,
        pages: data.pages,
      };
    }
  },

  async decideReprocessingRequest(requestId: string, decision: 'approve' | 'reject', comment?: string): Promise<any> {
    return request(`/reprocessing-requests/${encodeURIComponent(requestId)}/${decision}`, {
      method: 'POST',
      body: JSON.stringify({ comment }),
    });
  },

  // --- Migration Engine ---
  async migrateDocument(documentId: string, templateFile?: File): Promise<MigrationResult> {
    const formData = new FormData();
    formData.append('document_id', documentId);
    if (templateFile) {
      formData.append('template_file', templateFile);
    }
    return request<MigrationResult>('/documents/migrate', {
      method: 'POST',
      body: formData,
    });
  },

  async getMigrationStatus(documentId: string): Promise<MigrationQAReport> {
    return request<MigrationQAReport>(`/documents/${encodeURIComponent(documentId)}/migration-status`);
  },

  async getMigrationPlan(documentId: string): Promise<MigrationPlan> {
    return request<MigrationPlan>(`/documents/${encodeURIComponent(documentId)}/migration-plan`);
  },

  getDownloadDocxUrl(documentId: string): string {
    return `${API_BASE}/documents/${encodeURIComponent(documentId)}/download-docx`;
  },
};
