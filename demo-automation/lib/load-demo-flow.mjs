import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import example from '../demo-flow.config.example.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

function deepMerge(a, b) {
  if (!b) return structuredClone(a);
  const out = { ...a };
  for (const k of Object.keys(b)) {
    const av = a[k];
    const bv = b[k];
    if (
      bv &&
      typeof bv === 'object' &&
      !Array.isArray(bv) &&
      av &&
      typeof av === 'object' &&
      !Array.isArray(av)
    ) {
      out[k] = deepMerge(av, bv);
    } else {
      out[k] = bv;
    }
  }
  return out;
}

/** @returns {Promise<typeof example>} */
export async function loadDemoFlow() {
  const localPath = join(__dirname, '..', 'demo-flow.local.js');
  if (!existsSync(localPath)) {
    return example;
  }
  const local = await import(pathToFileURL(localPath).href);
  return deepMerge(example, local.default);
}
