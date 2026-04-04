// @ts-check
import { test, expect } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadDemoFlow } from '../lib/load-demo-flow.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const authPath = resolve(__dirname, '..', 'auth', 'ebay.json');

test.beforeAll(() => {
  if (!existsSync(authPath)) {
    throw new Error(
      'Missing auth/ebay.json — run: npm run auth:ebay (log in, then Enter in terminal)'
    );
  }
});

test('fill eBay listing draft (demo)', async ({ page }) => {
  const flow = await loadDemoFlow();
  const title = process.env.DEMO_LISTING_TITLE || 'ReRoute demo item — please delete';
  const price = process.env.DEMO_LISTING_PRICE || '29.99';
  const description =
    process.env.DEMO_LISTING_DESCRIPTION ||
    'Automated demo listing from ReRoute. Safe to discard.';
  const imagePath = process.env.DEMO_IMAGE_PATH
    ? resolve(process.env.DEMO_IMAGE_PATH)
    : null;

  const { startUrl, selectors } = flow.ebay;
  await page.goto(startUrl, { waitUntil: 'domcontentloaded' });

  // Broad fallbacks — replace in demo-flow.local.js after `npm run codegen:ebay`
  const titleBox = page.locator(selectors.title).first();
  await titleBox.waitFor({ state: 'visible', timeout: 30_000 }).catch(() => {});
  if (await titleBox.isVisible().catch(() => false)) {
    await titleBox.fill(title);
  }

  const priceBox = page.locator(selectors.price).first();
  if (await priceBox.isVisible().catch(() => false)) {
    await priceBox.fill(price);
  }

  const descBox = page.locator(selectors.description).first();
  if (await descBox.isVisible().catch(() => false)) {
    await descBox.fill(description);
  }

  if (imagePath && existsSync(imagePath)) {
    const fileInput = page.locator(selectors.photoInput).first();
    await fileInput.setInputFiles(imagePath).catch(() => {});
  }

  // Pause so you can finish manually or record screen — set DEMO_PAUSE_MS=0 to skip
  const pauseMs = Number(process.env.DEMO_PAUSE_MS ?? '5000');
  if (pauseMs > 0) {
    await new Promise((r) => setTimeout(r, pauseMs));
  }

  await expect(page).toHaveURL(/.+/);
});
