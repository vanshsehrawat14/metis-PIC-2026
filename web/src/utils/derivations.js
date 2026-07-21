/**
 * derivations.js — Maps metric keys to derivation chain data
 * extracted from real simulation results for the DerivationDrawer.
 *
 * Each function takes the full simResults object and returns
 * structured data the drawer renders. No hardcoded example numbers.
 */

export function getWaitDerivation(results) {
  if (!results) return null;
  const op = results.metrics?.operational || {};
  const wait = op.wait_time || {};
  const params = results.parameters || {};
  const nodeMetrics = results.simulation?.node_metrics || {};

  // Find the bottleneck node for service rate info
  const topNodes = Object.entries(nodeMetrics)
    .sort((a, b) => (b[1].util_mean || 0) - (a[1].util_mean || 0));
  const [bottleneckId, bottleneckData] = topNodes[0] || [];

  const attendance = params.attendance || 0;
  const arrivalWindow = params.arrival_window_hours || 3;
  const arrivalRate = arrivalWindow > 0 ? attendance / arrivalWindow : 0;

  // Estimate servers and utilization from bottleneck
  const utilMean = bottleneckData?.util_mean || op.utilization?.mean || 0;

  return {
    title: 'Wait Time',
    value: wait.mean,
    unit: 'min',
    formula: 'E[W] = (C²ₐ + C²ₛ) / 2 × E[W]_{M/M/s} × ρ / (1-ρ)',
    formulaName: 'Allen-Cunneen G/G/s approximation',
    inputs: [
      { label: 'Arrival rate λ', value: `${Math.round(arrivalRate).toLocaleString()} pph`, note: `${attendance.toLocaleString()} attendance / ${arrivalWindow}h window` },
      { label: 'Utilization ρ', value: `${(utilMean * 100).toFixed(1)}%`, note: bottleneckId ? `Bottleneck: ${bottleneckId.replace(/_/g, ' ')}` : null },
      { label: 'Weather factor', value: (params.weather_factor ?? 0.3).toFixed(2), note: 'Service rate degradation multiplier' },
      { label: 'Transit factor', value: (params.transit_factor ?? 0.5).toFixed(2), note: 'Arrival distribution modifier' },
    ],
    distribution: {
      p10: wait.p10,
      mean: wait.mean,
      p90: wait.p90,
    },
    source: 'Allen-Cunneen G/G/s approximation · Erlang-C in log-space · 1,000 MC trials',
  };
}

export function getHESDerivation(results) {
  if (!results) return null;
  const exp = results.metrics?.experience || {};
  const hes = exp.hes;
  if (hes == null) return null;

  // HES factor weights (from metrics.py EnhancedHES)
  const factors = [
    { name: 'Wait penalty', weight: 0.35, value: exp.wait_factor, color: 'var(--status-warn)' },
    { name: 'Density penalty', weight: 0.25, value: exp.density_factor, color: 'var(--status-danger)' },
    { name: 'Temperature penalty', weight: 0.15, value: exp.temperature_factor, color: '#f97316' },
    { name: 'Service penalty', weight: 0.15, value: exp.service_factor, color: 'var(--accent)' },
    { name: 'Access penalty', weight: 0.10, value: exp.access_factor, color: 'var(--status-safe)' },
  ];

  const grade = hes >= 90 ? 'Excellent' : hes >= 70 ? 'Good' : hes >= 50 ? 'Fair' : hes >= 30 ? 'Poor' : 'Critical';

  const gradeScale = [
    { label: 'A', range: '90-100', name: 'Excellent', min: 90 },
    { label: 'B', range: '70-89', name: 'Good', min: 70 },
    { label: 'C', range: '50-69', name: 'Fair', min: 50 },
    { label: 'D', range: '30-49', name: 'Poor', min: 30 },
    { label: 'F', range: '0-29', name: 'Critical', min: 0 },
  ];

  return {
    title: 'Human Experience Score',
    value: hes,
    unit: '/ 100',
    formula: 'HES = 100 × Π(wᵢ × fᵢ + (1 − wᵢ))',
    formulaName: 'Multiplicative degradation model',
    factors,
    grade,
    gradeScale,
    source: 'EnhancedHES multiplicative model · 5 weighted factors',
  };
}

export function getSafetyDerivation(results) {
  if (!results) return null;
  const safety = results.metrics?.safety || {};
  if (safety.srs == null) return null;

  const subScores = [
    {
      name: 'Crush Risk',
      value: safety.crush_risk,
      weight: 0.4,
      description: 'Sigmoid function centered at 1.5 persons/m²',
      threshold: 'Below 1.0 p/m² = safe. Above 2.17 p/m² = LOS F danger.',
    },
    {
      name: 'Flow Capacity',
      value: safety.flow_risk,
      weight: 0.3,
      description: 'Ratio of demand to exit capacity',
      threshold: 'Flow ratio > 0.85 = elevated risk.',
    },
    {
      name: 'Evacuation Time',
      value: safety.evac_risk,
      weight: 0.3,
      description: 'Estimated evacuation time vs 30-min planning target',
      threshold: 'NFPA 101 reference: 8 min (system sizing). Planning target: 30 min.',
    },
  ];

  return {
    title: 'Safety Risk Score',
    value: safety.srs,
    unit: 'SRS',
    formula: 'SRS = w₁×crush + w₂×flow + w₃×evac',
    formulaName: 'Weighted composite safety score',
    riskLevel: safety.risk_level || 'LOW',
    subScores,
    evacuationTime: safety.estimated_evacuation_min,
    nfpaTarget: 8,
    planningTarget: 30,
    source: 'Crush sigmoid (1.5 p/m²) · Flow capacity ratio · 30-min evac target',
  };
}

export function getRevenueDerivation(results) {
  if (!results) return null;
  const rev = results.metrics?.revenue || {};
  const totalLoss = rev.total_current_event_loss || 0;
  if (totalLoss <= 0) return null;

  const params = results.parameters || {};
  const attendance = params.attendance || 0;
  const waitMean = results.metrics?.operational?.wait_time?.mean || 0;

  const perHeadSpend = attendance > 0 ? (rev.baseline_concession || 0) / attendance : 0;
  const actualPerHead = attendance > 0 ? ((rev.baseline_concession || 0) - (rev.concession_loss || 0)) / attendance : 0;

  const breakdown = [
    { name: 'Concession loss', value: rev.concession_loss || 0, color: 'var(--status-warn)', note: `8%/min penalty × ${waitMean.toFixed(1)} min avg wait` },
    { name: 'Merch loss', value: rev.merch_loss || 0, color: '#f97316', note: 'Density + wait degradation' },
    { name: 'Future ticket loss', value: rev.future_ticket_loss || 0, color: 'var(--status-danger)', note: 'HES-driven repeat attendance risk' },
  ];

  return {
    title: 'Revenue Impact',
    value: totalLoss,
    unit: 'est. loss',
    formula: 'Loss = Σ(baseline_spend × penalty_rate × wait_minutes)',
    formulaName: 'NAC industry benchmark model',
    breakdown,
    perHeadBaseline: perHeadSpend,
    perHeadActual: actualPerHead,
    attendance,
    source: 'NAC concession benchmarks · 8%/min penalty · 20% spend floor',
  };
}

export function getBottleneckDerivation(results) {
  if (!results) return null;
  const nodeMetrics = results.simulation?.node_metrics || {};
  const topNodes = Object.entries(nodeMetrics)
    .sort((a, b) => (b[1].util_mean || 0) - (a[1].util_mean || 0));

  if (topNodes.length === 0) return null;

  const [bottleneckId, bottleneckData] = topNodes[0];
  const top5 = topNodes.slice(0, 5).map(([id, data]) => ({
    id: id.replace(/_/g, ' '),
    utilization: data.util_mean || 0,
    waitMean: data.wait_mean || 0,
    bottleneckFreq: data.bottleneck_frequency || 0,
  }));

  const util = bottleneckData.util_mean || 0;
  const overloaded = util > 1;

  return {
    title: 'Bottleneck Analysis',
    value: bottleneckId.replace(/_/g, ' '),
    unit: `${(util * 100).toFixed(0)}% utilization`,
    nodeDetail: {
      id: bottleneckId,
      utilization: util,
      waitMean: bottleneckData.wait_mean || 0,
      bottleneckFreq: bottleneckData.bottleneck_frequency || 0,
    },
    top5,
    overloaded,
    explanation: overloaded
      ? `${bottleneckId.replace(/_/g, ' ')} is at ${(util * 100).toFixed(0)}% utilization — demand exceeds capacity. Queue grows without bound.`
      : `${bottleneckId.replace(/_/g, ' ')} is the highest-utilized node at ${(util * 100).toFixed(0)}%.`,
    source: 'Queueing network solver · per-node utilization from 1,000 MC trials',
  };
}

export function getFruinDerivation(results) {
  if (!results) return null;
  const fruin = results.metrics?.fruin || {};
  if (!fruin.worst_grade) return null;

  const gradeDist = fruin.grade_distribution || {};
  const grades = ['A', 'B', 'C', 'D', 'E', 'F'];

  const gradeInfo = [
    { grade: 'A', density: '< 0.31', speed: '> 1.30 m/s', description: 'Free flow, no restrictions' },
    { grade: 'B', density: '0.31–0.43', speed: '1.27 m/s', description: 'Minor conflicts possible' },
    { grade: 'C', density: '0.43–0.72', speed: '1.22 m/s', description: 'Speed restricted, some conflicts' },
    { grade: 'D', density: '0.72–1.08', speed: '1.14 m/s', description: 'Restricted movement, frequent conflicts' },
    { grade: 'E', density: '1.08–2.17', speed: '0.76 m/s', description: 'Severely restricted, shuffling gait' },
    { grade: 'F', density: '> 2.17', speed: '< 0.46 m/s', description: 'Crush conditions, potential danger' },
  ];

  const distribution = grades.map(g => ({
    grade: g,
    count: gradeDist[g] || 0,
    info: gradeInfo.find(gi => gi.grade === g),
  }));

  // Find worst node details
  const nodeMetrics = results.simulation?.node_metrics || {};
  let worstNode = null;
  let worstDensity = 0;
  for (const [id, data] of Object.entries(nodeMetrics)) {
    const density = data.density_mean || 0;
    if (density > worstDensity) {
      worstDensity = density;
      worstNode = id;
    }
  }

  return {
    title: 'Fruin Level of Service',
    value: `LOS ${fruin.worst_grade}`,
    unit: '',
    worstGrade: fruin.worst_grade,
    distribution,
    gradeInfo,
    worstNode: worstNode ? {
      id: worstNode.replace(/_/g, ' '),
      density: worstDensity,
      grade: fruin.worst_grade,
    } : null,
    source: 'HCM6 / Fruin pedestrian density grading · per-node density analysis',
  };
}

/** Master lookup: returns derivation function for a given metric key */
export const DERIVATION_MAP = {
  wait: getWaitDerivation,
  experience: getHESDerivation,
  safety: getSafetyDerivation,
  revenue: getRevenueDerivation,
  bottleneck: getBottleneckDerivation,
  fruin: getFruinDerivation,
};
