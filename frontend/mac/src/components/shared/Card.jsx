import { motion } from 'framer-motion';

export default function Card({
  children,
  className = '',
  glow = false,
  onClick,
  animate = true,
  ...props
}) {
  const Component = animate ? motion.div : 'div';
  const motionProps = animate
    ? {
        initial: { opacity: 0, y: 12 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -8 },
        transition: { duration: 0.3, ease: 'easeOut' },
      }
    : {};

  return (
    <Component
      className={`glass-card ${glow ? 'glow' : ''} ${className}`}
      onClick={onClick}
      {...motionProps}
      {...props}
    >
      {children}
    </Component>
  );
}
