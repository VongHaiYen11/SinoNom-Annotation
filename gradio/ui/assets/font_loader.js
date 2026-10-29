function startFontLoader(manifest, unicodeRange) {
    // Gradio callbacks can run again; retain the existing downloads and registrations.
    if (window.vietnamicaFontLoader) return;
    const fonts = manifest.map(spec => ({...spec, received: 0, total: spec.size || null,
        status: 'loading', face: null, error: null}));
    const dialog = document.createElement('section');
    dialog.id = 'font-loading';
    dialog.setAttribute('role', 'region');
    dialog.setAttribute('aria-labelledby', 'font-loading-title');
    dialog.setAttribute('aria-describedby', 'font-loading-help');
    dialog.hidden = true;
    dialog.innerHTML = `<h2 id="font-loading-title">Preparing character fonts</h2>
        <p id="font-loading-help">Fonts are loading in the background. You can start working now.</p>
        <p data-font-total role="status" aria-live="polite"></p>
        <progress aria-label="Font download progress"></progress>
        <details data-font-details><summary data-font-summary>Font details</summary><ul data-font-list></ul></details>
        <div data-font-actions><button type="button" data-font-wait hidden>Retry failed fonts</button>
        <button type="button" data-font-work>Continue working</button></div>`;
    document.body.appendChild(dialog);
    const find = selector => dialog.querySelector(selector);
    const actions = find('[data-font-actions]');
    const wait = find('[data-font-wait]');
    const work = find('[data-font-work]');
    const help = find('#font-loading-help');
    const detailSummary = find('[data-font-summary]');
    const progress = find('progress');
    const rows = fonts.map(font => {
        const row = document.createElement('li');
        find('[data-font-list]').appendChild(row);
        return row;
    });
    const labels = {loading: 'Loading', processing: 'Preparing', ready: 'Ready', error: 'Error'};
    const mb = bytes => `${(bytes / 1e6).toFixed(2)} MB`;
    const amount = (received, total) => total
        ? `${mb(received)} / ${mb(total)} · ${Math.min(100, Math.floor(received / total * 100))}%`
        : mb(received);
    let background = false;
    const pending = () => fonts.some(font => ['loading', 'processing'].includes(font.status));
    function close() {
        dialog.hidden = true;
    }
    function choose() {
        background = false;
        dialog.hidden = false;
        actions.hidden = false;
        wait.hidden = false;
        help.textContent = 'One or more fonts could not be loaded.';
        wait.textContent = pending() ? 'Keep waiting' : 'Retry failed fonts';
        work.textContent = pending() ? 'Continue working' : 'Use available fonts';
    }
    function render() {
        const total = fonts.every(font => font.total) ? fonts.reduce((n, f) => n + f.total, 0) : null;
        const received = fonts.reduce((n, f) => n + f.received, 0);
        const errorCount=fonts.filter(font=>font.status==='error').length;
        const readyCount=fonts.filter(font=>font.status==='ready').length;
        const failureText=errorCount?`, ${errorCount} error${errorCount===1?'':'s'}`:'';
        const status=`${amount(received,total)} · ${readyCount}/${fonts.length} fonts ready${failureText}`;
        find('#font-loading-title').textContent=errorCount?`Font issue · ${readyCount}/${fonts.length} ready`:'Preparing character fonts';
        dialog.classList.toggle('font-error', !pending() && errorCount > 0);
        find('[data-font-total]').textContent = status;
        detailSummary.textContent=errorCount?`${errorCount} font error${errorCount===1?'':'s'} · View details`:`Font details · ${fonts.length} fonts`;
        progress.max = total || 1;
        if (total) progress.value = Math.min(received, total);
        else progress.removeAttribute('value');
        progress.hidden = !pending();
        fonts.forEach((font, i) => {
            rows[i].textContent = `${font.name}: ${amount(font.received, font.total)} — ${labels[font.status]}`;
            rows[i].title = font.error || '';
        });
        if (fonts.every(font => font.status === 'ready')) {
            close();
        } else if (!pending()) {
            choose();
        } else if (background) {
            dialog.hidden = true;
        } else {
            dialog.hidden = false;
            actions.hidden = false;
            wait.hidden = true;
            work.textContent = 'Continue working';
            help.textContent = 'Fonts are loading in the background. You can start working now.';
        }
    }
    async function load(font) {
        font.status = 'loading'; font.received = 0; font.total = font.size || null; font.error = null;
        try {
            const response = await fetch(font.url);
            if (!response.ok) throw Error(`HTTP ${response.status}`);
            // Content-Length for compressed responses measures encoded bytes, not stream bytes.
            const encoding = response.headers.get('Content-Encoding');
            const length = Number(response.headers.get('Content-Length'));
            if ((!encoding || encoding === 'identity') && Number.isFinite(length) && length > 0) font.total = length;
            render();
            let data;
            if (response.body) {
                const reader = response.body.getReader();
                const chunks = [];
                try {
                    while (true) {
                        const {done, value} = await reader.read();
                        if (done) break;
                        chunks.push(value); font.received += value.byteLength;
                        // A stale estimate must never report completion before bytes stop arriving.
                        if (font.total && font.received > font.total) font.total = null;
                        render();
                    }
                } finally { reader.releaseLock(); }
                data = new Uint8Array(font.received);
                let offset = 0;
                for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.byteLength; }
            } else {
                data = await response.arrayBuffer();
                font.received = data.byteLength;
            }
            font.total = font.received;
            font.status = 'processing'; render();
            const face = new FontFace(font.name, data, {weight: '400', style: 'normal', display: 'swap', unicodeRange});
            await face.load();
            document.fonts.add(face);
            font.face = face; font.status = 'ready';
        } catch (error) {
            font.status = 'error'; font.error = String(error);
        }
        render();
    }
    wait.addEventListener('click', () => {
        actions.hidden = true;
        help.textContent = 'Retrying failed fonts…';
        // Mark every failed font pending before starting retries, so fast failures do not
        // reopen the choice while other retries are still being scheduled.
        const failed = fonts.filter(font => font.status === 'error');
        failed.forEach(font => { font.status = 'loading'; });
        failed.forEach(load);
        render();
    });
    work.addEventListener('click', () => {
        background = true; close();
    });
    window.vietnamicaFontLoader = {fonts};
    render();
    fonts.forEach(load);
}
