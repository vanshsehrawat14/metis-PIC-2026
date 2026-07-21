export function formatWait(minutes) {
  if (minutes == null) return '--';
  return `${Number(minutes).toFixed(1)} min`;
}

export function formatPercent(fraction) {
  if (fraction == null) return '--';
  return `${(fraction * 100).toFixed(1)}%`;
}

export function formatDollars(amount) {
  if (amount == null) return '--';
  if (amount >= 1000000) return `$${(amount / 1000000).toFixed(1)}M`;
  if (amount >= 1000) return `$${(amount / 1000).toFixed(1)}K`;
  return `$${Math.round(amount)}`;
}

export function formatHES(score) {
  if (score == null) return { score: '--', grade: 'Unknown' };
  const s = Number(score);
  const grade = s >= 90 ? 'Excellent' : s >= 70 ? 'Good' :
                s >= 50 ? 'Fair' : s >= 30 ? 'Poor' : 'Critical';
  return { score: s.toFixed(0), grade };
}

export function riskColor(level) {
  const colors = {
    LOW: 'var(--status-safe)',
    MODERATE: 'var(--status-safe)',
    ELEVATED: 'var(--status-warn)',
    HIGH: 'var(--status-danger)',
    CRITICAL: 'var(--status-danger)',
  };
  return colors[level] || 'var(--text-secondary)';
}

export function statusColor(type, value) {
  if (type === 'wait') {
    if (value < 10) return 'var(--status-safe)';
    if (value < 20) return 'var(--status-warn)';
    return 'var(--status-danger)';
  }
  if (type === 'hes') {
    if (value >= 70) return 'var(--status-safe)';
    if (value >= 50) return 'var(--status-warn)';
    return 'var(--status-danger)';
  }
  if (type === 'risk') {
    return riskColor(value);
  }
  if (type === 'revenue') {
    if (value < 5) return 'var(--status-safe)';
    if (value < 15) return 'var(--status-warn)';
    return 'var(--status-danger)';
  }
  return 'var(--text-secondary)';
}

export function statusLabel(type, value) {
  if (type === 'wait') {
    if (value < 10) return 'Low';
    if (value < 20) return 'Moderate';
    return 'High';
  }
  if (type === 'hes') {
    return formatHES(value).grade;
  }
  if (type === 'revenue') {
    if (value < 5) return 'Minimal';
    if (value < 15) return 'Moderate';
    return 'Significant';
  }
  return String(value);
}
