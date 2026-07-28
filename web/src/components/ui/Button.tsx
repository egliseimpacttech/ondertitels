import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'accent' | 'ghost' | 'danger';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: 'md' | 'sm';
  children: ReactNode;
};

const variantClass: Record<Variant, string> = {
  primary: 'btn',
  secondary: 'btn btn-secondary',
  accent: 'btn btn-accent',
  ghost: 'btn btn-ghost',
  danger: 'btn btn-danger',
};

export function Button({ variant = 'primary', size = 'md', className = '', children, ...rest }: Props) {
  const sizeClass = size === 'sm' ? 'btn-small' : '';
  return (
    <button type="button" className={`${variantClass[variant]} ${sizeClass} ${className}`.trim()} {...rest}>
      {children}
    </button>
  );
}
