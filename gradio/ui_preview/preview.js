const steps = ['Image', 'Content', 'Bounding Boxes', 'Reading Order', 'Status', 'Crop', 'Review'];
let current = 0;

const controls = [
  `<section class="panel-section"><h3>Image</h3><p class="helper">Choose an image to begin the annotation workflow.</p><button class="button primary" data-demo>Open selected image</button></section>`,
  `<section class="panel-section"><h3>Content actions</h3><div class="action-grid"><button class="button primary" data-demo>Save content</button><button class="button" data-demo>Undo changes</button><button class="button full" id="preview-image">Preview image</button></div><details class="disclosure"><summary>More actions</summary><button class="button danger" data-demo>Restore original content</button></details></section>`,
  `<section class="panel-section"><h3>Selected region</h3><div class="coordinate-grid"><label>x1<input value="128"></label><label>y1<input value="84"></label><label>x2<input value="246"></label><label>y2<input value="204"></label></div><button class="button primary" data-demo>Update coordinates</button></section><section class="panel-section"><h3>Box actions</h3><p class="helper">Click or drag to select. Ctrl/Cmd adds to selection; Alt/Option-drag creates a box.</p><button class="button danger full" data-demo>Delete selected</button></section><details class="panel-section disclosure"><summary>Detection</summary><button class="button" data-demo>Run detection</button></details>`,
  `<section class="panel-section"><h3>Selected region</h3><div class="status-options"><label class="status-option"><input type="radio" name="status" checked> Intact</label><label class="status-option"><input type="radio" name="status"> Damaged</label></div><p class="helper">The selected status is saved when you continue.</p></section>`,
  `<section class="panel-section"><h3>Reading order</h3><p class="helper">Drag the numbered cards in the workspace to define the final sequence.</p><div class="validation"><div><span>Regions</span><strong>4</strong></div><div><span>Order</span><strong>1, 2, 3, 4</strong></div></div></section>`,
  `<section class="panel-section"><h3>Crop</h3><p class="helper">Adjust the orange crop frame. Oversized crops are scaled automatically on export.</p><label>Coordinates<input value="[24, 18, 920, 1260]"></label><button class="button primary" data-demo>Apply crop</button></section>`,
  `<section class="panel-section"><h3>Validation</h3><div class="validation"><div><span>Bounding boxes</span><strong>4</strong></div><div><span>Characters</span><strong>4</strong></div><div><span>Difference</span><strong>0</strong></div></div></section><section class="panel-section"><h3>Ready to save</h3><p class="helper">This preview does not write files or export annotations.</p><button class="button primary" data-demo>Save image</button></section>`
];

const stepper = document.querySelector('#stepper');
const title = document.querySelector('#step-title');
const canvasTitle = document.querySelector('#canvas-title');
const stepCount = document.querySelector('#step-count');
const controlHost = document.querySelector('#step-controls');
const back = document.querySelector('#back');
const next = document.querySelector('#next');
const dialog = document.querySelector('#image-dialog');
const toast = document.querySelector('#toast');

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 1600);
}

function bindDemoControls() {
  document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => showToast('UI preview only — no action was saved.')));
  document.querySelector('#preview-image')?.addEventListener('click', () => dialog.showModal());
}

function render() {
  stepper.innerHTML = steps.map((step, index) => `<li class="step ${index === current ? 'current' : index < current ? 'complete' : ''}" data-step="${index}"><span class="step-dot">${index < current ? '✓' : index + 1}</span><span class="step-label">${step}</span></li>`).join('');
  title.textContent = steps[current];
  canvasTitle.textContent = steps[current];
  stepCount.textContent = `${steps[current]} / ${current + 1} of ${steps.length}`;
  controlHost.innerHTML = controls[current];
  back.disabled = current === 0;
  next.disabled = current === steps.length - 1;
  document.querySelectorAll('[data-step]').forEach(item => item.addEventListener('click', () => { current = Number(item.dataset.step); render(); }));
  bindDemoControls();
}

back.addEventListener('click', () => { if (current > 0) { current -= 1; render(); } });
next.addEventListener('click', () => { if (current < steps.length - 1) { current += 1; render(); } });
document.querySelector('#close-preview').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
render();
