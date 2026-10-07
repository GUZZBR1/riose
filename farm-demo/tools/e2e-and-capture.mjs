import assert from 'node:assert/strict';
import { copyFile, mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../', import.meta.url));
const repository = resolve(root, '..');
const output = resolve(repository, 'docs/demo-preview');
const recordingDir = resolve(output, '.recording');
const baseUrl = process.env.RIOSE_BASE_URL || 'http://127.0.0.1:8009';
await mkdir(output, { recursive: true });
await rm(recordingDir, { recursive: true, force: true });
await mkdir(recordingDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const errors = [];
const mainContext = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  recordVideo: { dir: recordingDir, size: { width: 1440, height: 960 } },
});
const page = await mainContext.newPage();
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`${message.text()} @ ${JSON.stringify(message.location())}`);
});

try {
  await page.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await page.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(() => document.querySelectorAll('#farm-roster [role="option"]').length === 24);
  await page.waitForTimeout(1200);
  assert.equal(await page.locator('#farm-animal-count').textContent(), '24');
  await page.screenshot({ path: resolve(output, 'farm-demo-desktop.png'), fullPage: true });

  await page.getByRole('button', { name: 'Signals' }).click();
  assert.equal(await page.getByRole('button', { name: 'Signals' }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#farm-mode-caption').textContent(), 'Local signal estimate');
  await page.getByRole('button', { name: 'Coverage' }).click();
  assert.equal(await page.locator('#farm-mode-caption').textContent(), 'Estimated anchor coverage');

  await page.getByRole('button', { name: /Herd/ }).click();
  const firstAnimal = page.locator('#farm-roster [role="option"]').first();
  await firstAnimal.focus();
  await page.keyboard.press('Enter');
  await page.locator('#farm-animal-panel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#selected-animal-name').textContent(), 'Animal 0');
  assert.ok(await page.locator('#selected-animal-position').textContent());

  await page.getByRole('button', { name: 'Track' }).click();
  assert.equal(await page.locator('#farm-mode-caption').textContent(), 'Tracking Animal 0');
  await page.getByRole('button', { name: 'Open animal record' }).click();
  await page.locator('#record-screen').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#record-title').textContent(), 'Animal 0');
  assert.match(await page.locator('#record-portrait').getAttribute('src'), /\/assets\/demo\/animal-0\.webp$/);
  assert.equal(await page.locator('#journey-list .journey-beat').count(), 3);
  await page.locator('#record-verification').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('#record-verification')?.textContent === 'Record integrity verified', null, { timeout: 10000 });
  assert.equal(await page.getByRole('button', { name: 'Explore digital identity' }).isEnabled(), true);
  await page.waitForTimeout(650); // let the screen's blur/opacity entrance finish before capture
  await page.screenshot({ path: resolve(output, 'farm-demo-animal-record.png'), fullPage: true });

  const video = page.video();
  await page.waitForTimeout(1000);
  await mainContext.close();
  await copyFile(await video.path(), resolve(output, 'farm-demo-walkthrough.webm'));
  await rm(recordingDir, { recursive: true, force: true });

  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mobilePage = await mobileContext.newPage();
  mobilePage.on('pageerror', (error) => errors.push(error.message));
  await mobilePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await mobilePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await mobilePage.waitForTimeout(800);
  const mobileWidth = await mobilePage.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  assert.ok(mobileWidth.scroll <= mobileWidth.client + 1, `mobile horizontal overflow: ${JSON.stringify(mobileWidth)}`);
  await mobilePage.screenshot({ path: resolve(output, 'farm-demo-mobile.png'), fullPage: true });
  await mobileContext.close();

  const offlineContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const offlinePage = await offlineContext.newPage();
  await offlinePage.route('**/api/**', (route) => route.abort());
  await offlinePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await offlinePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await offlinePage.getByRole('button', { name: /Herd/ }).click();
  await offlinePage.locator('#farm-roster [role="option"]').first().click();
  await offlinePage.getByRole('button', { name: 'Open animal record' }).click();
  await offlinePage.getByRole('heading', { name: 'Animal 0' }).waitFor({ state: 'visible' });
  await offlinePage.getByText('Record unavailable').waitFor({ state: 'visible', timeout: 10000 });
  await offlinePage.getByRole('button', { name: 'Back to farm' }).click();
  await offlinePage.locator('#farm-canvas canvas').waitFor({ state: 'visible' });
  await offlineContext.close();

  const stressPage = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await stressPage.goto(`${baseUrl}/demo?herd=100`, { waitUntil: 'domcontentloaded' });
  await stressPage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await stressPage.waitForFunction(() => document.querySelectorAll('#farm-roster [role="option"]').length === 100);
  const performance = await stressPage.evaluate(() => new Promise((resolveResult) => {
    let frames = 0;
    let longTasks = 0;
    const start = performance.now();
    const observer = 'PerformanceObserver' in window
      ? new PerformanceObserver((list) => { longTasks += list.getEntries().length; })
      : null;
    try { observer?.observe({ type: 'longtask', buffered: true }); } catch {}
    const tick = (now) => {
      frames += 1;
      if (now - start >= 4000) {
        observer?.disconnect();
        resolveResult({ fps: Math.round(frames * 1000 / (now - start)), longTasks });
      } else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }));
  await stressPage.getByRole('button', { name: 'Signals' }).click();
  await stressPage.getByRole('button', { name: 'Coverage' }).click();
  assert.equal(await stressPage.locator('#farm-animal-count').textContent(), '100');
  await stressPage.context().close();

  const bundlePath = resolve(repository, 'src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/farm-demo.js');
  const bundle = await readFile(bundlePath);
  const rawBytes = (await stat(bundlePath)).size;
  const gzipBytes = gzipSync(bundle).byteLength;
  const report = [
    '# Farm demo browser evidence',
    '',
    `- Date: ${new Date().toISOString()}`,
    `- Browser: Chromium ${browser.version()}`,
    `- Desktop view: 1440 × 960; Mobile view: 390 × 844`,
    `- Herd stress run: 100 animals; browser animation-frame rate: ${performance.fps} fps; observed long tasks: ${performance.longTasks}`,
    `- Scene bundle: ${rawBytes.toLocaleString('en-US')} bytes; gzip: ${gzipBytes.toLocaleString('en-US')} bytes`,
    '- Verified in-browser: all four modes, keyboard roster selection, selected-animal panel, API-backed record verification, mobile horizontal overflow, and scene availability when API requests fail.',
    '',
  ].join('\n');
  await writeFile(resolve(output, 'README.md'), report);
  assert.deepEqual(errors, [], `browser console errors: ${errors.join(' | ')}`);
  console.log(report);
} finally {
  await browser.close();
}
