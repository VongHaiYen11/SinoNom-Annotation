function startFontLoader(manifest, unicodeRange) {
    // Gradio callbacks can run again; retain the existing downloads and registrations.
    if (window.vietnamicaFontLoader) return;
    const fonts = manifest.map(spec => ({...spec, received: 0, total: spec.size || null,
        status: 'loading', face: null, error: null}));
    const dialog = document.createElement('dialog');
    dialog.id = 'font-loading';
    dialog.setAttribute('aria-labelledby', 'font-loading-title');
    dialog.setAttribute('aria-describedby', 'font-loading-help');
    dialog.innerHTML = `<h2 id="font-loading-title" tabindex="-1">Đang tải font Hán/Nôm</h2>
        <p id="font-loading-help">Đang chuẩn bị font cho ký tự Hán/Nôm.</p>
        <p data-font-total role="status" aria-live="polite"></p>
        <progress aria-label="Dung lượng tải font"></progress>
        <ul data-font-list></ul>
        <div data-font-actions hidden><button type="button" data-font-wait>Tiếp tục chờ</button>
        <button type="button" data-font-work>Làm việc với font đã có</button></div>`;
    document.body.appendChild(dialog);
    const find = selector => dialog.querySelector(selector);
    const actions = find('[data-font-actions]');
    const wait = find('[data-font-wait]');
    const work = find('[data-font-work]');
    const help = find('#font-loading-help');
    const title = find('#font-loading-title');
    const progress = find('progress');
    const rows = fonts.map(font => {
        const row = document.createElement('li');
        find('[data-font-list]').appendChild(row);
        return row;
    });
    const labels = {loading: 'Đang tải', processing: 'Đang xử lý', ready: 'Sẵn sàng', error: 'Lỗi'};
    const mb = bytes => `${(bytes / 1e6).toFixed(2)} MB`;
    const amount = (received, total) => total
        ? `${mb(received)} / ${mb(total)} · ${Math.min(100, Math.floor(received / total * 100))}%`
        : mb(received);
    let timer, background = false, previousFocus = document.activeElement;
    const pending = () => fonts.some(font => ['loading', 'processing'].includes(font.status));
    function close() {
        if (!dialog.open) return;
        dialog.close();
        if (previousFocus?.isConnected) previousFocus.focus();
    }
    function choose() {
        if (background) return;
        actions.hidden = false;
        help.textContent = 'Một số ký tự có thể chưa hiển thị đủ. Bạn có thể chờ hoặc làm việc trong khi font tiếp tục tải ngầm.';
        wait.textContent = pending() ? 'Tiếp tục chờ' : 'Thử lại font lỗi';
        if (!dialog.open) {
            previousFocus = document.activeElement;
            dialog.showModal();
        }
        if (document.activeElement === title) wait.focus();
    }
    function render() {
        const total = fonts.every(font => font.total) ? fonts.reduce((n, f) => n + f.total, 0) : null;
        const received = fonts.reduce((n, f) => n + f.received, 0);
        find('[data-font-total]').textContent = amount(received, total);
        progress.max = total || 1;
        if (total) progress.value = Math.min(received, total);
        else progress.removeAttribute('value');
        fonts.forEach((font, i) => {
            rows[i].textContent = `${font.name}: ${amount(font.received, font.total)} — ${labels[font.status]}`;
            rows[i].title = font.error || '';
        });
        if (fonts.every(font => font.status === 'ready')) {
            clearTimeout(timer);
            close();
        } else if (!pending()) {
            clearTimeout(timer);
            choose();
        } else if (!actions.hidden) wait.textContent = 'Tiếp tục chờ';
    }
    function armTimer() {
        clearTimeout(timer);
        timer = setTimeout(choose, 300000);
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
        help.textContent = 'Đang chuẩn bị font cho ký tự Hán/Nôm.';
        title.focus();
        armTimer();
        // Mark every failed font pending before starting retries, so fast failures do not
        // reopen the choice while other retries are still being scheduled.
        const failed = fonts.filter(font => font.status === 'error');
        failed.forEach(font => { font.status = 'loading'; });
        failed.forEach(load);
        render();
    });
    work.addEventListener('click', () => {
        background = true; clearTimeout(timer); close();
    });
    // Native modal dialog supplies focus containment and makes the page inert.
    // Escape and backdrop clicks must not dismiss this explicit choice.
    dialog.addEventListener('cancel', event => event.preventDefault());
    window.vietnamicaFontLoader = {fonts};
    dialog.showModal(); title.focus(); armTimer(); render();
    fonts.forEach(load);
}
