const PLATFORM_MAP = {
  ebay: 'eBay',
  depop: 'Depop',
  mercari: 'Mercari',
  poshmark: 'Poshmark',
  offerup: 'OfferUp',
  facebook: 'FB Marketplace',
  amazon: 'Amazon',
  swappa: 'Swappa',
  decluttr: 'Decluttr',
  backmarket: 'Back Market',
};

export default function Badge({ variant = 'neutral', platform, children, className = '' }) {
  if (platform) {
    const key = platform.toLowerCase();
    return (
      <span className={`badge badge-platform badge-${key} ${className}`}>
        {PLATFORM_MAP[key] || platform}
      </span>
    );
  }

  return (
    <span className={`badge badge-${variant} ${className}`}>
      {children}
    </span>
  );
}
