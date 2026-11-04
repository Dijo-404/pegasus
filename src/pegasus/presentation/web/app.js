'use strict';

const $ = (id) => document.getElementById(id);
const state = { config: null, product: null, intent: null, grant: null, order: null, ownerReview: false, sentOrders: new Set() };
const labels = {
  AWAITING_APPROVAL: 'Awaiting approval', AUTHORIZED: 'Authorized', EXECUTING: 'Executing',
  UNCERTAIN: 'Uncertain · reconcile', BLOCKED: 'Blocked', UNPAID: 'Unpaid',
  PAYMENT_DETECTED: 'Payment detected', PAYMENT_CONFIRMED: 'Payment confirmed',
  PENDING_DELIVERY: 'Pending delivery', DELIVERED: 'Delivered', FAILED: 'Failed',
  EXPIRED: 'Expired', AWAITING_PAYMENT: 'Awaiting payment', CONFIRMED: 'Confirmed',
  REDEEMED: 'Redeemed', PAYMENT_CONFLICT: 'Payment conflict',
};

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined && text !== null) el.textContent = String(text);
  if (className) el.className = className;
  return el;
}
function notice(message, type = '') {
  $('notice').textContent = message;
  $('notice').className = `notice ${type}`;
  $('notice').hidden = false;
}
function clearNotice() { $('notice').hidden = true; }
function money(minor, currency = 'USD') {
  if (!Number.isSafeInteger(minor)) return 'Not verified';
  try { return new Intl.NumberFormat('en', { style: 'currency', currency }).format(minor / 100); }
  catch { return `${currency} ${(minor / 100).toFixed(2)}`; }
}
function minorUnits(value) {
  const text = String(value).trim();
  if (!/^\d+(\.\d{1,2})?$/.test(text)) throw new Error('Enter a positive amount with at most two decimal places.');
  const [whole, fraction = ''] = text.split('.');
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  if (!Number.isSafeInteger(minor) || minor <= 0) throw new Error('Enter a valid positive spending limit.');
  return minor;
}
function taz(zats) {
  if (!Number.isSafeInteger(zats) || zats < 0) return '—';
  const whole = Math.floor(zats / 100000000);
  const fraction = String(zats % 100000000).padStart(8, '0').replace(/0+$/, '');
  return `${whole}${fraction ? `.${fraction}` : ''}`;
}
function tag(status) {
  const el = node('span', labels[status] || status || 'Unknown', 'status-tag');
  if (['DELIVERED', 'CONFIRMED', 'REDEEMED'].includes(status)) el.classList.add('success');
  if (['FAILED', 'BLOCKED', 'UNCERTAIN', 'PAYMENT_CONFLICT', 'EXPIRED'].includes(status)) el.classList.add('danger');
  return el;
}
function setStatus(id, status) {
  const badge = tag(status);
  $(id).className = badge.className;
  $(id).textContent = badge.textContent;
}
function terms(target, rows) {
  const container = $(target);
  container.replaceChildren();
  rows.forEach(([label, value, className]) => {
    if (value === undefined || value === null || value === '') return;
    const row = node('div', null, className);
    row.append(node('dt', label), node('dd', value));
    container.append(row);
  });
}
function showSession() {
  $('owner-token').value = sessionStorage.getItem('pegasus.owner') || '';
  $('agent-token').value = sessionStorage.getItem('pegasus.agent') || '';
  if (!$('session-dialog').open) $('session-dialog').showModal();
}
async function api(path, { method = 'GET', body, owner = false, anonymous = false } = {}) {
  const headers = { Accept: 'application/json' };
  if (!anonymous) {
    const token = owner ? sessionStorage.getItem('pegasus.owner') :
      sessionStorage.getItem('pegasus.owner') || sessionStorage.getItem('pegasus.agent');
    if (!token) {
      showSession();
      throw new Error(owner ? 'Connect an owner session to approve this exact purchase.' : 'Connect a local session to continue.');
    }
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method, headers, credentials: 'same-origin',
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error('The server returned an unreadable response. No result has been assumed.'); }
  if (!response.ok) {
    const error = payload.error || payload.detail || payload;
    const code = typeof error === 'object' ? error.code : '';
    const message = typeof error === 'string' ? error : error.message || 'The request was rejected.';
    if (response.status === 401) showSession();
    throw new Error(`${code ? `${code}: ` : ''}${typeof message === 'string' ? message : 'Check the submitted fields.'}`);
  }
  return payload;
}
async function run(button, task) {
  const el = typeof button === 'string' ? $(button) : button;
  const previous = el ? Array.from(el.childNodes) : [];
  if (el) { el.disabled = true; el.textContent = 'Working…'; }
  clearNotice();
  try { await task(); }
  catch (error) { notice(error instanceof Error ? error.message : 'The operation did not complete.', 'error'); }
  finally { if (el) { el.disabled = false; el.replaceChildren(...previous); } }
}
function switchTab(name) {
  for (const key of ['commerce', 'private']) {
    const selected = key === name;
    $(`${key}-tab`).classList.toggle('selected', selected);
    $(`${key}-tab`).setAttribute('aria-selected', String(selected));
    $(`${key}-panel`).hidden = !selected;
  }
  $('breadcrumb-current').textContent = name === 'commerce' ? 'Commerce' : 'Private resource';
  window.pegasusVisuals?.setZone(name);
  clearNotice();
}
async function loadConfig() {
  try {
    state.config = await api('/api/config', { anonymous: true });
    const c = state.config;
    $('purchase-cap').textContent = money(c.caps?.per_purchase_minor, c.caps?.currency);
    $('daily-cap').textContent = money(c.caps?.per_day_minor, c.caps?.currency);
    $('commerce-status').textContent = c.bitrefill_configured ? 'Configured' : 'Not connected';
    $('commerce-status-note').textContent = c.bitrefill_configured ? 'Live requests enabled' : 'Provider credentials needed';
    $('search-button').disabled = !c.bitrefill_configured;
    $('merchant-name').textContent = c.merchant?.name || 'Pegasus private resource';
    $('resource-price').textContent = taz(c.merchant?.amount_zats);
    $('zcash-status').textContent = c.zcash_configured ? 'Receiving wallet configured. Testnet only.' : 'Connect the local testnet receiving wallet to begin.';
    $('create-private-order').disabled = !c.zcash_configured;
    $('intent-cap').value = Number.isSafeInteger(c.caps?.per_purchase_minor) ? (c.caps.per_purchase_minor / 100).toFixed(2) : '';
    if (c.allowed_countries?.length) {
      $('country').replaceChildren(...c.allowed_countries.map((code) => node('option', code)));
    }
    if (!c.bitrefill_configured && !c.zcash_configured) notice('The workspace is ready. Connect Bitrefill and the testnet receiving wallet in the local server configuration to use live flows.');
  } catch (error) {
    $('commerce-status').textContent = 'Unavailable';
    $('commerce-status-note').textContent = 'Cannot read server configuration';
    $('search-button').disabled = true;
    $('create-private-order').disabled = true;
    notice(error.message, 'error');
  }
}
async function search() {
  const params = new URLSearchParams({ q: $('search-query').value.trim(), country: $('country').value, intent: $('objective').value.trim() });
  const result = await api(`/api/catalog/search?${params}`);
  const products = result.products || [];
  $('result-count').textContent = `${products.length} result${products.length === 1 ? '' : 's'}`;
  $('search-results').replaceChildren();
  if (!products.length) {
    const empty = node('div', null, 'empty-state');
    empty.append(node('h3', 'No matching products.'), node('p', 'Try another product name or a different allowed country.'));
    $('search-results').append(empty);
  }
  products.forEach((product) => {
    const id = product.product_id || product.id;
    if (!id) return;
    const button = node('button', null, 'product-result');
    button.type = 'button';
    const content = node('span', null, 'product-result-content');
    content.append(node('strong', product.name || id), node('small', id));
    button.append(node('span', (product.name || id).charAt(0).toUpperCase(), 'product-initial'), content, node('span', 'Select'));
    button.addEventListener('click', () => run(button, () => selectProduct(id)));
    $('search-results').append(button);
  });
}
function receiptDestination(product) {
  const destination = product.receipt_destination;
  if (!destination || typeof destination !== 'object' || !['email', 'provider_account'].includes(destination.mode)) {
    throw new Error('The provider receipt destination could not be verified.');
  }
  if (destination.mode === 'provider_account' && !/^sha256:[a-f0-9]{64}$/.test(destination.account_reference || '')) {
    throw new Error('The connected Bitrefill account could not be verified.');
  }
  return destination;
}
async function selectProduct(id) {
  const product = await api(`/api/catalog/products/${encodeURIComponent(id)}`);
  const destination = receiptDestination(product);
  const accountReceipt = destination.mode === 'provider_account';
  state.product = product;
  state.intent = null;
  state.grant = null;
  $('review-empty').hidden = true;
  $('intent-review').hidden = true;
  $('proposal-form').hidden = false;
  $('product-name').textContent = product.name || product.product_id;
  $('product-id').textContent = product.product_id;
  $('package').replaceChildren();
  (product.packages || []).forEach((pkg) => {
    const option = node('option', `${pkg.package_value} · ${pkg.payment_price} ${pkg.payment_currency}`);
    option.value = pkg.package_value;
    $('package').append(option);
  });
  $('payment-method').replaceChildren();
  (product.payment_methods || []).filter((method) => method !== 'balance').forEach((method) => {
    const option = node('option', method);
    option.value = method;
    $('payment-method').append(option);
  });
  const recipientType = product.recipient_type || 'none';
  $('recipient-label').textContent = recipientType === 'phone_number' ? 'Team phone · country code, no + (e.g. 91…)' : `Recipient · ${recipientType}`;
  $('recipient').hidden = $('recipient-label').hidden = recipientType === 'none';
  $('recipient').required = recipientType !== 'none';
  $('recipient').value = '';
  $('email').hidden = $('email-label').hidden = accountReceipt;
  $('email').disabled = accountReceipt;
  $('email').required = !accountReceipt;
  $('account-receipt').hidden = !accountReceipt;
  if (accountReceipt) $('email').value = '';
  if (!product.in_stock) notice('This product is currently out of stock. The gateway will refuse a purchase.', 'error');
  else if (!$('package').options.length || !$('payment-method').options.length) notice('This product has no verified denomination or supported manual payment method.', 'error');
}
async function propose() {
  if (!state.product) throw new Error('Select a live product first.');
  const destination = receiptDestination(state.product);
  const accountReceipt = destination.mode === 'provider_account';
  const intent = await api('/api/intents', { method: 'POST', body: {
    product_id: state.product.product_id, package_value: $('package').value,
    country: $('country').value, recipient: $('recipient').hidden ? '' : $('recipient').value.trim(),
    email: accountReceipt ? '' : $('email').value.trim(), payment_method: $('payment-method').value,
    receipt_mode: accountReceipt ? 'provider_account' : 'email',
    receipt_account_reference: accountReceipt ? destination.account_reference : null,
    max_total_minor: minorUnits($('intent-cap').value),
  } });
  state.grant = null;
  renderIntent(intent);
  await loadHistory();
}
function renderIntent(intent) {
  state.intent = intent;
  state.ownerReview = Boolean(sessionStorage.getItem('pegasus.owner')) && intent.action?.email !== '[owner only]';
  $('review-empty').hidden = true;
  $('proposal-form').hidden = true;
  $('intent-review').hidden = false;
  const action = intent.action || {};
  const invoice = intent.invoice || {};
  setStatus('intent-status', intent.status);
  terms('intent-terms', [
    ['Product', action.product_id], ['Denomination', action.package_value],
    ['Quantity', action.quantity ?? 1], ['Country', action.country],
    ['Recipient', action.recipient || 'No recipient required'],
    ['Receipt destination', action.receipt_mode === 'provider_account' ? 'Connected Bitrefill account' : action.email],
    ['Account reference', action.receipt_mode === 'provider_account' ? action.receipt_account_reference : null],
    ['Payment method', action.payment_method], ['Your approved maximum', money(action.max_total_minor ?? intent.max_total_minor, action.currency)],
    ['Provider quote', money(action.total_minor, action.currency), 'total'],
    ['Invoice', invoice.invoice_id], ['Provider invoice status', invoice.status],
  ]);
  $('intent-digest').textContent = intent.digest ? `${intent.digest.slice(0, 14)}…` : 'Unavailable';
  $('intent-digest').title = intent.digest || '';
  $('intent-expiry').textContent = intent.expires_at ? `Quote expires ${new Date(typeof intent.expires_at === 'number' ? intent.expires_at * 1000 : intent.expires_at).toLocaleTimeString()}. Approval is bound to the fingerprint above.` : 'Approval is bound to this exact intent.';
  $('approve-button').hidden = intent.status !== 'AWAITING_APPROVAL';
  $('execute-button').hidden = !(intent.status === 'AUTHORIZED' && state.grant);
  $('refresh-button').hidden = !invoice.invoice_id;
  $('payment-link').hidden = true;
  if (invoice.payment_link && !['BLOCKED', 'FAILED', 'UNCERTAIN', 'EXPIRED', 'DELIVERED'].includes(intent.status)) {
    try {
      const link = new URL(invoice.payment_link);
      if (link.protocol === 'https:' && (link.hostname === 'bitrefill.com' || link.hostname.endsWith('.bitrefill.com'))) {
        $('payment-link').href = link.href;
        $('payment-link').hidden = false;
      }
    } catch { /* An invalid provider URL is never made clickable. */ }
  }
  const explanations = {
    AWAITING_APPROVAL: 'No invoice exists yet. The owner must approve these exact terms.',
    AUTHORIZED: state.grant ? 'One execution is authorized. The gateway rechecks price and caps before creating an invoice.' : 'The execution grant is no longer in this page memory. Use the originating client or create a new intent; no second approval is assumed.',
    UNCERTAIN: 'The provider outcome is uncertain. No automatic retry is made. Reconcile with the operator before another purchase.',
    UNPAID: 'Invoice created; payment is still outstanding. Opening checkout does not mean payment or delivery.',
    PAYMENT_DETECTED: 'The provider sees payment. Delivery has not been confirmed.',
    PAYMENT_CONFIRMED: 'Payment confirmed. Waiting for the provider to deliver every order.',
    PENDING_DELIVERY: 'The provider is processing delivery. An invoice marked complete alone is not delivery.',
    DELIVERED: 'The provider reports every order delivered. Redemption secrets are not displayed in this workspace.',
    BLOCKED: 'The gateway blocked this invoice for payment. Its payment link is withheld.',
    FAILED: 'The provider reported a failure. No automatic repurchase is made.',
    EXPIRED: 'This intent or invoice expired. Prepare a fresh quote and review it again.',
  };
  $('invoice-note').textContent = explanations[intent.status] || 'Status is shown from the gateway and provider evidence.';
}
async function approve() {
  if (!state.intent) return;
  const previous = state.intent;
  const reviewedAsOwner = state.ownerReview;
  const fresh = await api(`/api/intents/${encodeURIComponent(previous.id)}`, { owner: true });
  renderIntent(fresh);
  if (fresh.action?.email === '[owner only]') throw new Error('An owner credential is required to review and approve the exact recipient and receipt destination.');
  if (!reviewedAsOwner || previous.digest !== fresh.digest || JSON.stringify(previous.action) !== JSON.stringify(fresh.action)) {
    notice('The owner view is now loaded with the exact recipient and receipt destination. Review every term, then click approve again.');
    return;
  }
  const result = await api(`/api/intents/${encodeURIComponent(fresh.id)}/approve`, {
    method: 'POST', owner: true, body: { digest: fresh.digest },
  });
  state.grant = result.grant;
  renderIntent(result.intent || { ...state.intent, status: 'AUTHORIZED' });
  notice('Exact terms approved. The grant can be consumed once.', 'success');
}
async function execute() {
  if (!state.intent || !state.grant) throw new Error('A fresh owner approval is required.');
  const grant = state.grant;
  state.grant = null;
  try {
    const intent = await api(`/api/intents/${encodeURIComponent(state.intent.id)}/execute`, { method: 'POST', body: { grant } });
    renderIntent(intent);
  } catch (error) {
    try { renderIntent(await api(`/api/intents/${encodeURIComponent(state.intent.id)}`)); } catch { /* Keep original error. */ }
    throw error;
  }
  await loadHistory();
  await loadAudit(state.intent.id);
}
async function refresh() {
  if (!state.intent) return;
  renderIntent(await api(`/api/intents/${encodeURIComponent(state.intent.id)}/refresh`, { method: 'POST', body: {} }));
  await loadHistory();
}
async function loadHistory() {
  const result = await api('/api/intents');
  const intents = result.intents || [];
  $('history-body').replaceChildren();
  if (!intents.length) {
    const row = node('tr');
    const cell = node('td', 'No purchase intents yet. Start with a live catalog search.', 'empty-cell');
    cell.colSpan = 5;
    row.append(cell);
    $('history-body').append(row);
  }
  intents.slice().reverse().forEach((intent) => {
    const row = node('tr');
    const action = intent.action || {};
    row.append(node('td', `${intent.id.slice(0, 13)}…`), node('td', action.product_id || '—'), node('td', money(action.total_minor, action.currency)));
    const status = node('td');
    status.append(tag(intent.status));
    const last = node('td');
    const button = node('button', 'View', 'text-button');
    button.type = 'button';
    button.addEventListener('click', () => run(button, async () => {
      if (state.intent?.id !== intent.id) state.grant = null;
      renderIntent(await api(`/api/intents/${encodeURIComponent(intent.id)}`));
      await loadAudit(intent.id);
    }));
    last.append(button);
    row.append(status, last);
    $('history-body').append(row);
  });
}
async function loadAudit(id) {
  const result = await api(`/api/intents/${encodeURIComponent(id)}/audit`);
  const events = result.events || [];
  $('audit-events').replaceChildren();
  $('audit-events').hidden = !events.length;
  events.forEach((event) => {
    const row = node('div', null, 'audit-event');
    const timestamp = event.occurred_at || event.created_at || event.timestamp;
    const time = timestamp ? new Date(typeof timestamp === 'number' ? timestamp * 1000 : timestamp).toLocaleTimeString() : '';
    row.append(node('time', time), node('strong', event.action || event.event || 'Gateway event'), node('span', event.reason_code || event.decision || event.status || ''));
    $('audit-events').append(row);
  });
}
function renderPrivate(order) {
  state.order = order;
  $('private-empty').hidden = true;
  $('private-order').hidden = false;
  setStatus('private-status', order.status);
  $('shield-state').textContent = labels[order.status] || order.status;
  window.pegasusVisuals?.setShield(order.status);
  terms('private-terms', [
    ['Network', 'Zcash testnet'], ['Amount', `${taz(order.amount_zats)} TAZ`],
    ['Receiving address', order.address], ['Encrypted order memo', order.memo],
    ['Confirmations', order.payment?.confirmations], ['Transaction', order.payment?.txid],
    ['Redeem before', order.entitlement_expires_at ? new Date(order.entitlement_expires_at * 1000).toLocaleTimeString() : null],
  ]);
  $('zcash-uri').hidden = true;
  if (typeof order.payment_uri === 'string' && order.payment_uri.startsWith('zcash:utest1')) {
    $('zcash-uri').href = order.payment_uri;
    $('zcash-uri').hidden = false;
  }
  const pending = order.status === 'AWAITING_PAYMENT';
  $('noir-send').hidden = !pending || state.sentOrders.has(order.id);
  $('zcash-uri').hidden = !pending || $('zcash-uri').hidden;
  $('private-refresh').hidden = ['REDEEMED', 'PAYMENT_CONFLICT'].includes(order.status);
  const entitlementExpired = order.entitlement_expires_at && order.entitlement_expires_at * 1000 <= Date.now();
  $('private-redeem').hidden = order.status !== 'CONFIRMED' || entitlementExpired;
  const txid = order.payment?.txid;
  $('private-explorer').hidden = !/^[a-fA-F0-9]{64}$/.test(txid || '');
  if (!$('private-explorer').hidden) $('private-explorer').href = `https://zexplorer.app/testnet/tx/${txid}`;
}
async function createPrivateOrder() {
  $('private-content').hidden = true;
  $('private-content').textContent = '';
  renderPrivate(await api('/api/private/orders', { method: 'POST', body: {} }));
}
async function sendNoir() {
  const order = state.order;
  if (!order || order.status !== 'AWAITING_PAYMENT' || !order.address?.startsWith('utest1')) throw new Error('A testnet payment request is required.');
  if (!Number.isSafeInteger(order.amount_zats) || order.amount_zats <= 0) throw new Error('The payment amount is invalid.');
  const wallet = window.noirwallet;
  if (!wallet?.zcash) throw new Error('Install and unlock the separate Noir testnet extension, then try again.');
  await wallet.zcash.connect();
  if (state.sentOrders.has(order.id)) throw new Error('A wallet send was already attempted for this order. Verify the receiving wallet before any further payment.');
  state.sentOrders.add(order.id);
  $('noir-send').hidden = true;
  const txid = await wallet.zcash.sendTransaction({
    to: order.address, amount: taz(order.amount_zats), memo: order.memo, fundingSource: 'shielded',
  });
  if (typeof txid === 'string' && /^[a-fA-F0-9]{64}$/.test(txid)) {
    $('private-explorer').href = `https://zexplorer.app/testnet/tx/${txid}`;
    $('private-explorer').hidden = false;
  }
  $('noir-send').hidden = true;
  notice('The wallet broadcast the payment. Use “Verify payment” to wait for receiving-wallet confirmation; access remains locked.', 'success');
}
async function refreshPrivate() {
  if (!state.order) return;
  const order = await api(`/api/private/orders/${encodeURIComponent(state.order.id)}/refresh`, { method: 'POST', body: {} });
  renderPrivate(order);
  if (order.status === 'AWAITING_PAYMENT') notice('No matching mined shielded payment has been verified yet. Wait for a block, then check again.');
  if (order.status === 'CONFIRMED') {
    if (order.entitlement_expires_at && order.entitlement_expires_at * 1000 <= Date.now()) notice('Payment is confirmed, but the five-minute access entitlement has expired. Contact the local operator.');
    else notice('The receiving wallet verified the amount, encrypted order memo, shielded pool and confirmations. Redeem access once before the displayed deadline.', 'success');
  }
}
async function redeem() {
  if (!state.order) return;
  const result = await api(`/api/private/orders/${encodeURIComponent(state.order.id)}/redeem`, { method: 'POST', body: {} });
  $('private-content').textContent = typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2);
  $('private-content').hidden = false;
  renderPrivate({ ...state.order, status: 'REDEEMED' });
  notice('Single-use access redeemed. This entitlement cannot be redeemed again.', 'success');
}

$('commerce-tab').addEventListener('click', () => switchTab('commerce'));
$('private-tab').addEventListener('click', () => switchTab('private'));
$('topbar-session').addEventListener('click', showSession);
$('session-close').addEventListener('click', () => $('session-dialog').close());
$('session-form').addEventListener('submit', (event) => {
  event.preventDefault();
  for (const name of ['owner', 'agent']) {
    const token = $(`${name}-token`).value.trim();
    if (token) sessionStorage.setItem(`pegasus.${name}`, token);
    else sessionStorage.removeItem(`pegasus.${name}`);
    $(`${name}-token`).value = '';
  }
  $('session-dialog').close();
  $('topbar-session').textContent = 'Session settings';
  notice('Session connected for this browser tab. Owner approval is still required for each exact purchase.', 'success');
});
$('clear-session').addEventListener('click', () => {
  sessionStorage.removeItem('pegasus.owner');
  sessionStorage.removeItem('pegasus.agent');
  state.grant = null;
  $('owner-token').value = $('agent-token').value = '';
  $('session-dialog').close();
  $('topbar-session').textContent = 'Connect session';
  notice('Local session cleared.');
});
$('search-form').addEventListener('submit', (event) => { event.preventDefault(); run('search-button', search); });
$('proposal-form').addEventListener('submit', (event) => { event.preventDefault(); run(event.submitter, propose); });
$('approve-button').addEventListener('click', () => run('approve-button', approve));
$('execute-button').addEventListener('click', () => run('execute-button', execute));
$('refresh-button').addEventListener('click', () => run('refresh-button', refresh));
$('load-history').addEventListener('click', () => run('load-history', loadHistory));
$('new-intent-button').addEventListener('click', () => {
  state.grant = null;
  state.intent = null;
  $('intent-review').hidden = true;
  $('review-empty').hidden = Boolean(state.product);
  $('proposal-form').hidden = !state.product;
});
$('create-private-order').addEventListener('click', () => run('create-private-order', createPrivateOrder));
$('noir-send').addEventListener('click', () => run('noir-send', sendNoir));
$('private-refresh').addEventListener('click', () => run('private-refresh', refreshPrivate));
$('private-redeem').addEventListener('click', () => run('private-redeem', redeem));
// Local time beside quote and redemption deadlines, which are shown in the same format.
function tickClock() { $('hud-clock').textContent = new Date().toLocaleTimeString(); }
tickClock();
setInterval(tickClock, 1000);
loadConfig();
