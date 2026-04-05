import { swarmaFe } from './debugLog';

const BASE = window.location.origin || 'http://localhost:8080';

async function request(path, options = {}) {
  const method = options.method || 'GET';
  swarmaFe('api', 'fetch_start', { path, method, base: BASE });
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    swarmaFe('api', 'fetch_error', { path, method, status: res.status, statusText: res.statusText });
    throw new Error(`${res.status} ${res.statusText}`);
  }
  swarmaFe('api', 'fetch_ok', { path, method, status: res.status });
  return res.json();
}

export async function uploadVideo(file) {
  swarmaFe('api', 'upload_multipart_start', {
    url: `${BASE}/api/upload`,
    fileName: file?.name,
    size: file?.size,
    mime: file?.type,
  });
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    swarmaFe('api', 'upload_multipart_error', { status: res.status, statusText: res.statusText });
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const json = await res.json();
  swarmaFe('api', 'upload_multipart_ok', { job_id: json.job_id, status: json.status });
  return json;
}

export async function getJobs() {
  return request('/api/jobs');
}

export async function getJob(id) {
  return request(`/api/jobs/${id}`);
}

export async function getJobState(id) {
  return request(`/api/jobs/${id}`);
}

export async function executeItem(jobId, itemId, platforms) {
  return request(`/api/jobs/${jobId}/items/${itemId}/execute`, {
    method: 'POST',
    body: JSON.stringify({ platforms }),
  });
}

export async function sendReply(jobId, threadId, text) {
  return request(`/api/jobs/${jobId}/inbox/${threadId}/reply`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}
