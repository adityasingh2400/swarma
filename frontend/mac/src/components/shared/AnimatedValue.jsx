import { useEffect, useRef, useState } from 'react';
import { motion, useSpring, useTransform } from 'framer-motion';

export default function AnimatedValue({
  value = 0,
  prefix = '',
  suffix = '',
  decimals = 0,
  className = '',
  large = false,
  positive = false,
  negative = false,
}) {
  const spring = useSpring(0, { stiffness: 60, damping: 20 });
  const [display, setDisplay] = useState(format(0));

  function format(v) {
    return `${prefix}${Number(v).toFixed(decimals)}${suffix}`;
  }

  useEffect(() => {
    spring.set(value);
  }, [value, spring]);

  useEffect(() => {
    return spring.on('change', (v) => {
      setDisplay(format(v));
    });
  }, [spring, prefix, suffix, decimals]);

  const classes = [
    'animated-value',
    large && 'large',
    positive && 'positive',
    negative && 'negative',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <motion.span
      className={classes}
      initial={{ scale: 1 }}
      animate={{ scale: [1, 1.05, 1] }}
      transition={{ duration: 0.3 }}
      key={value}
    >
      {display}
    </motion.span>
  );
}
