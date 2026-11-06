'use client';

import { useId } from 'react';
import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

const FIELD_BASE =
  'w-full rounded-[var(--radius-sm)] border border-border bg-code-bg px-3 py-2 text-sm text-text ' +
  'placeholder:text-text-dim transition-colors hover:border-border-strong ' +
  'focus:border-accent focus:outline-none disabled:opacity-60';

export interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
  aside?: React.ReactNode;
}

export function Field({ label, hint, error, required, htmlFor, children, className, aside }: FieldProps) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-medium text-text-muted">
          {label}
          {required ? <span className="ml-1 text-danger">*</span> : null}
        </label>
        {aside}
      </div>
      {children}
      {error ? (
        <p role="alert" className="text-[11px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[11px] text-text-dim">{hint}</p>
      ) : null}
    </div>
  );
}

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  /** React 19 passes `ref` as a normal prop — forwarded to the <input>. */
  ref?: React.Ref<HTMLInputElement>;
}

export function TextInput({ className, invalid, ref, ...rest }: TextInputProps) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(FIELD_BASE, invalid && 'border-danger focus:border-danger', className)}
      {...rest}
    />
  );
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(FIELD_BASE, 'min-h-24 resize-y', className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(FIELD_BASE, 'pr-8', className)} {...rest}>
      {children}
    </select>
  );
}

/** Small labelled key/value hint used inside setup / settings panels. */
export function InlineNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-[var(--radius-sm)] border border-border bg-surface-2/60 px-3 py-2 text-xs text-text-muted">
      {children}
    </p>
  );
}

/** Reusable unique-id helper for forms that appear more than once on a page. */
export function useFieldId(prefix: string): string {
  const id = useId();
  return `${prefix}-${id.replace(/[:]/g, '')}`;
}
