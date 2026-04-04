import { useId } from 'react';

export default function ReRouteLogo({ className = '', size = 28 }) {
  const raw = useId();
  const uid = raw.replace(/[^a-zA-Z0-9_-]/g, '');
  const flow = `${uid}-f`;
  const spark = `${uid}-s`;

  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      fill="none"
      role="img"
      aria-hidden="true"
      width={size}
      height={size}
    >
      <defs>
        <linearGradient id={flow} x1="88" y1="420" x2="420" y2="92" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#F5D0B0" />
          <stop offset="50%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#F5D0B0" />
        </linearGradient>
        <linearGradient id={spark} x1="256" y1="64" x2="320" y2="128" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFE4B5" />
          <stop offset="100%" stopColor="#D4A574" />
        </linearGradient>
      </defs>
      <circle cx="128" cy="392" r="14" fill={`url(#${flow})`} opacity="0.55" />
      <circle cx="256" cy="416" r="14" fill={`url(#${flow})`} opacity="0.55" />
      <circle cx="384" cy="392" r="14" fill={`url(#${flow})`} opacity="0.55" />
      <path stroke={`url(#${flow})`} strokeWidth="36" strokeLinecap="round" strokeLinejoin="round"
        d="M128 392 C128 300 168 232 248 196 M256 416 C256 312 256 248 256 196 M384 392 C384 300 344 232 264 196" />
      <circle cx="256" cy="176" r="44" fill={`url(#${flow})`} opacity="0.2" />
      <circle cx="256" cy="176" r="26" fill={`url(#${flow})`} />
      <path stroke={`url(#${flow})`} strokeWidth="34" strokeLinecap="round" strokeLinejoin="round"
        d="M256 136 L256 88 M220 124 L256 88 L292 124" />
      <path fill={`url(#${spark})`} d="M352 108l8 18 18 8-18 8-8 18-8-18-18-8 18-8 8-18z" opacity="0.95" />
    </svg>
  );
}
