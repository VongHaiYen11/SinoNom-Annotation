// Production loader, streaming responses, font processing, and a deterministic clock.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../ui/assets/font_loader.js'), 'utf8');
const deferred = () => {let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise, resolve, reject};};
const flush = async () => {for (let i=0;i<30;i++) await Promise.resolve();};
function mount(specs, responses, processing = {}) {
    let now=0, seq=0;
    const timers=new Map(), calls=[], added=[], nodes=new Map();
    const document = {activeElement:null, createElement: () => new Element(), fonts:{add: face => added.push(face)}};
    class Element {
        constructor() {this.hidden=false; this.open=false; this.isConnected=true; this.handlers={}; this.children=[];}
        setAttribute() {} removeAttribute(key) {delete this[key];}
        appendChild(child) {this.children.push(child);}
        querySelector(key) {if (!nodes.has(key)) nodes.set(key,new Element()); if (key === "[data-font-actions]" && !nodes.get(key).initialized) { nodes.get(key).hidden=true; nodes.get(key).initialized=true; } return nodes.get(key);}
        addEventListener(type,fn) {this.handlers[type]=fn;}
        focus() {document.activeElement=this;}
        showModal() {this.open=true;} close() {this.open=false;}
        click() {this.handlers.click();}
    }
    document.body=new Element();
    const original=new Element(); original.focus();
    const context={window:{}, document, Uint8Array, console,
        setTimeout: (fn,ms) => {timers.set(++seq,{fn,time:now+ms}); return seq;},
        clearTimeout: id => timers.delete(id),
        fetch: async url => {calls.push(url); const response=responses[url].shift(); if (response instanceof Error) throw response; return response;},
        FontFace: class {constructor(name) {this.name=name;} load() {return processing[this.name]?.() || Promise.resolve(this);}}};
    vm.createContext(context); vm.runInContext(source,context); context.startFontLoader(specs,'U+4E00-9FFF');
    return {context,calls,added,nodes, original,document,dialog:document.body.children[0],
        fonts:context.window.vietnamicaFontLoader.fonts,
        tick(ms) {now+=ms; for (const [id,t] of [...timers]) if(t.time<=now) {timers.delete(id); t.fn();}}};
}
function stream(length, parts) {
    let i=0;
    return {ok:true,headers:{get:k => k==='Content-Length'?length:null},body:{getReader:()=>({
        async read() {if(i===parts.length) return {done:true}; const value=await parts[i++]; return {done:false,value};},releaseLock(){}})}};
}
const spec=(name,size)=>({name,url:name,size});
(async () => {
    const rest=deferred(), decode=deferred();
    const p=mount([spec('a',100),spec('b',300)],{a:[stream('100',[new Uint8Array(100)])],b:[stream(null,[new Uint8Array(100),rest.promise])]}, {a:()=>decode.promise});
    await flush();
    assert.equal(p.fonts[0].status,'processing');
    assert.match(p.nodes.get('[data-font-total]').textContent,/50%/); // bytes, not per-font average
    assert.match(p.nodes.get('[data-font-list]').children[1].textContent,/33%/);
    p.tick(299999); assert.equal(p.nodes.get('[data-font-actions]').hidden,true);
    p.tick(1); assert.equal(p.nodes.get('[data-font-actions]').hidden,false);
    p.nodes.get('[data-font-wait]').click();
    assert.equal(p.calls.length,2); // active requests are preserved
    p.tick(299999); assert.equal(p.nodes.get('[data-font-actions]').hidden,true);
    p.tick(1); assert.equal(p.nodes.get('[data-font-actions]').hidden,false);
    p.nodes.get('[data-font-work]').click(); assert.equal(p.dialog.open,false);
    assert.equal(p.document.activeElement,p.original);
    rest.resolve(new Uint8Array(200)); decode.resolve(); await flush();
    assert.ok(p.fonts.every(f=>f.status==='ready')); assert.equal(p.added.length,2);
    p.context.startFontLoader([spec('a',100)],''); assert.equal(p.calls.length,2);
    assert.ok(!source.includes('global-loading')); assert.ok(!source.includes('location.reload'));

    // HTTP and font parsing errors open choices immediately, retry only failures.
    const bad=mount([spec('ok',2),spec('http',2),spec('parse',2)], {
        ok:[stream('2',[new Uint8Array(2)])],
        http:[{ok:false,status:503},stream('2',[new Uint8Array(2)])],
        parse:[stream('2',[new Uint8Array(2)]),stream('2',[new Uint8Array(2)])]
    }, {parse:(()=>{let first=true;return ()=>{if(first){first=false;return Promise.reject(Error('invalid font'));} return Promise.resolve();};})()});
    await flush();
    assert.equal(bad.nodes.get('[data-font-wait]').textContent,'Thử lại font lỗi');
    bad.nodes.get('[data-font-wait]').click(); await flush();
    assert.deepEqual(bad.calls,['ok','http','parse','http','parse']);
    assert.equal(bad.added.length,3); assert.equal(bad.dialog.open,false);

    // Choosing background work suppresses later error prompts as well.
    const laterError=deferred();
    const bg=mount([spec('background',5)],{background:[stream(null,[laterError.promise])]});
    await flush(); bg.tick(300000); bg.nodes.get('[data-font-work]').click();
    laterError.reject(Error('connection lost')); await flush();
    assert.equal(bg.fonts[0].status,'error'); assert.equal(bg.dialog.open,false);

    const sizedChunk=deferred();
    const sized=mount([spec('sized',100)],{sized:[stream('20',[new Uint8Array(10),sizedChunk.promise])]});
    await flush(); assert.equal(sized.fonts[0].total,20);
    assert.match(sized.nodes.get('[data-font-total]').textContent,/50%/);
    sizedChunk.resolve(new Uint8Array(10)); await flush();

    // Unknown sizes remain indeterminate; cache/bodyless responses still parse.
    const chunk=deferred();
    const unknown=mount([spec('x',null)],{x:[stream(null,[new Uint8Array(8),chunk.promise])]});
    await flush(); assert.ok(!unknown.nodes.get('[data-font-total]').textContent.includes('%'));
    assert.equal(unknown.nodes.get('progress').value,undefined);
    chunk.resolve(new Uint8Array(2)); await flush(); assert.equal(unknown.fonts[0].total,10);
    const cached=mount([spec('cached',20)],{cached:[{ok:true,headers:{get:()=>null},body:null,arrayBuffer:async()=>new ArrayBuffer(20)}]});
    await flush(); assert.equal(cached.added.length,1); assert.equal(cached.fonts[0].status,'ready');
    const compressed=deferred();
    const response=stream('2',[new Uint8Array(5),compressed.promise]);
    response.headers.get=k=>k==='Content-Encoding'?'gzip':'2';
    const zipped=mount([spec('zip',10)],{zip:[response]}); await flush();
    assert.equal(zipped.fonts[0].total,10);
    const event={preventDefault(){this.prevented=true;}};
    zipped.dialog.handlers.cancel(event); assert.equal(event.prevented,true);
    compressed.resolve(new Uint8Array(5)); await flush();
    console.log('font loader: streaming, byte progress, timeout, retry, background, cache and parsing passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
