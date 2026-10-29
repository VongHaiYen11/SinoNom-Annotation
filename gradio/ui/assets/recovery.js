// Only completed local manipulations are checkpointed; pointer previews are not.
const draftRecovery = (() => {
  const key = 'vietnamica-drafts-v1';
  let metadata = null, records = {}, failed = false, restoring = false;
  const notice = message => {
    const host = document.querySelector('#draft-recovery-status');
    const status = host?.querySelector?.('[role="status"]') || host;
    if (status) status.textContent = message;
  };
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) {
      records = JSON.parse(raw);
      if (!records || typeof records !== 'object' || Array.isArray(records)) throw Error();
    }
  } catch (_) {
    records = {}; failed = true;
  }
  const recordKey = meta => JSON.stringify([meta.application, meta.tab, meta.image, meta.step]);
  const matches = (record, meta) => record?.metadata?.version === meta.version
    && record.metadata.application === meta.application && record.metadata.tab === meta.tab
    && record.metadata.image === meta.image && record.metadata.step === meta.step
    && record.metadata.generation === meta.generation;
  const persist = () => {
    try { sessionStorage.setItem(key, JSON.stringify(records)); }
    catch (_) { failed = true; notice('Draft recovery unavailable: browser storage could not be written.'); }
  };
  const read = meta => {
    if (!meta) return null;
    const record = records[recordKey(meta)];
    if (!matches(record, meta)) return null;
    return record;
  };
  const write = (meta, update) => {
    if (!meta?.image || restoring) return;
    records[recordKey(meta)] = {...(read(meta) || {}), metadata: meta, ...update};
    persist();
  };
  const uiSelectors = ['content-value', 'content-draft-bridge', 'crop-coordinates'];
  const captureUI = () => {
    if (!metadata?.image || restoring) return;
    const ui = {...(read(metadata)?.ui || {})};
    for (const id of uiSelectors) {
      const input = document.querySelector(`#${id} input, #${id} textarea`);
      if (input) ui[id] = input.value;
    }
    const current = read(metadata);
    const typing = {...(current?.typing || {})};
    if (metadata.step === 2 && current?.section && 'content-value' in ui) {
      typing[current.section] = ui['content-value'];
    }
    write(metadata, {ui, typing});
  };
  // Gradio HTML scripts can remount: keep exactly one set of global listeners.
  window.vietnamicaRecoveryController?.abort();
  const controller = new AbortController();
  window.vietnamicaRecoveryController = controller;
  window.vietnamicaRecoveryChannel?.close();
  try { if (typeof BroadcastChannel !== 'undefined') {
    const channel = new BroadcastChannel('vietnamica-tab-ownership');
    window.vietnamicaRecoveryChannel = channel;
    channel.onmessage = event => {
      const data = event.data;
      if (data?.type === 'probe' && data.tab === metadata?.tab) {
        channel.postMessage({type: 'owned', tab: data.tab, nonce: data.nonce});
      }
    };
    window.addEventListener('pagehide', () => channel.close(), {signal: controller.signal});
  } } catch (_) { /* Tab ownership detection is optional in restricted frames. */ }
  const onInput = event => {
    if (!event.isTrusted || restoring) return;
    if (event.target && !event.target.closest(
      uiSelectors.map(id => `#${id}`).join(','))) return;
    // Run after the editor's synchronous radio/coordinate handlers.
    queueMicrotask(captureUI);
  };
  document.addEventListener('input', onInput, {signal: controller.signal});
  document.addEventListener('change', onInput, {signal: controller.signal});
  window.addEventListener('pagehide', captureUI, {signal: controller.signal});
  const activate = meta => {
    if (!meta) return;
    metadata = meta;
    let stale = false;
    for (const [id, record] of Object.entries(records)) {
      if (record?.metadata?.application !== meta.application || record.metadata.tab !== meta.tab) {
        delete records[id]; stale = true;
      } else if ((meta.discardImage && record.metadata.image === meta.discardImage)
          || (record.metadata.image === meta.image && record.metadata.generation !== meta.generation)) {
        delete records[id];
      }
    }
    persist();
    if (meta.defaultSection && !read(meta)?.section) write(meta, {section: meta.defaultSection});
    document.querySelector('#workspace')?.removeAttribute('inert');
    document.querySelector('#workflow-footer')?.removeAttribute('inert');
    document.querySelector('.gradio-container')?.removeAttribute('inert');
    notice(failed || window.vietnamicaStorageError
      ? 'Draft recovery unavailable: check browser session storage.'
      : stale ? 'Drafts from an earlier application session were ignored.' : 'Draft recovery active for this tab.');
  };
  const restoreUI = (record, setter) => {
    restoring = true;
    try {
      for (const [id, value] of Object.entries(record?.ui || {})) {
        if (uiSelectors.includes(id)) setter(`#${id}`, value);
      }
    } finally { restoring = false; }
  };
  let installedProgress = null;
  const installProgress = meta => {
    const imported = meta?.progressImport;
    if (!imported || imported.id === installedProgress) return;
    try {
      if (sessionStorage.getItem('vietnamica-progress-import-id') === imported.id) {
        installedProgress = imported.id;
        return;
      }
    } catch (_) { /* In-memory recovery still works when storage is blocked. */ }
    // A portable import establishes a new generation. Old tab drafts must never
    // win a subsequent component mount or a page reload.
    records = structuredClone(imported.records);
    installedProgress = imported.id;
    persist();
    try { sessionStorage.setItem('vietnamica-progress-import-id', imported.id); }
    catch (_) { failed = true; }
  };
  const exportProgress = () => {
    captureUI();
    if (metadata?.image) {
      if (window.vietnamicaWorkspace?.active()) write(metadata, {workspace: window.vietnamicaWorkspace.snapshot()});
      if (window.vietnamicaViewer?.active()) write(metadata, {viewer: window.vietnamicaViewer.progressSnapshot()});
    }
    return {application: metadata?.application, drafts: structuredClone(records)};
  };
  const section = (value, content) => {
    const record = read(metadata);
    if (metadata?.image) write(metadata, {section: value, content});
    return record?.typing?.[value];
  };
  const content = value => write(metadata, {content: JSON.stringify(value)});
  window.vietnamicaRecovery = {section, content};
  return {read, write, activate, restoreUI, captureUI, notice, installProgress, exportProgress};
})();
window.vietnamicaDraftRecovery = draftRecovery;
let lastRecoveryKey = '';
const initializeRecovery = () => {
  const meta = props.value;
  if (!meta) return;
  draftRecovery.installProgress(meta);
  const record = draftRecovery.read(meta);
  draftRecovery.activate(meta);
  const identity = JSON.stringify(meta);
  if (identity === lastRecoveryKey) return;
  lastRecoveryKey = identity;
  requestAnimationFrame(() => draftRecovery.restoreUI(record, (selector, value) => {
    const input = document.querySelector(`${selector} input, ${selector} textarea`);
    if (!input) return;
    const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(input, String(value));
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }));
  if (meta.progressImport && meta.step === 6 && record?.viewer) {
    requestAnimationFrame(() => window.vietnamicaViewer?.restoreProgress(record.viewer));
  }
};
watch('value', initializeRecovery);
initializeRecovery();
