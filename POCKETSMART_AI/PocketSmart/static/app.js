const $ = s => document.querySelector(s);
const inr = n => '₹' + Number(n || 0).toLocaleString('en-IN', {maximumFractionDigits: 0});
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const errText = d => { const x = d && d.detail; return Array.isArray(x) ? x.map(e => e.msg).join('; ') : (x || 'Something went wrong'); };

async function api(url, opts) {
  const r = await fetch(url, opts);
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (r.status === 401 && url !== '/token') { location.href = '/login'; throw new Error('Please log in again'); }
  if (!r.ok) throw new Error(errText(d));
  return d;
}

function formJSON(f) {
  const o = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    o[el.name] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? +el.value : (el.value.trim() || null);
  }
  return o;
}

// ---------- renderers ----------
const links = o => Object.entries(o || {}).map(([k, u]) => `<a class="chip" target="_blank" rel="noopener" href="${esc(u)}">${esc(k)}</a>`).join('');
const tips = (list, title) => list && list.length ? `<section class="card"><h3>${title}</h3><ul>${list.map(t => `<li>${esc(t)}</li>`).join('')}</ul></section>` : '';
const summary = d => `<div class="summary"><span>Total budget <b>${inr(d.total_budget)}</b></span><span>Remaining <b class="${d.remaining_budget < 0 ? 'bad' : 'good'}">${inr(d.remaining_budget)}</b></span></div>` +
  (d.notice ? `<p class="notice">${esc(d.notice)}</p>` : '');

function renderBreakdown(d) {
  const cats = (d.budget_breakdown || []).map(c => `<section class="card"><h3>${esc(c.category.replace(/_/g, ' '))} <small>Allocation ${inr(c.allocation)}</small></h3>
    <table><tr><th>Item</th><th>Unit price</th><th>Qty</th><th>Shop</th></tr>${c.items.map(i => `<tr><td><b>${esc(i.name)}</b><br><small>${esc(i.description)}</small></td><td>${inr(i.estimated_price)}</td><td>${i.quantity}</td><td>${links(i.shopping_links)}</td></tr>`).join('')}</table></section>`).join('');
  const venues = (d.venue_suggestions || []).length ? `<section class="card"><h3>Venue suggestions</h3>${d.venue_suggestions.map(v => `<p><b>${esc(v.name)}</b> (${esc(v.type)}, up to ${esc(v.capacity)} guests) · ${inr(v.estimated_cost)}<br>${links(v.shopping_links)}</p>`).join('')}</section>` : '';
  return summary(d) + cats + venues + tips(d.additional_suggestions, 'Additional suggestions');
}

function renderJewelry(d) {
  const o = d.outfit_analysis;
  const outfit = o ? `<section class="card"><h3>Outfit analysis</h3><p>Colors: <b>${esc([].concat(o.colors || []).join(', '))}</b> · Style: <b>${esc(o.style)}</b> · Formality: <b>${esc(o.formality)}</b></p></section>` : '';
  const items = (d.jewelry_recommendations || []).map(i => `<section class="card"><h3>${esc(i.item_type)} <small>${inr(i.estimated_price)}</small></h3><p>${esc(i.description)}</p><p><small>Style: ${esc(i.style)}</small></p>${links(i.shopping_links)}</section>`).join('');
  return summary(d) + outfit + items + tips(d.styling_tips, 'Styling tips');
}

const render = (type, d) => type === 'jewelry' ? renderJewelry(d) : renderBreakdown(d);

// ---------- planner forms ----------
async function runPlanner(url, opts, type) {
  const out = $('#result'), btn = $('button[type=submit]');
  btn.disabled = true; btn.textContent = 'Generating...';
  out.innerHTML = '<p class="loading">Building your plan. This can take up to 20 seconds.</p>';
  try {
    out.innerHTML = render(type, await api(url, opts));
    out.scrollIntoView({behavior: 'smooth'});
  } catch (e) {
    out.innerHTML = `<p class="notice err">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false; btn.textContent = btn.dataset.label;
  }
}

function wirePlanner(url, type, multipart) {
  $('#f').addEventListener('submit', e => {
    e.preventDefault();
    const f = e.target;
    runPlanner(url, multipart ? {method: 'POST', body: new FormData(f)}
      : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(formJSON(f))}, type);
  });
}

// ---------- history ----------
const TYPES = {home: '🏠 Home interior', party: '🎉 Party planning', jewelry: '💎 Jewelry'};
function histLine(h) {
  const i = h.input || {};
  if (h.type === 'home') return `Lights ${i.num_lights}, fans ${i.num_fans}, furniture ${i.num_furniture}, dining tables ${i.num_dining_tables}`;
  if (h.type === 'party') return `${esc(i.party_type)}, ${i.num_guests} guests`;
  return `${esc(i.occasion)}${i.image ? ', with outfit image' : ''}`;
}
const histRow = h => `<div class="hist"><div><b>${TYPES[h.type] || esc(h.type)}</b><br><small>${new Date(h.timestamp).toLocaleString()} · Budget ${inr(h.summary.total_budget)} · ${histLine(h)}</small></div>
  <button class="btn-sm" onclick="openDetail('${h.id}')">View details</button></div>`;

async function openDetail(id) {
  try {
    const d = await api('/recommendation-details/' + id);
    $('#detail').innerHTML = render(d.type, d.full_result);
    $('#dlg').showModal();
  } catch (e) { alert(e.message); }
}
