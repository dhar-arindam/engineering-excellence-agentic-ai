import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function getScoreColor(score: number): string {
  if (score >= 80) return 'text-emerald-500';
  if (score >= 60) return 'text-amber-500';
  return 'text-red-500';
}

export function getRiskVariant(risk: string): 'low' | 'medium' | 'high' {
  switch (risk) {
    case 'Low': return 'low';
    case 'Medium': return 'medium';
    case 'High': return 'high';
    default: return 'medium';
  }
}

export function getSeverityOrder(severity: string): number {
  const order: Record<string, number> = {
    Critical: 0, High: 1, Medium: 2, Low: 3, Info: 4,
  };
  return order[severity] ?? 99;
}
