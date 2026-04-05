const PLATFORM_MAP = {
  facebook: 'FB Marketplace',
  depop: 'Depop',
  amazon: 'Amazon',
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
