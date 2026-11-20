#!/usr/bin/env node
// Checks sketch/index.html in headless Chromium.
//
//   node sketch/check.js <out-dir>
//
// Renders the loop offline through the same engine the page plays live (full mix and
// each part alone) and writes the WAVs to <out-dir> for bridge/measure.py and
// bridge/spectrum.py. Then presses Play at phone size and reports whether the audio
// context ran, the playhead moved and the console stayed clean, and runs the page's own
// sound check: output meter, test tone, and the loop rendered to a file player. Writes a
// screenshot.
//
// A pass here says the page works in Chromium. It says nothing about how it sounds,
// and nothing about Safari on iOS: both of those are checked by ear on the device.

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const out = path.resolve(process.argv[2] || '.');
  fs.mkdirSync(out, { recursive: true });
  const page_url = 'file://' + path.join(__dirname, 'index.html');

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  const problems = [];
  page.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  await page.goto(page_url);
  await page.waitForFunction(() => window.SketchKit);

  for (const solo of [null, 'drums', 'bass', 'keys']) {
    const r = await page.evaluate(s => window.SketchKit.render({ solo: s, loops: 2, state: s ? { crackle: -61 } : {} }), solo);
    const name = (solo || 'mix') + '.wav';
    fs.writeFileSync(path.join(out, name), Buffer.from(r.wavBase64, 'base64'));
    console.log(name.padEnd(12), 'peak', (20 * Math.log10(r.peak)).toFixed(1), 'dBFS,', r.seconds.toFixed(1), 's');
  }

  await page.click('#play');
  await page.waitForTimeout(1500);
  const a = await page.evaluate(() => Object.assign(window.SketchKit.debug(), {
    counter: document.getElementById('counter').textContent,
    status: document.getElementById('status').textContent,
    sideScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth
  }));
  await page.waitForTimeout(1000);
  const b = await page.evaluate(() => window.SketchKit.debug());
  console.log('live:', JSON.stringify(a));
  if (a.ctx !== 'running') problems.push('audio context is ' + a.ctx);
  if (!a.playing || a.beat === b.beat) problems.push('transport did not advance');
  if (a.sideScroll) problems.push('page scrolls sideways at 390 px');
  const meter = await page.evaluate(() => document.getElementById('meter-out').textContent);
  console.log('meter while playing:', meter);
  if (!/dBFS/.test(meter)) problems.push('meter shows "' + meter + '" while playing');
  await page.click('#play');

  await page.locator('#crackle').fill('-61');
  await page.waitForTimeout(900);
  const quiet = await page.evaluate(() => document.getElementById('meter-out').textContent);
  await page.click('#tone-test');
  await page.waitForTimeout(300);
  const tone = await page.evaluate(() => document.getElementById('meter-out').textContent);
  console.log('meter stopped:', quiet, '| during test tone:', tone);
  if (!/dBFS/.test(tone)) problems.push('test tone did not reach the meter');

  await page.click('#file-test');
  await page.waitForSelector('#file-slot audio', { timeout: 60000 });
  await page.waitForFunction(() => document.querySelector('#file-slot audio').duration > 0, null, { timeout: 15000 });
  const file = await page.evaluate(() => { const a = document.querySelector('#file-slot audio'); return { duration: a.duration, paused: a.paused }; });
  console.log('file player:', JSON.stringify(file));
  if (!(file.duration > 20)) problems.push('rendered file is ' + file.duration + ' s');
  await page.screenshot({ path: path.join(out, 'phone.png'), fullPage: true });
  await browser.close();

  if (problems.length) { console.log('FAIL\n' + problems.join('\n')); process.exit(1); }
  console.log('ok');
})();
