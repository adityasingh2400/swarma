// @ts-check
import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config({ path: resolve(dirname(fileURLToPath(import.meta.url)), '.env') });

const __dirname = dirname(fileURLToPath(import.meta.url));
const ebayAuth = resolve(__dirname, 'auth', 'ebay.json');
const fbAuth = resolve(__dirname, 'auth', 'facebook.json');

/** @type {import('@playwright/test').PlaywrightTestConfig} */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 120_000,
  use: {
    ...devices['Desktop Chrome'],
    headless: process.env.HEADLESS === '1',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'ebay',
      use: {
        storageState: existsSync(ebayAuth) ? ebayAuth : undefined,
      },
      testMatch: /ebay-listing/,
    },
    {
      name: 'facebook',
      use: {
        storageState: existsSync(fbAuth) ? fbAuth : undefined,
      },
      testMatch: /facebook-listing/,
    },
  ],
});
