// Minimal CDP harness: launch the studio in headless Chrome, wait for the demo
// to finish building, then screenshot / evaluate. No npm deps (uses the global
// WebSocket in Node 22).
//
//   node h3/shot.js "http://127.0.0.1:8791/index.html?demo4" out.png
//   EVAL="JSON.stringify(window.__seq())" node h3/shot.js <url>
//   SAVE_SHEET=/abs/path/sheet.png node h3/shot.js <url>
//
// Headless throttles requestAnimationFrame hard (measured ~1.6 fps instead of
// 10), so playIdx advances slowly here -- that is the harness, not the app.
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9333;
const URL_ = process.argv[2] || 'http://127.0.0.1:8791/index.html?demo4';
const SHOT = process.argv[3] || '';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const proc = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    '--window-size=1600,1000', '--hide-scrollbars',
    '--user-data-dir=' + path.join(require('os').tmpdir(), 'wb-cdp-profile'),
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--no-proxy-server', '--proxy-bypass-list=*',
    'about:blank',
  ], { stdio: 'ignore' });

  let list = null;
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      list = await r.json();
      if (list.length) break;
    } catch (e) {}
    await sleep(250);
  }
  if (!list) { console.error('chrome did not start'); proc.kill(); process.exit(1); }
  const page = list.find(t => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const logs = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.consoleAPICalled') {
      logs.push(m.params.args.map(a => a.value ?? a.description ?? a.type).join(' '));
    }
    if (m.method === 'Runtime.exceptionThrown') {
      logs.push('EXC ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    }
  };
  await new Promise(r => ws.onopen = r);
  const send = (method, params = {}) => new Promise(res => {
    const i = ++id;
    pending.set(i, res);
    ws.send(JSON.stringify({ id: i, method, params }));
  });

  await send('Runtime.enable');
  await send('Page.enable');
  // W / H 让同一份脚本能测窄窗口（候选池展开后的媒体查询就靠这个验）
  const W = +(process.env.W || 1400), H = +(process.env.H || 940);
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: URL_ });

  const evalJs = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) return 'ERR ' + JSON.stringify(r.result.exceptionDetails).slice(0, 400);
    return r.result?.result?.value;
  };

  // wait until the demo has produced frames + a timeline
  let state = null;
  for (let i = 0; i < 120; i++) {
    await sleep(500);
    state = await evalJs(`(()=>{try{
      const cells=document.querySelectorAll('#grid .cell').length;
      const pv=document.querySelectorAll('#pwrap .pv canvas').length;
      return JSON.stringify({cells,pv,title:document.title,err:window.__err||null});
    }catch(e){return 'E '+e.message}})()`);
    if (typeof state === 'string' && state.includes('"cells":') && !state.includes('"cells":0')) break;
  }
  console.log('STATE', state);
  const extra = await evalJs(process.env.EVAL || '1');
  console.log('EVAL', JSON.stringify(extra).slice(0, 1500));

  if (process.env.SAVE_SHEET) {
    const r = await send('Runtime.evaluate', { expression:
      `(()=>{exportSheet();const c=window.__lastSheet.canvas;return JSON.stringify({url:c.toDataURL('image/png'),w:c.width,h:c.height,atlas:window.__lastAtlas});})()`,
      returnByValue: true, awaitPromise: true });
    const v = r.result.result.value;
    const o = JSON.parse(v);
    fs.writeFileSync(process.env.SAVE_SHEET, Buffer.from(o.url.split(',')[1], 'base64'));
    fs.writeFileSync(process.env.SAVE_SHEET.replace(/\.png$/, '_atlas.json'), JSON.stringify(o.atlas, null, 1));
    console.log('SHEET', o.w + 'x' + o.h, process.env.SAVE_SHEET);
  }

  if (SHOT) {
    const r = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(r.result.data, 'base64'));
    console.log('SHOT ' + SHOT);
  }
  if (logs.length) console.log('LOGS\n' + logs.slice(0, 30).join('\n'));
  ws.close();
  proc.kill();
  process.exit(0);
}
main().catch(e => { console.error(e); process.exit(1); });
