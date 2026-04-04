const BASE = window.location.origin || 'http://localhost:8080';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function uploadVideo(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
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
