/**
 * Default routes + placeholder selectors. Override non-secret tweaks in
 * demo-flow.local.js (gitignored) — copy this file and rename.
 */
export default {
  ebay: {
    /** After login, open seller flow in browser, copy URL from address bar */
    startUrl:
      process.env.EBAY_SELL_START_URL ||
      'https://www.ebay.com/sl/sell',
    /** Playwright locators — replace with what codegen gives you */
    selectors: {
      title: 'input[name="title"], [data-testid="x-title"], #listing-title',
      price: 'input[name="price"], [data-testid="x-price"]',
      description: 'textarea[name="description"], [contenteditable="true"]',
      photoInput: 'input[type="file"]',
    },
  },
  facebook: {
    startUrl:
      process.env.FB_MARKETPLACE_CREATE_URL ||
      'https://www.facebook.com/marketplace/create/item',
    selectors: {
      title: 'input[placeholder*="Title" i], label:has-text("Title") ~ input, [aria-label*="title" i]',
      price: 'input[placeholder*="Price" i], label:has-text("Price") ~ input',
      description: 'textarea[placeholder*="Describe" i], label:has-text("Description") ~ textarea',
      photoInput: 'input[type="file"][accept*="image"]',
    },
  },
};
