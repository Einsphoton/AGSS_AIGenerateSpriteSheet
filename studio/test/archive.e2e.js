#!/usr/bin/env node
/* 工程存档往返测试 —— 验证「保存工程 → 换一个页面 → 导入工程」之后
   参数、时间轴、素材来源、导出表都原样回来。

   需要在跑着一个 serve.py（studio 必须是它 serve 出来的那份，否则 ?frames= 读不到），
   并且 SERVE_ROOT 指向那个服务真正在 serve 的目录 —— 测试要把 zip 放回这个目录，
   页面才能 fetch('/_archive_test.zip') 把它读回来。

     STUDIO_URL='http://127.0.0.1:8777/_studio/index.html?frames=/frames/attack&videos=/videos&key=ff00ff' \
     SERVE_ROOT='/path/to/sprite-project' \
     node studio/test/archive.e2e.js

   可选：CHROME=/path/to/chrome   ONLY=images,video,gif   KEEP_ZIP=1

   三个场景对应三种素材来源，三种在 zip 里的存法都不一样：
     images  逐张 PNG 源 → 位图存进 assets/<dir>/NNNN.png
     video   ?videos= 拉下来的 mp4 → 原始字节存进 assets/<dir>.mp4
     gif     拖进来的 .gif → 原始字节存进 assets/<dir>.gif
   判定标准不是「差不多」：三个场景都比一次 buildSheet() 的 PNG 指纹，
   逐像素不一致就算 FAIL。 */

'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const URL_ = process.env.STUDIO_URL;
const ROOT = process.env.SERVE_ROOT;
const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const ONLY = (process.env.ONLY || 'images,video,gif').split(',').map(s => s.trim()).filter(Boolean);
const HANDBACK = '_archive_test.zip';
if (!URL_ || !ROOT) {
  console.error('需要 STUDIO_URL 和 SERVE_ROOT，见文件头注释');
  process.exit(2);
}
if (!fs.existsSync(CHROME)) {
  console.error('找不到 Chrome：' + CHROME + '（用 CHROME=... 指定）');
  process.exit(2);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const PORT = 9400 + Math.floor(Math.random() * 200);
const DL = path.join(os.tmpdir(), 'studio_dl_' + Date.now());
const PROFILE = path.join(os.tmpdir(), 'studio_prof_' + Date.now());
fs.mkdirSync(DL, { recursive: true });

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.wait = new Map(); this.sid = null;
    ws.addEventListener('message', ev => {
      const m = JSON.parse(ev.data);
      if (m.id && this.wait.has(m.id)) {
        const { res, rej } = this.wait.get(m.id); this.wait.delete(m.id);
        m.error ? rej(new Error(m.error.message)) : res(m.result);
      }
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    this.ws.send(JSON.stringify(msg));
    return new Promise((res, rej) => {
      this.wait.set(id, { res, rej });
      setTimeout(() => { if (this.wait.has(id)) { this.wait.delete(id); rej(new Error('timeout ' + method)); } }, 180000);
    });
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate',
      { expression: expr, awaitPromise: true, returnByValue: true, userGesture: true }, this.sid);
    if (r.exceptionDetails) throw new Error('page error: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
}

const SNAP = `JSON.stringify({
  seqs: window.__seq(),
  tracks: window.__tracks.map(t => ({ id:t.id, frames:t.frames.length, kind:t.srcKind,
                                      extras:(t.extras||[]).length, name:t.srcName||'' })),
  p: { count:__P.count, tol:__P.tol, soft:__P.soft, desc:__P.despill, erode:__P.erode,
       key:__P.key, pxMode:__P.pxMode, align:__P.align, palette:__P.palette, norm:__P.norm,
       fname:__P.fname, scale:__P.scale, merge:__P.merge, fps:__P.fps,
       tStart:__P.tStart, tEnd:__P.tEnd, mult:__P.mult, cols:__P.cols, gap:__P.gap },
  cell: { w:__G().cellW, h:__G().cellH, pal:__G().palN },
  hasSheet: !!window.__lastSheet, sheetName: window.__sheetName || ''
})`;

/* 表指纹：把「当前参数下的成品表」编码成 PNG 再取 SHA-256 前 8 字节。
   比像素数组省事，而且连编码差异都算进去了。 */
const HASH = `(async () => {
  const sh = window.__buildSheet(); if (!sh) return 'none';
  const b = await new Promise(r => sh.canvas.toBlob(r, 'image/png'));
  const d = await crypto.subtle.digest('SHA-256', await b.arrayBuffer());
  return sh.W + 'x' + sh.H + ':' + [...new Uint8Array(d)].slice(0, 8)
    .map(x => x.toString(16).padStart(2, '0')).join('');
})()`;

(async () => {
  const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', 'about:blank'], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; break; }
    catch (e) { await sleep(300); }
  }
  if (!wsUrl) throw new Error('Chrome 没起来（--remote-debugging-port ' + PORT + '）');

  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const cdp = new CDP(ws);
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL, eventsEnabled: true });
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  cdp.sid = sessionId;
  for (const d of ['Page', 'Runtime', 'DOM']) await cdp.send(d + '.enable', {}, sessionId);

  const goto = u => cdp.send('Page.navigate', { url: u }, sessionId);
  const waitFor = async (label, expr, ms = 240000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try { if (await cdp.eval(expr)) return; } catch (e) {}
      await sleep(400);
    }
    throw new Error(label + ' 超时（' + Math.round(ms / 1000) + 's）');
  };
  const openStudio = async () => {
    await goto('about:blank'); await sleep(300);
    await goto(URL_);
    await waitFor('studio 载入', `document.title.startsWith('slots=')`);
  };

  const setFiles = async (selector, files) => {
    const { root } = await cdp.send('DOM.getDocument', {}, sessionId);
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector }, sessionId);
    if (!nodeId) throw new Error('找不到 ' + selector);
    await cdp.send('DOM.setFileInputFiles', { files, nodeId }, sessionId);
  };

  const runCase = async (name, prepare, ready) => {
    if (!ONLY.includes(name)) { console.log(`--- ${name}: 跳过`); return null; }
    console.log(`\n=== ${name} ===`);
    await openStudio();
    await prepare();
    await waitFor(name + ' 就绪', ready);

    const before = JSON.parse(await cdp.eval(SNAP));
    const h1 = await cdp.eval(HASH);
    console.log('  素材:', before.tracks.map(t => `${t.id}:${t.kind}/${t.frames}`).join(' | '));
    console.log('  表指纹:', h1);

    const t0 = Date.now();
    await cdp.eval(`document.querySelector('#btnProjSave').click(), 1`);
    let zips = [];
    for (let i = 0; i < 240; i++) {
      zips = fs.readdirSync(DL).filter(f => f.endsWith('.zip'));
      if (zips.length) break;
      await sleep(500);
    }
    if (!zips.length) throw new Error('没有下载到 zip');
    const zp = path.join(DL, zips[0]);
    let prev = -1;
    for (let i = 0; i < 120; i++) {
      const s = fs.statSync(zp).size;
      if (s === prev && s > 0) break;
      prev = s; await sleep(400);
    }
    console.log(`  存档: ${zips[0]}  ${(fs.statSync(zp).size / 1048576).toFixed(2)} MB  (${Date.now() - t0}ms)`);

    /* 换一个干净的页面再导入 = 换一台机器：内存里什么都不剩，只有这个 zip */
    fs.copyFileSync(zp, path.join(ROOT, HANDBACK));
    await openStudio();
    await cdp.eval(`(async () => {
      const r = await fetch('/${HANDBACK}?t=' + Date.now());
      if (!r.ok) throw new Error('取不到 zip: HTTP ' + r.status + '（SERVE_ROOT 对吗？）');
      await window.__projLoad(new Uint8Array(await r.arrayBuffer()));
      return 1;
    })()`);
    await waitFor(name + ' 导入', ready);
    await sleep(800);

    const after = JSON.parse(await cdp.eval(SNAP));
    const h2 = await cdp.eval(HASH);
    console.log('  导入后:', after.tracks.map(t => `${t.id}:${t.kind}/${t.frames}`).join(' | '));
    console.log('  表指纹:', h2);

    const jj = v => JSON.stringify(v);
    const checks = [
      ['素材来源', jj(before.tracks), jj(after.tracks)],
      ['时间轴', jj(before.seqs), jj(after.seqs)],
      ['参数', jj(before.p), jj(after.p)],
      ['单元格', jj(before.cell), jj(after.cell)],
      ['导出表', h1, h2],
      ['带回的表', String(before.hasSheet || after.hasSheet), String(after.hasSheet)],
    ];
    let bad = 0;
    for (const [label, a, b] of checks) {
      const ok = a === b;
      if (!ok) bad++;
      console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}` + (ok ? '' : `\n       before=${a}\n       after =${b}`));
    }
    if (!process.env.KEEP_ZIP) { fs.unlinkSync(zp); fs.rmSync(path.join(ROOT, HANDBACK), { force: true }); }
    return bad === 0;
  };

  const results = [];

  results.push(await runCase('images',
    async () => {},
    `window.__tracks.some(t => t.srcKind === 'images' && t.frames.length > 0)`));

  results.push(await runCase('video',
    async () => {
      const opts = await cdp.eval(`[...document.querySelectorAll('#vidSel option')].map(o => o.value)`);
      if (!opts.length) throw new Error('没有版本化视频（URL 要带 ?videos=）');
      await cdp.eval(`(() => { const s = document.querySelector('#vidSel');
        s.value = ${JSON.stringify(opts[0])}; document.querySelector('#btnVidLoad').click(); return 1; })()`);
    },
    `window.__tracks.some(t => t.srcKind === 'video' && t.frames.length > 0)`));

  results.push(await runCase('gif',
    async () => {
      await setFiles('#file', [path.join(__dirname, 'fixtures', 'anim6f.gif')]);
    },
    `window.__tracks.some(t => t.srcKind === 'gif' && t.frames.length > 0)`));

  const ran = results.filter(r => r !== null);
  const ok = ran.length > 0 && ran.every(Boolean);
  console.log(`\n${ok ? '全部通过' : '有失败项'}（${ran.filter(Boolean).length}/${ran.length}）`);

  ws.close(); chrome.kill();
  /* Chrome 退出是异步的：立刻删 profile 会撞到 Crashpad 还占着文件（EBUSY），
     所以等一下再删，删不掉也不算失败 —— 临时目录而已。 */
  await sleep(1200);
  try {
    fs.rmSync(PROFILE, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
    fs.rmSync(DL, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
  } catch (e) {
    console.warn('（临时目录没删干净，可忽略：' + e.code + '）');
  }
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error('FAILED:', e.message); process.exit(1); });
