'use strict';

const $ = (id) => document.getElementById(id);
const tokenKeys = { owner: 'pegasus.owner', agent: 'pegasus.agent' };
const progressKeys = { intent: 'pegasus.intent', order: 'pegasus.order', sent: 'pegasus.sent' };
const state = {
  config: null, role: null, product: null, intent: null, grant: null, order: null, ownerReview: false,
  sent: {}, pendingSend: null, wallet: null, walletChecked: false, walletEstimate: null, nextActions: {},
};
let sessionGeneration = 0;
const labels = {
  AWAITING_APPROVAL: 'Awaiting approval', AUTHORIZED: 'Authorized', EXECUTING: 'Executing',
  UNCERTAIN: 'Uncertain · reconcile', BLOCKED: 'Blocked', UNPAID: 'Unpaid',
  PAYMENT_DETECTED: 'Payment detected', PAYMENT_CONFIRMED: 'Payment confirmed',
  PENDING_DELIVERY: 'Pending delivery', DELIVERED: 'Delivered', FAILED: 'Failed',
  EXPIRED: 'Expired', AWAITING_PAYMENT: 'Awaiting payment', CONFIRMED: 'Confirmed',
  REDEEMED: 'Redeemed', PAYMENT_CONFLICT: 'Payment conflict',
};
const paidStatuses = ['PAYMENT_DETECTED', 'PAYMENT_CONFIRMED', 'PENDING_DELIVERY', 'DELIVERED'];
const watchedInvoiceStatuses = ['UNPAID', 'PAYMENT_DETECTED', 'PAYMENT_CONFIRMED', 'PENDING_DELIVERY'];
const problemStatuses = ['FAILED', 'BLOCKED', 'UNCERTAIN', 'PAYMENT_CONFLICT', 'EXPIRED'];
const explanations = {
  AWAITING_APPROVAL: 'No invoice exists yet. The owner must approve these exact terms.',
  AUTHORIZED: 'The execution grant is no longer in this page memory. Use the originating client or create a new intent; no second approval is assumed.',
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
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

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
// Wallets report decimal ZEC strings; convert exactly before comparing with zatoshi amounts.
function zatsFrom(value) {
  const text = String(value ?? '').trim();
  if (!/^\d+(\.\d{1,8})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  const zats = Number(whole) * 100000000 + Number(fraction.padEnd(8, '0'));
  return Number.isSafeInteger(zats) ? zats : null;
}
function shortAddress(address) { return address.length > 20 ? `${address.slice(0, 10)}…${address.slice(-6)}` : address; }
function clock(seconds) { return new Date(typeof seconds === 'number' ? seconds * 1000 : seconds).toLocaleTimeString(); }
function tag(status) {
  const el = node('span', labels[status] || status || 'Unknown', 'status-tag');
  if (['DELIVERED', 'CONFIRMED', 'REDEEMED'].includes(status)) el.classList.add('success');
  if (problemStatuses.includes(status)) el.classList.add('danger');
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
function focusOn(id) {
  const el = $(id);
  if (!el || el.hidden) return;
  el.scrollIntoView({ block: 'center', behavior: reducedMotion.matches ? 'auto' : 'smooth' });
  el.focus({ preventScroll: true });
}
function block(id, blocked) {
  if (blocked) $(id).dataset.blocked = 'true';
  else delete $(id).dataset.blocked;
  $(id).disabled = blocked;
}
function remember(key, value) {
  if (value) sessionStorage.setItem(key, value);
  else sessionStorage.removeItem(key);
}
function clearSessionView() {
  sessionGeneration += 1;
  stopWatch('commerce');
  stopWatch('private');
  Object.assign(state, { product: null, intent: null, grant: null, order: null, ownerReview: false, walletEstimate: null });
  for (const id of ['objective', 'search-query', 'recipient', 'email', 'session-token']) $(id).value = '';
  for (const id of ['product-name', 'product-id', 'intent-digest', 'intent-expiry', 'invoice-note', 'commerce-watch',
    'private-watch', 'copy-address', 'copy-amount', 'copy-memo', 'private-content']) $(id).textContent = '';
  $('intent-digest').removeAttribute('title');
  for (const id of ['package', 'payment-method', 'intent-terms', 'private-terms', 'pay-summary', 'audit-events',
    'history-body', 'search-results']) $(id).replaceChildren();
  for (const id of ['proposal-form', 'intent-review', 'private-order', 'private-content', 'private-redeem',
    'private-explorer', 'noir-send', 'other-wallet', 'wallet-funds', 'wallet-faucet', 'audit-events']) $(id).hidden = true;
  $('review-empty').hidden = $('private-empty').hidden = false;
  for (const id of ['payment-link', 'zcash-uri', 'private-explorer']) {
    $(id).hidden = true;
    $(id).removeAttribute('href');
  }
  $('result-count').textContent = 'No search yet';
  $('shield-state').textContent = 'No payment request';
  window.pegasusVisuals?.setShield('idle');
  revealToken(false);
}

// Sign-in: the gateway decides whether a pasted token is the owner or the agent credential.
function storedToken(role) { return sessionStorage.getItem(tokenKeys[role]); }
async function roleFor(token) {
  const response = await fetch('/api/session', {
    headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }, credentials: 'same-origin',
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error('The gateway could not check this token right now. Try again.');
  const { role } = await response.json();
  return role === 'owner' || role === 'agent' ? role : null;
}
function updateSession() {
  state.role = storedToken('owner') ? 'owner' : storedToken('agent') ? 'agent' : null;
  const copy = {
    owner: ['Signed in as owner', 'You can search, prepare and approve purchases, and use the private checkout.', 'Use this token'],
    agent: ['Signed in as agent', 'You can search and prepare purchases and use the private checkout. Add the owner token to approve.', 'Add token'],
  }[state.role] || ['Sign in to Pegasus', 'Paste an access token from your local configuration. The gateway tells you what it allows.', 'Sign in'];
  [$('session-title').textContent, $('session-status').textContent, $('session-submit').textContent] = copy;
  $('clear-session').hidden = !state.role;
  $('topbar-session').textContent = { owner: 'Owner signed in', agent: 'Agent signed in' }[state.role] || 'Sign in';
  renderWorkflows();
}
function showSession(reason = '') {
  $('session-token').value = '';
  revealToken(false);
  $('session-error').hidden = true;
  $('session-reason').textContent = reason;
  $('session-reason').hidden = !reason;
  updateSession();
  if (!$('session-dialog').open) $('session-dialog').showModal();
  $('session-token').focus();
}
function revealToken(visible) {
  $('session-token').type = visible ? 'text' : 'password';
  $('token-reveal').textContent = visible ? 'Hide' : 'Show';
  $('token-reveal').setAttribute('aria-pressed', String(visible));
}
function sessionError(message) {
  $('session-error').textContent = message;
  $('session-error').hidden = false;
  $('session-token').setAttribute('aria-invalid', 'true');
  $('session-token').focus();
}
async function signIn() {
  const generation = sessionGeneration;
  const token = $('session-token').value.trim();
  $('session-error').hidden = true;
  $('session-token').removeAttribute('aria-invalid');
  if (!token) return sessionError('Paste a token to sign in.');
  const role = await roleFor(token);
  if (generation !== sessionGeneration) throw new Error('The session changed. Sign in again if needed.');
  if (!role) return sessionError('This token was not accepted. Copy OWNER_TOKEN or AGENT_TOKEN from your local .env exactly.');
  clearSessionView();
  Object.values(tokenKeys).forEach((key) => sessionStorage.removeItem(key));
  sessionStorage.setItem(tokenKeys[role], token);
  $('session-token').value = '';
  $('session-dialog').close();
  updateSession();
  notice(role === 'owner' ? 'Signed in as owner. You can search, prepare and approve exact purchases.' : 'Signed in as agent. You can search and prepare purchases; approval needs the owner token.', 'success');
  await loadHistory().catch((error) => notice(error.message, 'error'));
  await restoreProgress();
}
function signOut() {
  clearSessionView();
  Object.values(tokenKeys).forEach((key) => sessionStorage.removeItem(key));
  $('session-dialog').close();
  updateSession();
  loadHistory();
  notice('Signed out. Your tokens were removed from this tab.');
}
async function restoreSession() {
  const generation = sessionGeneration;
  for (const role of ['owner', 'agent']) {
    const token = storedToken(role);
    if (!token) continue;
    try {
      const actualRole = await roleFor(token);
      if (generation !== sessionGeneration) return;
      if (actualRole !== role) sessionStorage.removeItem(tokenKeys[role]);
    }
    catch { /* Keep the token while the gateway is unreachable. */ }
    if (generation !== sessionGeneration) return;
  }
  updateSession();
  if (!state.role) return;
  try { await loadHistory(); } catch { /* History stays empty until the next refresh. */ }
  await restoreProgress();
}

async function api(path, { method = 'GET', body, owner = false, anonymous = false } = {}) {
  const generation = sessionGeneration;
  const requireCurrentSession = () => {
    if (!anonymous && generation !== sessionGeneration) throw new Error('The session changed. The earlier response was ignored.');
  };
  const headers = { Accept: 'application/json' };
  const role = owner || storedToken('owner') ? 'owner' : 'agent';
  if (!anonymous) {
    const token = storedToken(role);
    if (!token) {
      showSession(owner ? 'Approving a purchase needs the owner token.' : 'Sign in to continue.');
      throw new Error(owner ? 'Sign in with the owner token to approve this exact purchase.' : 'Sign in to continue.');
    }
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method, headers, credentials: 'same-origin',
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  requireCurrentSession();
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error('The server returned an unreadable response. No result has been assumed.'); }
  requireCurrentSession();
  if (!response.ok) {
    const error = payload.error || payload.detail || payload;
    const code = typeof error === 'object' ? error.code : '';
    const message = typeof error === 'string' ? error : error.message || 'The request was rejected.';
    if (response.status === 401 && !anonymous) {
      clearSessionView();
      sessionStorage.removeItem(tokenKeys[role]);
      updateSession();
      showSession('Your session is no longer valid. Sign in again.');
    }
    if (code === 'OWNER_REQUIRED') showSession('This step needs the owner token.');
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
  finally {
    if (el) {
      el.disabled = 'blocked' in el.dataset;
      if (el.textContent === 'Working…') el.replaceChildren(...previous);
    }
  }
}

// Automatic status checks: visible countdown, paused in background tabs, capped in time.
const watches = {};
function ensureWatch(name, subject, every, limit, task, output) {
  if (watches[name]?.subject === subject) return;
  stopWatch(name);
  const entry = { subject, output, started: Date.now(), next: Date.now() + every, last: null, busy: false, timer: 0 };
  const tick = async () => {
    if (watches[name] !== entry) return;
    if (Date.now() - entry.started > limit) {
      stopWatch(name, `Automatic checks stopped after ${Math.round(limit / 60000)} minutes. Use the check button to look again.`);
      return;
    }
    if (!document.hidden) {
      entry.busy = true;
      try { await task(); entry.last = Date.now(); }
      catch { /* The next check tries again; manual checks still report errors. */ }
      finally { entry.busy = false; }
    }
    if (watches[name] !== entry) return;
    entry.next = Date.now() + every;
    entry.timer = setTimeout(tick, every);
  };
  entry.timer = setTimeout(tick, every);
  watches[name] = entry;
  renderWatches();
}
function stopWatch(name, message = '') {
  const entry = watches[name];
  if (!entry) return;
  clearTimeout(entry.timer);
  delete watches[name];
  $(entry.output).textContent = message;
}
function renderWatches() {
  for (const entry of Object.values(watches)) {
    const seconds = Math.max(0, Math.ceil((entry.next - Date.now()) / 1000));
    const last = entry.last ? `Checked ${new Date(entry.last).toLocaleTimeString()}. ` : '';
    $(entry.output).textContent = entry.busy ? `${last}Checking now…` : `${last}Next automatic check in ${seconds} s.`;
  }
}

// Guided workflow: each rail shows completed steps and one concrete next action.
function markSteps(listId, done, problem) {
  const current = done.indexOf(false);
  $(listId).querySelectorAll('li').forEach((item, index) => {
    const isCurrent = index === current;
    item.classList.toggle('done', current === -1 || index < current);
    item.classList.toggle('problem', isCurrent && problem);
    if (isCurrent) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
}
function setNext(prefix, text, label = null, handler = null) {
  if ($(`${prefix}-next`).textContent !== text) $(`${prefix}-next`).textContent = text;
  const button = $(`${prefix}-next-action`);
  button.hidden = !label;
  if (label) button.textContent = label;
  state.nextActions[prefix] = handler;
}
function renderCommerceFlow() {
  const intent = state.intent;
  const status = intent?.status;
  const invoice = Boolean(intent?.invoice?.invoice_id);
  const done = [
    Boolean(state.role), Boolean(state.product || intent), Boolean(intent),
    invoice || ['AUTHORIZED', 'EXECUTING', 'UNCERTAIN'].includes(status), invoice,
    paidStatuses.includes(status), status === 'DELIVERED',
  ];
  const problem = problemStatuses.includes(status);
  markSteps('commerce-steps', done, problem);
  if (status === 'UNCERTAIN') return setNext('commerce', 'The provider outcome is uncertain. Reconcile this purchase with the operator before taking any further action. No automatic retry is made.');
  if (state.config && !state.config.bitrefill_configured) return setNext('commerce', 'Bitrefill is not connected on this server. Add the provider credentials to the local configuration.');
  if (problem) return setNext('commerce', explanations[status], 'Start another purchase', newIntent);
  switch (done.indexOf(false)) {
    case 0: return setNext('commerce', 'Sign in with the owner token from your local .env to search and approve purchases.', 'Sign in', () => showSession());
    case 1: return setNext('commerce', 'Describe what you need, then search the live Bitrefill catalog.', 'Go to search', () => focusOn($('objective').value.trim() ? 'search-query' : 'objective'));
    case 2: return setNext('commerce', 'Choose the denomination and recipient, set your maximum total, then prepare the intent.', 'Fill in the purchase', () => focusOn('package'));
    case 3: return state.role === 'owner'
      ? setNext('commerce', 'Check every term. Approval binds this exact fingerprint and can be used once.', 'Review and approve', () => focusOn('approve-button'))
      : setNext('commerce', 'Approval needs the owner token. The agent token can only prepare purchases.', 'Sign in as owner', () => showSession('Approving a purchase needs the owner token.'));
    case 4:
      if (status === 'EXECUTING') return setNext('commerce', 'Creating the invoice with Bitrefill…');
      return state.grant
        ? setNext('commerce', 'Approved once. Create the invoice; the gateway rechecks the price and your caps first.', 'Create the invoice', () => focusOn('execute-button'))
        : setNext('commerce', explanations.AUTHORIZED, 'Start another purchase', newIntent);
    case 5: return $('payment-link').hidden
      ? setNext('commerce', 'Pay the invoice with Bitrefill. Pegasus checks the status every 30 seconds.', 'Check status', refresh)
      : setNext('commerce', 'Pay the invoice on Bitrefill\'s page. Pegasus checks the status every 30 seconds.', 'Open payment page', () => $('payment-link').click());
    case 6: return setNext('commerce', 'Payment received. Waiting for Bitrefill to deliver every order.', 'Check now', refresh);
    default: return setNext('commerce', 'Delivered. Codes stay in your Bitrefill account; this workspace never displays them.', 'Start another purchase', newIntent);
  }
}
function renderPrivateFlow() {
  const order = state.order;
  const status = order?.status;
  block('create-private-order', Boolean(state.pendingSend) || !state.config?.zcash_configured);
  const sent = order ? state.sent[order.id] : undefined;
  const expired = status === 'CONFIRMED' && order.entitlement_expires_at && order.entitlement_expires_at * 1000 <= Date.now();
  const done = [
    Boolean(state.role), Boolean(status), Boolean(status) && (Boolean(sent) || status !== 'AWAITING_PAYMENT'),
    ['CONFIRMED', 'REDEEMED'].includes(status), status === 'REDEEMED',
  ];
  markSteps('private-steps', done, status === 'PAYMENT_CONFLICT' || expired);
  if (state.config && !state.config.zcash_configured) return setNext('private', 'The receiving wallet is not configured on this server, so testnet payments are unavailable.');
  if (state.role && state.pendingSend) return setNext('private', 'Your wallet is waiting for you to approve or reject the send. No payment outcome has been assumed. Finish that wallet request before creating another.');
  if (status === 'PAYMENT_CONFLICT') return setNext('private', 'This payment is already linked to another order and cannot unlock access. Contact the operator.', 'Create a new request', createPrivateOrder);
  if (expired) return setNext('private', 'Payment verified, but the five-minute redemption window has closed. Contact the operator.');
  const amount = order ? `${taz(order.amount_zats)} TAZ` : '';
  switch (done.indexOf(false)) {
    case 0: return setNext('private', 'Sign in to create a private payment request.', 'Sign in', () => showSession());
    case 1: return setNext('private', 'Create a payment request. It gets a unique encrypted memo so the merchant can find your payment.', 'Create payment request', createPrivateOrder);
    case 2:
      if (!window.noirwallet?.zcash) return setNext('private', `Send ${amount} from any Zcash testnet wallet with the memo below. Pegasus detects it once it is mined.`, 'Show payment details', () => { $('other-wallet').open = true; focusOn('zcash-uri'); });
      if (!state.wallet) return setNext('private', 'Connect your Noir testnet wallet to pay in one step, or pay from another wallet below.', 'Connect wallet', connectWallet);
      if (!testnetAddress(state.wallet.address)) return setNext('private', 'Your connected wallet is not on testnet. Switch to the [Testnet] Noir Wallet extension.');
      if (Number.isSafeInteger(state.walletEstimate?.max) && state.walletEstimate.max < order.amount_zats) {
        return setNext('private', `Your wallet can send at most ${taz(state.walletEstimate.max)} TAZ after fees. Add testnet TAZ using the faucet link below, then refresh your balance.`, 'Refresh balance', refreshWallet);
      }
      return setNext('private', `Pay ${amount} from your connected wallet. The memo is attached for you.`, `Pay ${amount}`, sendNoir);
    case 3:
      if (sent === true) return setNext('private', 'A wallet send was attempted, but its outcome is unknown. Check your wallet and wait for verification before paying again.', 'Check payment', refreshPrivate);
      return setNext('private', 'Waiting for the payment to be mined and verified. Blocks arrive about every 25 seconds; Pegasus checks every 20 seconds.', 'Check now', refreshPrivate);
    case 4: return setNext('private', `Payment verified. Redeem your single-use access before ${clock(order.entitlement_expires_at)}.`, 'Redeem access', redeem);
    default: return setNext('private', 'Access redeemed. Create a new request to buy again.', 'Create a new request', createPrivateOrder);
  }
}
function renderWorkflows() {
  renderCommerceFlow();
  renderPrivateFlow();
}

function switchTab(name, updateHash = true) {
  for (const key of ['commerce', 'private']) {
    const selected = key === name;
    $(`${key}-tab`).classList.toggle('selected', selected);
    $(`${key}-tab`).setAttribute('aria-selected', String(selected));
    $(`${key}-panel`).hidden = !selected;
  }
  $('breadcrumb-current').textContent = name === 'commerce' ? 'Commerce' : 'Private resource';
  window.pegasusVisuals?.setZone(name);
  if (updateHash) history.replaceState(null, '', name === 'private' ? '#private' : location.pathname);
  clearNotice();
}
async function loadConfig() {
  try {
    state.config = await api('/api/config', { anonymous: true });
    const c = state.config;
    $('gateway-status').textContent = 'Gateway online';
    $('gateway-dot').classList.remove('offline');
    $('purchase-cap').textContent = money(c.caps?.per_purchase_minor, c.caps?.currency);
    $('daily-cap').textContent = money(c.caps?.per_day_minor, c.caps?.currency);
    $('commerce-status').textContent = c.bitrefill_configured ? 'Configured' : 'Not connected';
    $('commerce-status-note').textContent = c.bitrefill_configured ? 'Live requests enabled' : 'Provider credentials needed';
    block('search-button', !c.bitrefill_configured);
    $('merchant-name').textContent = c.merchant?.name || 'Pegasus private resource';
    $('resource-price').textContent = taz(c.merchant?.amount_zats);
    $('zcash-status').textContent = c.zcash_configured ? 'Receiving wallet configured. Testnet only.' : 'The local testnet receiving wallet is not configured.';
    block('create-private-order', !c.zcash_configured);
    $('intent-cap').value = Number.isSafeInteger(c.caps?.per_purchase_minor) ? (c.caps.per_purchase_minor / 100).toFixed(2) : '';
    if (c.allowed_countries?.length) {
      $('country').replaceChildren(...c.allowed_countries.map((code) => node('option', code)));
    }
  } catch (error) {
    $('gateway-status').textContent = 'Gateway unreachable';
    $('gateway-dot').classList.add('offline');
    $('commerce-status').textContent = 'Unavailable';
    $('commerce-status-note').textContent = 'Cannot read server configuration';
    block('search-button', true);
    block('create-private-order', true);
    notice(`${error.message} Reload the page once the gateway is running.`, 'error');
  }
  renderWorkflows();
}

async function search() {
  const params = new URLSearchParams({ q: $('search-query').value.trim(), country: $('country').value, intent: $('objective').value.trim() });
  if (!params.get('intent')) { focusOn('objective'); throw new Error('Describe your buying objective first. It is sent with the search.'); }
  if (!params.get('q')) { focusOn('search-query'); throw new Error('Enter a product name to search for.'); }
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
    button.setAttribute('aria-pressed', 'false');
    const content = node('span', null, 'product-result-content');
    content.append(node('strong', product.name || id), node('small', id));
    button.append(node('span', (product.name || id).charAt(0).toUpperCase(), 'product-initial'), content, node('span', 'Select', 'product-result-action'));
    // Mark the choice after run() has restored the button contents.
    button.addEventListener('click', () => run(button, () => selectProduct(id)).then(() => {
      if (state.product?.product_id !== id) return;
      document.querySelectorAll('.product-result').forEach((other) => {
        const chosen = other === button;
        other.classList.toggle('selected', chosen);
        other.setAttribute('aria-pressed', String(chosen));
        other.querySelector('.product-result-action').textContent = chosen ? 'Selected' : 'Select';
      });
    }));
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
  remember(progressKeys.intent, null);
  stopWatch('commerce');
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
  renderWorkflows();
  $('package').focus();
  if (!product.in_stock) notice('This product is currently out of stock. The gateway will refuse a purchase.', 'error');
  else if (!$('package').options.length || !$('payment-method').options.length) notice('This product has no verified denomination or supported manual payment method.', 'error');
}
async function propose() {
  if (!state.product) throw new Error('Select a live product first.');
  if (!$('proposal-form').reportValidity()) throw new Error('Complete the highlighted fields to prepare the intent.');
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
  $('intent-review').scrollIntoView({ block: 'nearest', behavior: reducedMotion.matches ? 'auto' : 'smooth' });
  await loadHistory();
}
function renderIntent(intent) {
  if (!state.role) return;
  state.intent = intent;
  remember(progressKeys.intent, intent.id);
  state.ownerReview = Boolean(storedToken('owner')) && intent.action?.email !== '[owner only]';
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
  $('intent-expiry').textContent = intent.expires_at ? `Quote expires ${clock(intent.expires_at)}. Approval is bound to the fingerprint above.` : 'Approval is bound to this exact intent.';
  $('approve-button').hidden = intent.status !== 'AWAITING_APPROVAL';
  $('execute-button').hidden = !(intent.status === 'AUTHORIZED' && state.grant);
  $('new-intent-button').hidden = intent.status === 'UNCERTAIN';
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
  $('invoice-note').textContent = intent.status === 'AUTHORIZED' && state.grant
    ? 'One execution is authorized. The gateway rechecks price and caps before creating an invoice.'
    : explanations[intent.status] || 'Status is shown from the gateway and provider evidence.';
  if (state.role && watchedInvoiceStatuses.includes(intent.status)) ensureWatch('commerce', intent.id, 30000, 600000, () => refresh({ quiet: true }), 'commerce-watch');
  else stopWatch('commerce');
  renderWorkflows();
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
  focusOn('execute-button');
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
let commerceRefresh = null;
let commerceRefreshGeneration = -1;
function refresh({ quiet = false } = {}) {
  const generation = sessionGeneration;
  if (commerceRefreshGeneration !== generation) {
    commerceRefresh = null;
    commerceRefreshGeneration = generation;
  }
  commerceRefresh ??= (async () => {
    if (!state.intent) return;
    const intentId = state.intent.id;
    const before = state.intent.status;
    const intent = await api(`/api/intents/${encodeURIComponent(intentId)}/refresh`, { method: 'POST', body: {} });
    if (!state.role || state.intent?.id !== intentId) return;
    renderIntent(intent);
    const label = labels[intent.status] || intent.status;
    if (intent.status !== before) notice(`Bitrefill status: ${label}.`, intent.status === 'DELIVERED' ? 'success' : problemStatuses.includes(intent.status) ? 'error' : '');
    else if (!quiet) notice(`No change yet. Bitrefill still reports ${label.toLowerCase()}.`);
    await loadHistory();
  })().finally(() => { if (commerceRefreshGeneration === generation) commerceRefresh = null; });
  return commerceRefresh;
}
function newIntent() {
  if (state.intent?.status === 'UNCERTAIN') {
    notice('Reconcile this uncertain purchase with the operator before replacing it. No result has been assumed.', 'error');
    return;
  }
  state.grant = null;
  state.intent = null;
  remember(progressKeys.intent, null);
  stopWatch('commerce');
  $('intent-review').hidden = true;
  $('review-empty').hidden = Boolean(state.product);
  $('proposal-form').hidden = !state.product;
  renderWorkflows();
  focusOn(state.product ? 'package' : 'objective');
}
async function loadHistory() {
  $('history-body').replaceChildren();
  const emptyRow = (text) => {
    const row = node('tr');
    const cell = node('td', text, 'empty-cell');
    cell.colSpan = 5;
    row.append(cell);
    $('history-body').append(row);
  };
  if (!state.role) return emptyRow('Sign in to see your purchase history.');
  const result = await api('/api/intents');
  const intents = result.intents || [];
  $('history-body').replaceChildren();
  if (!intents.length) emptyRow('No purchase intents yet. Start with a live catalog search.');
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
      $('review-title').scrollIntoView({ block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth' });
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
    row.append(node('time', timestamp ? clock(timestamp) : ''), node('strong', event.action || event.event || 'Gateway event'), node('span', event.reason_code || event.decision || event.status || ''));
    $('audit-events').append(row);
  });
}

// Wallet: the user's own Noir testnet extension. Pegasus never holds keys or signs payments.
const testnetAddress = (value) => typeof value === 'string' && /^(utest1|ztestsapling)/.test(value);
function noir() { return window.noirwallet?.zcash || null; }
function walletAddress(result) {
  const values = [];
  const visit = (value) => {
    if (typeof value === 'string') values.push(value);
    else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') ['shielded', 'unified', 'address', 'sapling'].forEach((key) => visit(value[key]));
  };
  visit(result);
  visit(result?.accounts);
  return values.find(testnetAddress) || values.find((value) => /^(u1|zs1)/.test(value)) || null;
}
async function detectWallet() {
  for (let attempt = 0; attempt < 10 && !noir(); attempt++) await new Promise((resolve) => setTimeout(resolve, 300));
  const wallet = noir();
  if (wallet) {
    try { const address = walletAddress(await wallet.getAccounts()); if (address) state.wallet = { address }; }
    catch { /* The wallet stays disconnected until the user connects it. */ }
    try {
      wallet.on?.('accountsChanged', (accounts) => {
        const address = walletAddress(accounts);
        state.wallet = address ? { address } : null;
        refreshWallet();
      });
    } catch { /* Account changes are picked up on the next connect. */ }
  }
  state.walletChecked = true;
  await refreshWallet();
}
async function connectWallet() {
  const wallet = noir();
  if (!wallet) throw new Error('Install and unlock the [Testnet] Noir Wallet extension, or pay from another wallet.');
  const address = walletAddress(await wallet.connect());
  if (!address) throw new Error('The wallet did not share a shielded address. Unlock it and try again.');
  state.wallet = { address };
  await refreshWallet();
  if (testnetAddress(address)) notice('Wallet connected. Pegasus can ask it to send payments; you approve every send in the wallet.', 'success');
  else notice('This wallet is not on testnet. Switch to the [Testnet] Noir Wallet extension.', 'error');
}
async function refreshWallet() {
  const generation = sessionGeneration;
  const wallet = noir();
  const order = state.order;
  const connected = state.wallet;
  const current = () => generation === sessionGeneration && state.wallet === connected && state.order?.id === order?.id;
  state.walletEstimate = null;
  if (wallet && connected) {
    try {
      const balance = await wallet.getBalance();
      if (!current()) return;
      connected.balance = zatsFrom(balance?.shielded);
      connected.synced = balance?.synced !== false;
    } catch {
      if (!current()) return;
      connected.balance = null;
    }
    if (order?.status === 'AWAITING_PAYMENT' && testnetAddress(order.address) && testnetAddress(connected.address)) {
      try {
        const estimate = await wallet.getMaxTransfer({ to: order.address, memo: order.memo, fundingSource: 'shielded' });
        if (!current()) return;
        state.walletEstimate = { max: zatsFrom(estimate?.maxAmount), fee: zatsFrom(estimate?.fee) };
      } catch { /* The wallet still shows its own fee when sending. */ }
    }
  }
  if (!current()) return;
  renderWallet();
}
function renderWallet() {
  const wallet = noir();
  const connected = state.wallet;
  let status = 'Not installed';
  let tone = '';
  let detail = 'Pay in one step with the [Testnet] Noir Wallet browser extension, or pay from any Zcash testnet wallet after you create a request.';
  if (!state.walletChecked) [status, detail] = ['Checking…', 'Looking for the Noir testnet extension…'];
  else if (wallet && !connected) [status, detail] = ['Not connected', 'Connect to pay in one step. Pegasus never sees your keys; the wallet asks you to approve every send.'];
  else if (connected && !testnetAddress(connected.address)) [status, tone, detail] = ['Wrong network', 'danger', `${shortAddress(connected.address)} is not a testnet address. Switch to the [Testnet] Noir Wallet extension.`];
  else if (connected) {
    const balance = Number.isSafeInteger(connected.balance) ? `${taz(connected.balance)} TAZ shielded${connected.synced === false ? ', still syncing' : ''}` : 'Balance unavailable';
    [status, tone, detail] = ['Connected', 'success', `${shortAddress(connected.address)}. ${balance}.`];
  }
  $('wallet-state').textContent = status;
  $('wallet-state').className = `status-tag ${tone}`;
  $('wallet-detail').textContent = detail;
  $('wallet-connect').hidden = !wallet;
  $('wallet-connect').textContent = connected ? 'Refresh balance' : 'Connect Noir wallet';
  $('wallet-install').hidden = !state.walletChecked || Boolean(wallet);
  renderPaySummary();
  renderWorkflows();
}
function renderPaySummary() {
  const order = state.order;
  if (!order || order.status !== 'AWAITING_PAYMENT') return;
  const estimate = state.walletEstimate;
  terms('pay-summary', [
    ['Memo', 'Attached automatically'],
    ['From', state.wallet ? shortAddress(state.wallet.address) : 'Your wallet'],
    ['Network fee', Number.isSafeInteger(estimate?.fee) ? `About ${taz(estimate.fee)} TAZ` : 'Shown by your wallet'],
    ['You pay', `${taz(order.amount_zats)} TAZ`, 'total'],
  ]);
  const short = Number.isSafeInteger(estimate?.max) && estimate.max < order.amount_zats;
  $('wallet-funds').hidden = $('wallet-faucet').hidden = !short;
  if (short) $('wallet-funds').textContent = `Your wallet can send at most ${taz(estimate.max)} TAZ after fees. Add testnet TAZ before paying.`;
  $('noir-send').textContent = state.wallet ? `Pay ${taz(order.amount_zats)} TAZ` : 'Connect and pay with Noir';
  block('noir-send', short || Boolean(state.wallet && !testnetAddress(state.wallet.address)));
}

function markSent(orderId, value) {
  state.sent[orderId] = value;
  remember(progressKeys.sent, JSON.stringify(state.sent));
}
function renderPrivate(order) {
  if (!state.role) return;
  state.order = order;
  remember(progressKeys.order, order.id);
  $('private-empty').hidden = true;
  $('private-order').hidden = false;
  setStatus('private-status', order.status);
  $('shield-state').textContent = labels[order.status] || order.status;
  window.pegasusVisuals?.setShield(order.status);
  terms('private-terms', [
    ['Network', 'Zcash testnet'], ['Amount', `${taz(order.amount_zats)} TAZ`],
    ['Receiving address', order.address], ['Encrypted order memo', order.memo],
    ['Confirmations', order.payment?.confirmations], ['Transaction', order.payment?.txid],
    ['Redeem before', order.entitlement_expires_at ? clock(order.entitlement_expires_at) : null],
  ]);
  $('copy-address').textContent = order.address || '';
  $('copy-amount').textContent = taz(order.amount_zats);
  $('copy-memo').textContent = order.memo || '';
  $('zcash-uri').hidden = true;
  if (typeof order.payment_uri === 'string' && order.payment_uri.startsWith('zcash:utest1')) {
    $('zcash-uri').href = order.payment_uri;
    $('zcash-uri').hidden = false;
  }
  const pending = order.status === 'AWAITING_PAYMENT';
  const sent = state.sent[order.id];
  $('pay-summary').hidden = !pending || Boolean(sent);
  $('noir-send').hidden = !pending || Boolean(sent) || !noir();
  $('noir-send').nextElementSibling.hidden = $('noir-send').hidden;
  $('other-wallet').hidden = !pending || Boolean(sent);
  if (!pending) $('wallet-funds').hidden = $('wallet-faucet').hidden = true;
  $('private-refresh').hidden = ['REDEEMED', 'PAYMENT_CONFLICT'].includes(order.status);
  const entitlementExpired = order.entitlement_expires_at && order.entitlement_expires_at * 1000 <= Date.now();
  $('private-redeem').hidden = order.status !== 'CONFIRMED' || entitlementExpired;
  const txid = order.payment?.txid || (typeof sent === 'string' ? sent : '');
  $('private-explorer').hidden = !/^[a-fA-F0-9]{64}$/.test(txid);
  if (!$('private-explorer').hidden) $('private-explorer').href = `https://zexplorer.app/testnet/tx/${txid}`;
  if (state.role && pending) ensureWatch('private', order.id, 20000, 900000, () => refreshPrivate({ quiet: true }), 'private-watch');
  else stopWatch('private');
  renderPaySummary();
  renderWorkflows();
}
async function createPrivateOrder() {
  if (state.pendingSend) throw new Error('A wallet approval request is still pending. Finish it before creating another payment request.');
  $('private-content').hidden = true;
  $('private-content').textContent = '';
  renderPrivate(await api('/api/private/orders', { method: 'POST', body: {} }));
  $('other-wallet').open = !noir();
  $('private-steps').scrollIntoView({ block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth' });
  await refreshWallet();
}
async function sendNoir() {
  const generation = sessionGeneration;
  const order = state.order;
  if (!state.role) throw new Error('Sign in before paying for this request.');
  if (state.pendingSend) throw new Error('A wallet approval request is already pending. Finish it before attempting another send.');
  if (!order || order.status !== 'AWAITING_PAYMENT' || !testnetAddress(order.address)) throw new Error('Create a testnet payment request first.');
  if (!Number.isSafeInteger(order.amount_zats) || order.amount_zats <= 0) throw new Error('The payment amount is invalid.');
  const wallet = noir();
  if (!wallet) throw new Error('Install and unlock the [Testnet] Noir Wallet extension, or pay from another wallet.');
  if (!state.wallet) await connectWallet();
  if (generation !== sessionGeneration || state.order?.id !== order.id) throw new Error('The session or payment request changed. Review the current request before paying.');
  if (!testnetAddress(state.wallet?.address)) throw new Error('Your connected wallet is not on testnet. Switch to the [Testnet] Noir Wallet extension.');
  if (state.sent[order.id]) throw new Error('A wallet send was already attempted for this order. Wait for verification before any further payment.');
  if (Number.isSafeInteger(state.walletEstimate?.max) && state.walletEstimate.max < order.amount_zats) throw new Error('Your wallet does not have enough shielded TAZ for this payment and its fee.');
  markSent(order.id, true);
  state.pendingSend = order.id;
  renderPrivate(order);
  let txid;
  try {
    txid = await wallet.sendTransaction({ to: order.address, amount: taz(order.amount_zats), memo: order.memo, fundingSource: 'shielded' });
  } catch {
    // A wallet error does not prove that no transaction was broadcast.
  } finally {
    state.pendingSend = null;
  }
  const validTxid = typeof txid === 'string' && /^[a-fA-F0-9]{64}$/.test(txid);
  if (validTxid) markSent(order.id, txid);
  if (generation !== sessionGeneration || !state.role || state.order?.id !== order.id) {
    renderWorkflows();
    return;
  }
  renderPrivate(order);
  if (!validTxid) throw new Error('The wallet did not return a valid transaction ID, so the send outcome is unknown. Its reservation remains. Check your wallet and wait for verification before paying again.');
  notice('Payment sent. Access stays locked until the receiving wallet sees it mined; Pegasus checks automatically.', 'success');
  refreshWallet();
}
let privateRefresh = null;
let privateRefreshGeneration = -1;
function refreshPrivate({ quiet = false } = {}) {
  const generation = sessionGeneration;
  if (privateRefreshGeneration !== generation) {
    privateRefresh = null;
    privateRefreshGeneration = generation;
  }
  privateRefresh ??= (async () => {
    if (!state.order) return;
    const orderId = state.order.id;
    const before = state.order.status;
    const order = await api(`/api/private/orders/${encodeURIComponent(orderId)}/refresh`, { method: 'POST', body: {} });
    if (!state.role || state.order?.id !== orderId) return;
    renderPrivate(order);
    if (order.status === 'AWAITING_PAYMENT' && !quiet) notice('No mined payment with this memo yet. Blocks arrive about every 25 seconds; Pegasus keeps checking.');
    if (order.status === 'CONFIRMED' && (before !== 'CONFIRMED' || !quiet)) {
      if (order.entitlement_expires_at && order.entitlement_expires_at * 1000 <= Date.now()) notice('Payment is confirmed, but the five-minute access entitlement has expired. Contact the local operator.', 'error');
      else notice(`Payment verified: amount, memo, shielded pool and confirmations all match. Redeem access before ${clock(order.entitlement_expires_at)}.`, 'success');
    }
  })().finally(() => { if (privateRefreshGeneration === generation) privateRefresh = null; });
  return privateRefresh;
}
async function redeem() {
  if (!state.order) return;
  const result = await api(`/api/private/orders/${encodeURIComponent(state.order.id)}/redeem`, { method: 'POST', body: {} });
  $('private-content').textContent = typeof result.content === 'string' ? result.content : JSON.stringify(result.content, null, 2);
  $('private-content').hidden = false;
  renderPrivate({ ...state.order, status: 'REDEEMED' });
  notice('Single-use access redeemed. This entitlement cannot be redeemed again.', 'success');
}
async function restoreProgress() {
  const generation = sessionGeneration;
  if (!state.role) return;
  const intentId = sessionStorage.getItem(progressKeys.intent);
  if (intentId && !state.intent) {
    try { renderIntent(await api(`/api/intents/${encodeURIComponent(intentId)}`)); }
    catch { if (generation === sessionGeneration) remember(progressKeys.intent, null); }
  }
  if (generation !== sessionGeneration || !state.role) return;
  const orderId = sessionStorage.getItem(progressKeys.order);
  if (orderId && !state.order) {
    state.order = { id: orderId };
    try { await refreshPrivate({ quiet: true }); }
    catch {
      if (generation === sessionGeneration) { state.order = null; remember(progressKeys.order, null); }
    }
  }
}
async function copyValue(id, button) {
  const text = $(id).textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = 'Copy'; }, 1600);
  } catch {
    getSelection().selectAllChildren($(id));
    notice('Copying is blocked in this browser. The value is selected; copy it with your keyboard.');
  }
}
function tickClock() {
  $('hud-clock').textContent = new Date().toLocaleTimeString();
  renderWatches();
}

try { state.sent = JSON.parse(sessionStorage.getItem(progressKeys.sent) || '{}') || {}; }
catch { state.sent = {}; }
$('commerce-tab').addEventListener('click', () => switchTab('commerce'));
$('private-tab').addEventListener('click', () => switchTab('private'));
window.addEventListener('hashchange', () => switchTab(location.hash === '#private' ? 'private' : 'commerce', false));
$('topbar-session').addEventListener('click', () => showSession());
$('session-close').addEventListener('click', () => $('session-dialog').close());
$('session-dialog').addEventListener('close', () => revealToken(false));
$('token-reveal').addEventListener('click', () => revealToken($('session-token').type === 'password'));
$('session-form').addEventListener('submit', (event) => {
  event.preventDefault();
  run('session-submit', async () => {
    try { await signIn(); }
    catch (error) { sessionError(error instanceof Error ? error.message : 'Sign in did not complete.'); }
  }).then(updateSession);
});
$('clear-session').addEventListener('click', signOut);
$('commerce-next-action').addEventListener('click', (event) => run(event.currentTarget, () => state.nextActions.commerce?.()));
$('private-next-action').addEventListener('click', (event) => run(event.currentTarget, () => state.nextActions.private?.()));
$('search-form').addEventListener('submit', (event) => { event.preventDefault(); run('search-button', search); });
$('proposal-form').addEventListener('submit', (event) => { event.preventDefault(); run(event.submitter, propose); });
$('approve-button').addEventListener('click', () => run('approve-button', approve));
$('execute-button').addEventListener('click', () => run('execute-button', execute));
$('refresh-button').addEventListener('click', () => run('refresh-button', () => refresh()));
$('load-history').addEventListener('click', () => run('load-history', loadHistory));
$('new-intent-button').addEventListener('click', newIntent);
$('create-private-order').addEventListener('click', () => run('create-private-order', createPrivateOrder));
$('wallet-connect').addEventListener('click', () => run('wallet-connect', () => (state.wallet ? refreshWallet() : connectWallet())));
$('noir-send').addEventListener('click', () => run('noir-send', sendNoir));
$('private-refresh').addEventListener('click', () => run('private-refresh', () => refreshPrivate()));
$('private-redeem').addEventListener('click', () => run('private-redeem', redeem));
document.querySelectorAll('[data-copy]').forEach((button) => button.addEventListener('click', () => copyValue(button.dataset.copy, button)));
switchTab(location.hash === '#private' ? 'private' : 'commerce', false);
tickClock();
setInterval(tickClock, 1000);
updateSession();
loadConfig();
restoreSession();
detectWallet();
