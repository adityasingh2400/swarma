# ReRoute demo browser automation

Playwright flows for **eBay** and **Facebook Marketplace** listing forms. Uses **saved browser sessions** (no passwords in `.env`).

## What you need locally (do not paste into chat)

1. **eBay account** you can sign into in a browser (seller listing flow must be available for your region).
2. **Facebook account** with Marketplace access.
3. **2FA devices** if enabled — you complete them once while saving the session.
4. Optional: **one demo image** path for `DEMO_IMAGE_PATH`.

## Setup

```bash
cd demo-automation
cp .env.example .env
npm install
npx playwright install chromium
```

Save sessions (headed browser opens — you log in, then press Enter in the terminal):

```bash
npm run auth:ebay
npm run auth:facebook
```

Tune selectors after recording with:

```bash
npm run codegen:ebay
npm run codegen:facebook
```

Copy `demo-flow.config.example.js` → `demo-flow.local.js` and paste the locators you need, or override `EBAY_SELL_START_URL` / `FB_MARKETPLACE_CREATE_URL` in `.env` with the exact URLs from your browser.

## Run demo fills

```bash
npm run demo:ebay
npm run demo:facebook
```

`auth/*.json` and `.env` are gitignored — treat them like secrets.
