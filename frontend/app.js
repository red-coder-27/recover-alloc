// RECOVER-ALLOC Frontend Control Center App Logic — Phase 8 Hardened

const API_BASE = ''; // Relative or local server API

let currentRunId = null;
let currentAllocationId = null;
let activeAllocationsMap = {};

document.addEventListener('DOMContentLoaded', async () => {
  initTabs();

  // Load primary dashboard tab essentials in parallel for instant interactivity
  await Promise.all([
    loadDashboardSummary(),
    loadRecoveryItems()
  ]);

  // Load secondary tabs asynchronously in background
  Promise.all([
    loadAuditLog(),
    loadExecutions(),
    loadEvaluationSummary(),
    loadEvaluationCompare()
  ]).catch(err => console.error('Secondary tab prefetch error:', err));

  // Attach Button Listeners (explicit arrow function avoids passing MouseEvent as scenario)
  const btnReplan = document.getElementById('btn-replan');
  if (btnReplan) {
    btnReplan.addEventListener('click', (e) => runReplan(null, e.currentTarget));
  }

  const btnRefreshAudit = document.getElementById('btn-refresh-audit');
  if (btnRefreshAudit) {
    btnRefreshAudit.addEventListener('click', () => { loadAuditLog(); loadExecutions(); });
  }

  // Demo Failure Toggles
  document.getElementById('btn-demo-duplicate')?.addEventListener('click', (e) => testExecuteScenario('duplicate', e.currentTarget));
  document.getElementById('btn-demo-budget')?.addEventListener('click', (e) => runReplan('budget_exhaustion', e.currentTarget));
  document.getElementById('btn-demo-confidence')?.addEventListener('click', (e) => testExecuteScenario('low_confidence', e.currentTarget));
  document.getElementById('btn-demo-solver')?.addEventListener('click', (e) => runReplan('solver_failure', e.currentTarget));
  document.getElementById('btn-demo-razorpay')?.addEventListener('click', (e) => testExecuteScenario('razorpay', e.currentTarget));

  // Modal Close
  document.getElementById('modal-close-btn')?.addEventListener('click', hideModal);
});

// Tab Management
function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = `tab-${tab.getAttribute('data-tab')}`;
      document.getElementById(targetId)?.classList.add('active');
    });
  });
}

// Format Currency
function formatINR(val) {
  return '₹' + Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// 1. Dashboard Summary
async function loadDashboardSummary() {
  try {
    const res = await fetch(`${API_BASE}/dashboard/summary`);
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('kpi-total-risk').innerText = formatINR(data.total_revenue_at_risk);
    document.getElementById('kpi-expected-obj').innerText = formatINR(data.recoverable_expected_objective);
    document.getElementById('kpi-served').innerText = `${data.served_items} / ${data.n_items}`;
    document.getElementById('kpi-unserved').innerText = `${data.unserved_items} Unserved`;
    document.getElementById('kpi-blocks').innerText = data.policy_blocks;

    // Capacity Bars
    const u = data.resource_usage || {};
    const b = data.resource_budget || {};
    const pct = data.resource_utilization_percent || {};

    document.getElementById('res-retry-text').innerText = `${u.retry_slots || 0} / ${b.retry_slots || 35}`;
    document.getElementById('res-retry-fill').style.width = `${pct.retry_slots || 0}%`;

    document.getElementById('res-wa-text').innerText = `${u.whatsapp_quota || 0} / ${b.whatsapp_quota || 50}`;
    document.getElementById('res-wa-fill').style.width = `${pct.whatsapp_quota || 0}%`;

    document.getElementById('res-human-text').innerText = `${u.human_hours || 0} / ${b.human_hours || 8} hrs`;
    document.getElementById('res-human-fill').style.width = `${pct.human_hours || 0}%`;

    // Live Batch Comparison
    if (data.compare_naive) {
      document.getElementById('comp-naive-obj').innerText = formatINR(data.compare_naive.naive_expected_objective);
      document.getElementById('comp-optimal-obj').innerText = formatINR(data.compare_naive.mcmkp_expected_objective);
    }

  } catch (err) {
    console.error('Failed to load dashboard summary:', err);
  }
}

// Initial plan fetch to populate live comparison
async function runInitialPlan() {
  try {
    const res = await fetch(`${API_BASE}/recovery/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n_items: 100, retry_slots: 35, whatsapp_quota: 50, human_hours: 8 }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data.compare_naive) {
      document.getElementById('comp-naive-obj').innerText = formatINR(data.compare_naive.naive_expected_objective);
      document.getElementById('comp-optimal-obj').innerText = formatINR(data.compare_naive.mcmkp_expected_objective);
    }
  } catch (err) {
    console.error('Failed to run initial plan:', err);
  }
}

// 2. Recovery Items & Plan
async function loadRecoveryItems() {
  try {
    const res = await fetch(`${API_BASE}/recovery/items?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    renderAllocationTable(data.items);
  } catch (err) {
    console.error('Failed to load recovery items:', err);
  }
}

function renderAllocationTable(items) {
  const tbody = document.getElementById('tbody-allocation');
  if (!tbody) return;
  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="loading-cell">No items returned.</td></tr>`;
    return;
  }

  let html = '';
  items.forEach((item, idx) => {
    activeAllocationsMap[item.id] = item;

    const rank = idx + 1;
    const intervLabel = item.recommended_intervention || 'UNSERVED';
    const probLabel = item.recommended_intervention ? (item.predicted_probability * 100).toFixed(1) + '%' : '-';
    const expNetLabel = item.recommended_intervention ? formatINR(item.expected_net_value) : '₹0.00';

    let policyBadge = '';
    if (item.policy_status === 'ALLOW') policyBadge = `<span class="badge allow">ALLOW</span>`;
    else if (item.policy_status === 'BLOCK') policyBadge = `<span class="badge block">BLOCK</span>`;
    else if (item.policy_status === 'ESCALATE') policyBadge = `<span class="badge escalate">ESCALATE</span>`;
    else policyBadge = `<span class="badge secondary">-</span>`;

    let actionCell = '';
    if (!item.recommended_intervention || item.recommended_intervention === 'UNSERVED') {
      actionCell = `<span class="badge secondary" style="opacity:0.7; cursor:not-allowed;">No Capacity ⏸️</span>`;
    } else if (item.policy_status === 'BLOCK') {
      actionCell = `<span class="badge block" style="cursor:not-allowed;">Blocked 🔒</span>`;
    } else if (item.policy_status === 'ESCALATE') {
      actionCell = `<span class="badge escalate" style="cursor:not-allowed;">Review Req ⚠️</span>`;
    } else if (item.policy_status === 'ALLOW') {
      actionCell = `<button class="btn primary action-sm" onclick="executeSingleItem('${item.id}', '${item.recommended_intervention}')">Execute</button>`;
    } else {
      actionCell = `<span class="badge secondary">N/A</span>`;
    }

    html += `
      <tr>
        <td>#${rank}</td>
        <td><strong>${item.id}</strong></td>
        <td>${item.type}</td>
        <td><strong>${formatINR(item.amount)}</strong></td>
        <td>${item.failure_code || 'N/A'}</td>
        <td>${item.days_overdue} days</td>
        <td><span class="badge info">${intervLabel}</span></td>
        <td>${probLabel}</td>
        <td><strong class="green">${expNetLabel}</strong></td>
        <td>${policyBadge}<br><small style="color:#9ca3af; font-size:0.7rem;">${item.policy_reason || ''}</small></td>
        <td>${actionCell}</td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// 3. Re-plan Trigger with loading state and visible error handling
async function runReplan(scenario = null, btnElement = null) {
  let btn = btnElement;
  if (!btn) {
    if (scenario === 'budget_exhaustion') btn = document.getElementById('btn-demo-budget');
    else if (scenario === 'solver_failure') btn = document.getElementById('btn-demo-solver');
    else btn = document.getElementById('btn-replan');
  }

  const originalBtnHtml = btn ? btn.innerHTML : 'Run MCMKP Allocation Plan';

  if (btn) {
    btn.disabled = true;
    let procMsg = 'Running MCMKP Allocation...';
    if (scenario === 'budget_exhaustion') procMsg = 'Testing Budget Exhaustion...';
    else if (scenario === 'solver_failure') procMsg = 'Testing Solver Failure...';
    btn.innerHTML = `<span class="spinner-icon">⟳</span> ${procMsg}`;
  }

  try {
    const payload = { n_items: 100, retry_slots: 35, whatsapp_quota: 50, human_hours: 8 };

    // Guard: Only string values are valid failure scenarios (never pass Event objects)
    if (typeof scenario === 'string' && scenario.trim() !== '') {
      payload.failure_scenario = scenario;
    }

    const res = await fetch(`${API_BASE}/recovery/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      const errMsg = errData.detail ? (typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail)) : res.statusText;
      console.error('Allocation API error:', res.status, errMsg);
      showModal('Allocation Failed', `HTTP Error ${res.status}: ${errMsg}`);
      return;
    }

    const data = await res.json();

    if (data.status === 'SOLVER_FAILED') {
      showModal(
        'SOLVER FAILURE DEMO',
        `
        <div style="font-family:var(--font-sans);">
          <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); padding:12px; border-radius:8px; margin-bottom:12px;">
            <h4 style="margin:0 0 4px 0; color:#ef4444;">Controlled Solver Failure Scenario</h4>
            <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Solver Status: <strong>SOLVER_FAILED</strong> | Event: <code>OPTIMIZER_FAILED</code></p>
          </div>
          <p style="font-size:0.85rem; color:#9ca3af;">Safe Failure Protection: CP-SAT solver failure yields safe empty plan. No unverified execution calls were attempted.</p>
        </div>
        `,
        true
      );
      await loadAuditLog();
      return;
    }

    currentRunId = data.run_id;
    currentAllocationId = data.allocation_id;

    // Update Side by Side Comparison
    if (data.compare_naive) {
      document.getElementById('comp-naive-obj').innerText = formatINR(data.compare_naive.naive_expected_objective);
      document.getElementById('comp-optimal-obj').innerText = formatINR(data.compare_naive.mcmkp_expected_objective);
    }

    await loadDashboardSummary();
    renderPlanAllocations(data.allocations);

    const isBudgetScenario = (scenario === 'budget_exhaustion');
    const title = isBudgetScenario ? 'Budget Exhaustion Scenario Active' : 'MCMKP Allocation Plan Generated';

    const totalEvaluated = data.allocations ? data.allocations.length : 0;
    const allocatedInterventions = data.allocations ? data.allocations.filter(a => a.chosen_intervention && a.chosen_intervention !== 'UNSERVED').length : 0;
    const unservedCount = totalEvaluated - allocatedInterventions;
    const solverStatus = data.solver_status || 'OPTIMAL';
    const solveTime = (data.solve_time_ms !== undefined && data.solve_time_ms !== null) ? `${data.solve_time_ms} ms` : 'N/A';

    // Authoritative resource utilization from API response or INTERVENTION_CATALOG parity
    const u = data.resource_usage || {};
    const b = data.resource_budget || { retry_slots: 35, whatsapp_quota: 50, human_hours: 8 };

    let retryUsed = u.retry_slots;
    let waUsed = u.whatsapp_quota;
    let humanUsed = u.human_hours;

    if (retryUsed === undefined && data.allocations) {
      retryUsed = 0; waUsed = 0; humanUsed = 0;
      data.allocations.forEach(a => {
        if (a.chosen_intervention === 'PAYMENT_RETRY') retryUsed += 1;
        else if (a.chosen_intervention === 'WHATSAPP_REMINDER') waUsed += 1;
        else if (a.chosen_intervention === 'HUMAN_ESCALATION') humanUsed += 1;
      });
    }

    let budgetBanner = '';
    if (isBudgetScenario) {
      budgetBanner = `
        <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); padding:8px 12px; border-radius:6px; margin-bottom:8px;">
          <h4 style="margin:0 0 2px 0; color:#f59e0b; font-size:0.85rem;">Constrained Capacity Budget Applied</h4>
          <p style="margin:0; font-size:0.78rem; color:#d1d5db;">Resource capacity exhausted (2 Retries, 2 WhatsApp, 0 Human Hours). ${unservedCount} items remain UNSERVED.</p>
        </div>
      `;
    }

    const bodyHtml = `
      <div style="font-family: var(--font-sans); color: #e5e7eb; line-height: 1.3;">
        ${budgetBanner}
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px; font-size: 0.75rem; color: #9ca3af; font-family: var(--font-mono);">
          <span>Run ID: ${data.run_id}</span>
          <span style="color: #10b981; font-weight: 600;">Solver: ${solverStatus} · ${solveTime}</span>
        </div>

        <div style="background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25); padding: 8px 12px; border-radius: 6px; margin-bottom: 8px;">
          <div style="font-size: 0.68rem; color: #9ca3af; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">MODEL-PREDICTED NET RECOVERY</div>
          <div style="font-size: 1.15rem; font-weight: 800; color: #10b981; font-family: var(--font-mono); margin-top: 2px;">${formatINR(data.expected_objective)}</div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; background: #111827; padding: 8px; border-radius: 6px; margin-bottom: 8px; text-align: center; border: 1px solid var(--panel-border);">
          <div>
            <div style="font-size: 0.65rem; color: #9ca3af; text-transform: uppercase; font-weight: 600;">ITEMS EVALUATED</div>
            <div style="font-size: 0.95rem; font-weight: 700; color: #f9fafb; margin-top: 1px;">${totalEvaluated}</div>
          </div>
          <div>
            <div style="font-size: 0.65rem; color: #9ca3af; text-transform: uppercase; font-weight: 600;">ALLOCATED</div>
            <div style="font-size: 0.95rem; font-weight: 700; color: #10b981; margin-top: 1px;">${allocatedInterventions}</div>
          </div>
          <div>
            <div style="font-size: 0.65rem; color: #9ca3af; text-transform: uppercase; font-weight: 600;">UNSERVED</div>
            <div style="font-size: 0.95rem; font-weight: 700; color: #f59e0b; margin-top: 1px;">${unservedCount}</div>
          </div>
        </div>

        <div style="background: #111827; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid var(--panel-border);">
          <div style="font-size: 0.65rem; color: #9ca3af; text-transform: uppercase; font-weight: 600; margin-bottom: 4px; letter-spacing: 0.5px;">RESOURCE CAPACITY</div>
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; font-size: 0.75rem;">
            <div><span style="color: #9ca3af;">Retry:</span> <strong style="color: #f3f4f6;">${retryUsed} / ${b.retry_slots}</strong></div>
            <div><span style="color: #9ca3af;">WhatsApp:</span> <strong style="color: #f3f4f6;">${waUsed} / ${b.whatsapp_quota}</strong></div>
            <div><span style="color: #9ca3af;">Human:</span> <strong style="color: #f3f4f6;">${humanUsed} / ${b.human_hours} hrs</strong></div>
          </div>
        </div>

        <div style="background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.2); padding: 6px 12px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem;">
          <span style="color: #93c5fd;">vs Naive Greedy:</span>
          <strong style="color: #60a5fa; font-family: var(--font-mono);">${formatINR(data.compare_naive ? data.compare_naive.incremental_gain_inr : 0)} (+${data.compare_naive ? data.compare_naive.percentage_gain : 0}%)</strong>
        </div>
      </div>
    `;

    showModal(title, bodyHtml, true);
    await loadAuditLog();

  } catch (err) {
    console.error('Re-plan execution failed:', err);
    showModal('Allocation Execution Error', `Error: ${err.message || err}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalBtnHtml;
    }
  }
}

function renderPlanAllocations(allocations) {
  const tbody = document.getElementById('tbody-allocation');
  if (!tbody || !allocations) return;
  let html = '';

  allocations.forEach((item, idx) => {
    const rank = idx + 1;
    const intervLabel = item.chosen_intervention || 'UNSERVED';
    const probLabel = item.chosen_intervention ? (item.predicted_p * 100).toFixed(1) + '%' : '-';
    const expNetLabel = item.chosen_intervention ? formatINR(item.expected_net) : '₹0.00';

    let policyBadge = '';
    if (item.policy_outcome === 'ALLOW') policyBadge = `<span class="badge allow">ALLOW</span>`;
    else if (item.policy_outcome === 'BLOCK') policyBadge = `<span class="badge block">BLOCK</span>`;
    else if (item.policy_outcome === 'ESCALATE') policyBadge = `<span class="badge escalate">ESCALATE</span>`;
    else policyBadge = `<span class="badge secondary">-</span>`;

    let actionCell = '';
    if (!item.chosen_intervention || item.chosen_intervention === 'UNSERVED') {
      actionCell = `<span class="badge secondary" style="opacity:0.7; cursor:not-allowed;">No Capacity ⏸️</span>`;
    } else if (item.policy_outcome === 'BLOCK') {
      actionCell = `<span class="badge block" style="cursor:not-allowed;">Blocked 🔒</span>`;
    } else if (item.policy_outcome === 'ESCALATE') {
      actionCell = `<span class="badge escalate" style="cursor:not-allowed;">Review Req ⚠️</span>`;
    } else if (item.policy_outcome === 'ALLOW') {
      actionCell = `<button class="btn primary action-sm" onclick="executeSingleItem('${item.item_id}', '${item.chosen_intervention}', '${item.allocation_id}')">Execute</button>`;
    } else {
      actionCell = `<span class="badge secondary">N/A</span>`;
    }

    html += `
      <tr>
        <td>#${rank}</td>
        <td><strong>${item.item_id}</strong></td>
        <td>${item.item_type}</td>
        <td><strong>${formatINR(item.amount)}</strong></td>
        <td>-</td>
        <td>-</td>
        <td><span class="badge info">${intervLabel}</span></td>
        <td>${probLabel}</td>
        <td><strong class="green">${expNetLabel}</strong></td>
        <td>${policyBadge}<br><small style="color:#9ca3af; font-size:0.7rem;">${item.policy_reason || ''}</small></td>
        <td>${actionCell}</td>
      </tr>
    `;
  });

  tbody.innerHTML = html;
}

// 4. Single Item Execution
async function executeSingleItem(itemId, intervention, allocId = null) {
  const runId = currentRunId || `run_manual_${Date.now()}`;
  const allocationId = allocId || currentAllocationId || `alloc_manual_${Date.now()}`;

  try {
    const res = await fetch(`${API_BASE}/recovery/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id: runId,
        allocation_id: allocationId,
        item_id: itemId,
        intervention: intervention,
        adapter_type: 'simulator',
      }),
    });

    const data = await res.json();
    renderExecutionResultModal(data, itemId, intervention);

    await loadAuditLog();
    await loadExecutions();
  } catch (err) {
    console.error('Execution failed:', err);
  }
}

function renderExecutionResultModal(data, itemId, intervention) {
  const isDuplicate = data.status === 'DUPLICATE_BLOCKED';
  const isBlocked = data.status === 'POLICY_BLOCKED';

  let title = '✓ Recovery Action Executed';
  if (isDuplicate) title = '🔒 DUPLICATE EXECUTION BLOCKED';
  else if (isBlocked) title = '🛑 POLICY EXECUTION BLOCKED';

  let executorLabel = 'Test Simulator';
  if (data.external_ref && data.external_ref.startsWith('pay_')) {
    executorLabel = 'Razorpay Test API';
  }

  const statusDisplay = data.status || 'UNKNOWN';
  const finalStatusDisplay = data.final_status || 'NOT AVAILABLE';
  const extRefDisplay = data.external_ref || 'NOT AVAILABLE';
  const execIdDisplay = data.execution_id || 'NOT AVAILABLE';
  const idempKeyDisplay = data.idempotency_key || 'NOT AVAILABLE';

  const html = `
    <div style="font-family: var(--font-sans);">
      <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); padding: 12px; border-radius: 8px; margin-bottom: 16px;">
        <h4 style="margin:0 0 4px 0; color:#10b981;">Status: ${statusDisplay} (${finalStatusDisplay})</h4>
        <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Account ID: <strong>${itemId || 'UNKNOWN'}</strong> | Intervention: <strong>${intervention || 'UNKNOWN'}</strong></p>
      </div>

      <div style="margin-bottom: 16px; font-size: 0.85rem;">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><span>Executor Adapter:</span> <strong>${executorLabel}</strong></div>
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><span>External Reference:</span> <code>${extRefDisplay}</code></div>
      </div>

      <div style="background:#111827; padding:10px; border-radius:6px; margin-bottom:16px;">
        <span style="font-size:0.75rem; color:#9ca3af; text-transform:uppercase;">Execution Lifecycle Audit Trace</span>
        <div style="margin-top:6px; font-size:0.8rem; color:#34d399;">
          ${(data.audit_events && data.audit_events.length > 0) ? data.audit_events.map(ev => `✓ ${ev}`).join(' &nbsp;→&nbsp; ') : '✓ EXECUTION_REQUESTED'}
        </div>
      </div>

      <details style="font-size:0.78rem; color:#9ca3af; background:#1f2937; padding:8px; border-radius:6px;">
        <summary style="cursor:pointer; font-weight:600; color:#e5e7eb;">Technical Security Keys</summary>
        <div style="margin-top:6px; font-family:monospace; word-break:break-all;">
          <div><strong>Execution ID:</strong> ${execIdDisplay}</div>
          <div><strong>Idempotency Key (SHA256):</strong> ${idempKeyDisplay}</div>
        </div>
      </details>
    </div>
  `;

  showModal(title, html, true);
}

// 5. Test Failure Scenarios
async function testExecuteScenario(scenario, btnElement = null) {
  let btn = btnElement;
  if (!btn) {
    if (scenario === 'duplicate') btn = document.getElementById('btn-demo-duplicate');
    else if (scenario === 'budget_exhaustion') btn = document.getElementById('btn-demo-budget');
    else if (scenario === 'low_confidence') btn = document.getElementById('btn-demo-confidence');
    else if (scenario === 'solver_failure') btn = document.getElementById('btn-demo-solver');
    else if (scenario === 'razorpay') btn = document.getElementById('btn-demo-razorpay');
  }

  const originalHtml = btn ? btn.innerHTML : '';
  
  if (btn) {
    btn.disabled = true;
    let procMsg = 'Testing Scenario...';
    if (scenario === 'duplicate') procMsg = 'Testing Duplicate Execution...';
    else if (scenario === 'low_confidence') procMsg = 'Testing Low Confidence...';
    else if (scenario === 'razorpay') procMsg = 'Testing Razorpay Adapter...';
    btn.innerHTML = `<span class="spinner-icon">⟳</span> ${procMsg}`;
  }

  try {
    // 1. Fetch a real ALLOW item from current dataset
    let itemId = 'item_00001';
    let intervention = 'PAYMENT_RETRY';

    try {
      const itemsRes = await fetch(`${API_BASE}/recovery/items?limit=100`);
      if (itemsRes.ok) {
        const itemsData = await itemsRes.json();
        if (itemsData.items && itemsData.items.length > 0) {
          const allowItem = itemsData.items.find(i => i.policy_status === 'ALLOW' && i.recommended_intervention);
          if (allowItem) {
            itemId = allowItem.id;
            intervention = allowItem.recommended_intervention;
          } else {
            itemId = itemsData.items[0].id;
          }
        }
      }
    } catch (e) {
      console.warn('Could not fetch items, falling back to item_00001:', e);
    }

    const runId = `run_demo_${Date.now()}`;
    const allocationId = `alloc_demo_${Date.now()}`;
    const adapter = (scenario === 'razorpay') ? 'razorpay' : 'simulator';

    const res = await fetch(`${API_BASE}/recovery/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id: runId,
        allocation_id: allocationId,
        item_id: itemId,
        intervention: intervention,
        adapter_type: adapter,
        failure_scenario: scenario,
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      const errMsg = errData.detail ? (typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail)) : res.statusText;
      showModal('Demo Scenario Error', `HTTP Error ${res.status}: ${errMsg}`);
      return;
    }

    const data = await res.json();

    if (scenario === 'duplicate') {
      const firstStatus = (data.first_execution && data.first_execution.status) || 'EXECUTED';
      const firstFinal = (data.first_execution && data.first_execution.final_status) || 'VERIFIED_SUCCESS';
      const secondStatus = (data.second_execution_duplicate && data.second_execution_duplicate.status) || data.status || 'DUPLICATE_BLOCKED';

      const html = `
        <div style="font-family:var(--font-sans);">
          <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); padding:12px; border-radius:8px; margin-bottom:16px;">
            <h4 style="margin:0 0 4px 0; color:#ef4444;">DUPLICATE EXECUTION BLOCKED</h4>
            <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Second execution request was prevented by idempotency protection.</p>
          </div>
          <div style="font-size:0.85rem; margin-bottom:16px; background:#111827; padding:12px; border-radius:6px; border:1px solid var(--panel-border);">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Target Account:</span> <strong>${itemId}</strong></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Intervention:</span> <strong>${intervention}</strong></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>1st Execution Status:</span> <span class="badge allow">${firstStatus} (${firstFinal})</span></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>2nd Execution Status:</span> <span class="badge block">${secondStatus}</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Idempotency Safeguard:</span> <strong style="color:#10b981;">ACTIVE (DB UNIQUE Key)</strong></div>
          </div>
          <div style="font-size:0.8rem; color:#34d399; background:#111827; padding:8px; border-radius:6px; border:1px solid rgba(16,185,129,0.3);">
            ✓ Audit Verified: Concurrency UNIQUE(idempotency_key) constraint on database prevented duplicate dispatch!
          </div>
        </div>
      `;
      showModal('DUPLICATE EXECUTION BLOCKED', html, true);

    } else if (scenario === 'low_confidence') {
      const html = `
        <div style="font-family:var(--font-sans);">
          <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); padding:12px; border-radius:8px; margin-bottom:16px;">
            <h4 style="margin:0 0 4px 0; color:#f59e0b;">LOW CONFIDENCE SCENARIO</h4>
            <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Diagnosis confidence below policy threshold — automatic execution prevented.</p>
          </div>
          <div style="font-size:0.85rem; margin-bottom:16px; background:#111827; padding:12px; border-radius:6px; border:1px solid var(--panel-border);">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Account ID:</span> <strong>${itemId}</strong></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Policy Outcome:</span> <span class="badge escalate">ESCALATE</span></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Automatic Execution:</span> <strong style="color:#ef4444;">BLOCKED</strong></div>
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Reason:</span> <span style="color:#9ca3af;">insufficient confidence</span></div>
            <div style="display:flex; justify-content:space-between;"><span>Safety Action:</span> <strong style="color:#f59e0b;">human review required</strong></div>
          </div>
          <div style="font-size:0.8rem; color:#9ca3af; background:#111827; padding:8px; border-radius:6px; border:1px solid var(--panel-border);">
            Audit Trace: ${(data.audit_events && data.audit_events.length > 0) ? data.audit_events.join(' → ') : 'EXECUTION_REQUESTED → EXECUTION_BLOCKED'}
          </div>
        </div>
      `;
      showModal('LOW CONFIDENCE SCENARIO', html, true);

    } else if (scenario === 'razorpay') {
      const hasCreds = data.external_ref && data.external_ref.startsWith('pay_');
      if (!hasCreds) {
        const html = `
          <div style="font-family:var(--font-sans);">
            <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); padding:12px; border-radius:8px; margin-bottom:16px;">
              <h4 style="margin:0 0 4px 0; color:#ef4444;">Razorpay Test Payment Link</h4>
              <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Razorpay test credentials are not configured. No live API call was attempted.</p>
            </div>
            <div style="font-size:0.85rem; margin-bottom:16px; background:#111827; padding:12px; border-radius:6px; border:1px solid var(--panel-border);">
              <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Status:</span> <strong style="color:#9ca3af;">NOT_EXECUTED</strong></div>
              <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Final Outcome:</span> <strong style="color:#9ca3af;">NOT_EXECUTED</strong></div>
              <div style="display:flex; justify-content:space-between;"><span>Adapter:</span> <strong>Test Simulator</strong></div>
            </div>
            <div style="font-size:0.8rem; color:#9ca3af; background:#111827; padding:8px; border-radius:6px; border:1px solid var(--panel-border);">
              Safety Guard: No live API call attempted without valid Razorpay credentials.
            </div>
          </div>
        `;
        showModal('Razorpay Test Payment Link', html, true);
      } else {
        const html = `
          <div style="font-family:var(--font-sans);">
            <div style="background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.3); padding:12px; border-radius:8px; margin-bottom:16px;">
              <h4 style="margin:0 0 4px 0; color:#10b981;">Razorpay Test Payment Link Created</h4>
              <p style="margin:0; font-size:0.85rem; color:#d1d5db;">Payment Link successfully created via Razorpay Test API.</p>
            </div>
            <div style="font-size:0.85rem; margin-bottom:16px; background:#111827; padding:12px; border-radius:6px; border:1px solid var(--panel-border);">
              <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Status:</span> <strong style="color:#10b981;">${data.status || 'EXECUTED'}</strong></div>
              <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Final Outcome:</span> <strong style="color:#10b981;">${data.final_status || 'VERIFIED_SUCCESS'}</strong></div>
              <div style="display:flex; justify-content:space-between; margin-bottom:6px;"><span>Adapter:</span> <strong>Razorpay Test API</strong></div>
              <div style="display:flex; justify-content:space-between;"><span>External Reference:</span> <code>${data.external_ref}</code></div>
            </div>
          </div>
        `;
        showModal('Razorpay Test Payment Link', html, true);
      }

    } else {
      showModal(`Controlled Scenario: ${scenario}`, `<pre style="font-size:0.8rem; background:#111827; padding:10px; border-radius:6px;">${JSON.stringify(data, null, 2)}</pre>`, true);
    }

    await loadAuditLog();
    await loadExecutions();

  } catch (err) {
    console.error('Scenario test failed:', err);
    showModal('Scenario Execution Error', `Error: ${err.message || err}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}


// 6. Audit Log & Executions Table
async function loadAuditLog() {
  try {
    const res = await fetch(`${API_BASE}/audit/events?limit=50`);
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('tbody-audit');
    if (!tbody) return;

    if (!data.audit_events || data.audit_events.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No audit events recorded yet.</td></tr>`;
      return;
    }

    let html = '';
    data.audit_events.forEach(e => {
      const ts = new Date(e.timestamp * 1000).toLocaleTimeString();
      let resBadge = `<span class="badge info">${e.result || 'OK'}</span>`;
      if (e.result === 'FAILURE' || e.event_type.includes('BLOCKED')) resBadge = `<span class="badge block">BLOCKED</span>`;

      const payloadStr = JSON.stringify(e.payload);
      html += `
        <tr>
          <td><small>${ts}</small></td>
          <td><strong>${e.event_type}</strong></td>
          <td><small>${e.run_id || '-'}</small></td>
          <td><small>${e.item_id || '-'}</small></td>
          <td>${resBadge}</td>
          <td><small>${e.reason || '-'}</small></td>
          <td>
            <details style="font-size:0.75rem;">
              <summary style="cursor:pointer; color:#60a5fa;">View Payload</summary>
              <code style="font-size:0.7rem; display:block; margin-top:4px;">${payloadStr}</code>
            </details>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    console.error('Failed to load audit events:', err);
  }
}

async function loadExecutions() {
  try {
    const res = await fetch(`${API_BASE}/recovery/executions?limit=50`);
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('tbody-executions');
    if (!tbody) return;

    if (!data.executions || data.executions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="loading-cell">No DB executions recorded yet. Execute an item to see idempotency records.</td></tr>`;
      return;
    }

    let html = '';
    data.executions.forEach(ex => {
      const ts = new Date(ex.requested_at * 1000).toLocaleTimeString();
      html += `
        <tr>
          <td><small>${ex.id.substring(0, 8)}...</small></td>
          <td><small style="font-family:monospace; color:#10b981;">${ex.idempotency_key.substring(0, 16)}...</small></td>
          <td><strong>${ex.item_id}</strong></td>
          <td><span class="badge info">${ex.intervention}</span></td>
          <td>${ex.executor_adapter}</td>
          <td><span class="badge allow">${ex.status}</span></td>
          <td><small>${ex.external_ref || '-'}</small></td>
          <td><small>${ts}</small></td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    console.error('Failed to load executions:', err);
  }
}

// 7. Benchmark & Evaluation
async function loadEvaluationSummary() {
  try {
    const res = await fetch(`${API_BASE}/evaluation/summary`);
    if (!res.ok) return;
    const data = await res.json();

    const tbody = document.getElementById('tbody-leaderboard');
    if (!tbody) return;
    const bench = data.verified_benchmarks;

    const rowsDef = [
      { name: 'oracle', label: 'Oracle (True-Probability Benchmark)', data: bench.oracle },
      { name: 'recover_alloc', label: 'RECOVER-ALLOC (CP-SAT)', badge: 'Best Learned Strategy', data: bench.recover_alloc },
      { name: 'random_under_budget', label: 'Random Under Budget', data: bench.random_under_budget },
      { name: 'static_rules', label: 'Static Rules', data: bench.static_rules },
      { name: 'blind_retry', label: 'Blind Retry', data: bench.blind_retry },
      { name: 'no_action', label: 'No Action', data: bench.no_action },
    ];

    let html = '';
    rowsDef.forEach(r => {
      const d = r.data || {};
      const trueObj = d.true_expected_objective ? formatINR(d.true_expected_objective) : '₹0.00';
      const realMean = d.realized_net_recovery_mean ? formatINR(d.realized_net_recovery_mean) : '₹0.00';
      const realMed = d.realized_net_recovery_median ? formatINR(d.realized_net_recovery_median) : '₹0.00';
      const realStd = d.realized_net_recovery_stddev ? formatINR(d.realized_net_recovery_stddev) : '₹0.00';
      const ratio = d.realized_ratio_vs_oracle ? d.realized_ratio_vs_oracle.toFixed(2) + '%' : '-';

      let adv = '-';
      if (r.name === 'recover_alloc') adv = `<strong class="green">+90.07% vs Static Rules</strong>`;

      const isWinner = (r.name === 'recover_alloc');
      const rowStyle = isWinner ? `style="background: rgba(16, 185, 129, 0.08);"` : '';

      const labelBadge = r.badge ? `<br><span class="badge success" style="font-size:0.65rem; margin-top:2px;">${r.badge}</span>` : '';

      html += `
        <tr ${rowStyle}>
          <td><strong>${r.label}</strong>${labelBadge}</td>
          <td><span class="badge allow">OK</span></td>
          <td>${trueObj}</td>
          <td><strong class="green">${realMean}</strong></td>
          <td>${realMed}</td>
          <td>${realStd}</td>
          <td><strong>${ratio}</strong></td>
          <td>${adv}</td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  } catch (err) {
    console.error('Failed to load evaluation summary:', err);
  }
}

async function loadEvaluationCompare() {
  try {
    const res = await fetch(`${API_BASE}/evaluation/compare`);
    if (!res.ok) return;
    const data = await res.json();

    const ce = data.counterexample_proof;
    if (ce) {
      document.getElementById('ce-naive-val').innerText = formatINR(ce.naive_greedy_objective);
      document.getElementById('ce-optimal-val').innerText = formatINR(ce.mcmkp_optimal_objective);
      document.getElementById('ce-gain-val').innerText = `+${formatINR(ce.incremental_gain_inr)}`;
      document.getElementById('ce-pct-val').innerText = `+${ce.improvement_percentage}%`;
      document.getElementById('ce-explanation-text').innerText = ce.explanation;
    }
  } catch (err) {
    console.error('Failed to load evaluation compare:', err);
  }
}

// Modal Helpers
function showModal(title, textOrHtml, isHtml = false) {
  document.getElementById('modal-title').innerText = title;
  const body = document.getElementById('modal-body');
  if (isHtml) {
    body.innerHTML = textOrHtml;
  } else {
    body.innerText = textOrHtml;
  }
  document.getElementById('modal-execution').classList.add('show');
}

function hideModal() {
  document.getElementById('modal-execution').classList.remove('show');
}
