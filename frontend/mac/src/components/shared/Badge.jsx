const PLATFORM_MAP = {
  ebay: 'eBay',
  depop: 'Depop',
  mercari: 'Mercari',
  poshmark: 'Poshmark',
  offerup: 'OfferUp',
  facebook: 'FB Mkt',
  amazon: 'Amazon',
  swappa: 'Swappa',
  decluttr: 'Decluttr',
  backmarket: 'Back Mkt',
};

export default function Badge({ variant = 'neutral', platform, children, className = '' }) {
  if (platform) {
    const key = platform.toLowerCase();
    return (
      <span className={`badge badge--platform ${className}`} data-platform={key}>
        {PLATFORM_MAP[key] || platform}
      </span>
    );
  }

  return (
    <span className={`badge badge--${variant} ${className}`}>
      {children}
    </span>
  );
}
