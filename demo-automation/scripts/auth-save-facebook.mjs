import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const out = join(root, 'auth', 'facebook.json');

mkdirSync(dirname(out), { recursive: true });

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
const page = await context.newPage();

await page.goto('https://www.facebook.com', { waitUntil: 'domcontentloaded' });

console.log('\n>>> Log in to Facebook in the opened window (complete 2FA if prompted).');
console.log('>>> When fully signed in, return here and press Enter.\n');

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
await new Promise((res) => rl.once('line', res));
rl.close();

await context.storageState({ path: out });
await browser.close();

console.log(`Saved session to ${out} (keep this file secret; it is gitignored)\n`);
