import assert from 'node:assert/strict';
import { copyFile, mkdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
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
const assetMutations = [];
const mainContext = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  recordVideo: { dir: recordingDir, size: { width: 1440, height: 960 } },
});
const page = await mainContext.newPage();
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`${message.text()} @ ${JSON.stringify(message.location())}`);
});
page.on('request', (request) => {
  if (request.method() === 'POST' && /\/asset-(?:intent|reserve|submission)/.test(request.url())) {
    assetMutations.push(request.url());
  }
});

async function selectByKeyboard(target) {
  await page.locator('#farm-canvas').focus();
  await page.keyboard.press('Escape');
  for (let index = 0; index < target + 1; index += 1) await page.keyboard.press('ArrowRight');
  await page.locator('#farm-animal-panel').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#selected-animal-name').textContent(), `Animal ${target}`);
}

try {
  await page.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await page.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  await page.waitForFunction(() => Number(document.querySelector('#farm-canvas')?.dataset.movingAnimals) > 0);
  await page.locator('#farm-intro-hint').waitFor({ state: 'visible' });
  const initialCanvas = await page.locator('#farm-canvas canvas').evaluate((canvas) => canvas.toDataURL());
  await page.waitForTimeout(1200);
  const movedCanvas = await page.locator('#farm-canvas canvas').evaluate((canvas) => canvas.toDataURL());
  assert.notEqual(movedCanvas, initialCanvas, 'cattle visibly advance without pressing play');

  const forbidden = await page.locator('body').innerText();
  for (const label of ['Overview', 'Signals', 'Coverage', 'Track', 'SIMULATED', 'Herd overview', '24 animals']) {
    assert.ok(!forbidden.includes(label), `unexpected visible label: ${label}`);
  }
  assert.equal(await page.locator('#farm-animal-panel').isVisible(), false);
  await page.screenshot({ path: resolve(output, 'farm-demo-desktop.png'), fullPage: true });

  await selectByKeyboard(0);
  assert.equal(await page.locator('#farm-intro-hint').isVisible(), false, 'animal selection dismisses the hint');
  assert.match(await page.locator('#selected-animal-portrait').getAttribute('src'), /\/assets\/demo\/animal-0\.webp$/);
  assert.ok(await page.locator('#selected-animal-zone').textContent());
  await page.waitForTimeout(450);
  await page.screenshot({ path: resolve(output, 'farm-demo-selected-animal.png'), fullPage: true });
  await page.getByRole('button', { name: 'View animal record' }).click();
  await page.locator('#record-screen').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#record-title').textContent(), 'Animal 0');
  assert.match(await page.locator('#record-portrait').getAttribute('src'), /\/assets\/demo\/animal-0\.webp$/);
  assert.equal(await page.locator('#journey-list .journey-beat').count(), 3);
  await page.locator('#record-verification').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('#record-verification')?.textContent === 'Record integrity verified', null, { timeout: 10000 });
  assert.equal(await page.getByRole('button', { name: 'Explore digital identity' }).isEnabled(), true);
  await page.waitForTimeout(650);
  await page.screenshot({ path: resolve(output, 'farm-demo-animal-record.png'), fullPage: true });

  await page.getByRole('button', { name: 'Explore digital identity' }).click();
  await page.locator('#solana-screen').waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'Preview the flow' }).click();
  await page.getByText('Preview complete · not created').waitFor({ state: 'visible', timeout: 5000 });
  assert.equal(await page.locator('#asset-preview-public-name').textContent(), 'Animal 0');
  assert.equal(await page.getByRole('button', { name: 'Create on Devnet' }).isVisible(), true);
  assert.match(await page.locator('.asset-separation-note').textContent(), /does not verify animal history or prove physical ownership/i);
  assert.deepEqual(assetMutations, [], 'preview must not start an asset transaction');
  await page.waitForTimeout(650);
  await page.screenshot({ path: resolve(output, 'farm-demo-solana-preview.png'), fullPage: true });
  await page.getByRole('button', { name: 'Create on Devnet' }).click();
  await page.getByText(/No verified mint was recorded:/).waitFor({ state: 'visible', timeout: 15000 });
  assert.equal(await page.locator('#asset-explorer').isVisible(), false, 'wallet failure must not show a verified asset');
  assert.equal(assetMutations.length, 1, 'the attempted real flow may prepare an intent only');
  assert.match(assetMutations[0], /\/asset-intent$/);

  const video = page.video();
  await page.getByRole('button', { name: 'Back to record' }).click();
  await page.locator('#record-screen').waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'Back to farm' }).click();
  await page.locator('#farm-canvas canvas').waitFor({ state: 'visible' });
  await selectByKeyboard(1);
  await page.waitForTimeout(700);
  await mainContext.close();
  await copyFile(await video.path(), resolve(output, 'farm-demo-walkthrough.webm'));
  await rm(recordingDir, { recursive: true, force: true });

  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mobilePage = await mobileContext.newPage();
  mobilePage.on('pageerror', (error) => errors.push(error.message));
  await mobilePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await mobilePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await mobilePage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  const mobileWidth = await mobilePage.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  assert.ok(mobileWidth.scroll <= mobileWidth.client + 1, `mobile horizontal overflow: ${JSON.stringify(mobileWidth)}`);
  await mobilePage.locator('#farm-canvas').focus();
  await mobilePage.keyboard.press('ArrowRight');
  await mobilePage.locator('#farm-animal-panel').waitFor({ state: 'visible' });
  await mobilePage.waitForTimeout(450);
  await mobilePage.screenshot({ path: resolve(output, 'farm-demo-mobile.png'), fullPage: true });
  await mobileContext.close();

  const offlineContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const offlinePage = await offlineContext.newPage();
  await offlinePage.route('**/api/**', (route) => route.abort());
  await offlinePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await offlinePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await offlinePage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  await offlinePage.locator('#farm-canvas').focus();
  await offlinePage.keyboard.press('ArrowRight');
  await offlinePage.locator('#farm-animal-panel').waitFor({ state: 'visible', timeout: 10000 });
  await offlinePage.getByRole('button', { name: 'View animal record' }).click();
  await offlinePage.getByRole('heading', { name: 'Animal 0' }).waitFor({ state: 'visible' });
  await offlinePage.getByText('Record unavailable').waitFor({ state: 'visible', timeout: 10000 });
  await offlinePage.getByRole('button', { name: 'Back to farm' }).click();
  await offlinePage.locator('#farm-canvas canvas').waitFor({ state: 'visible' });
  await offlineContext.close();

  const stressContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const stressPage = await stressContext.newPage();
  await stressPage.goto(`${baseUrl}/demo?herd=100`, { waitUntil: 'domcontentloaded' });
  await stressPage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await stressPage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '100');
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
  await stressContext.close();

  const bundlePath = resolve(repository, 'src/riose/products/livestock_tracking/adapters/static/assets/farm-demo/farm-demo.js');
  const bundle = await readFile(bundlePath);
  const rawBytes = (await stat(bundlePath)).size;
  const gzipBytes = gzipSync(bundle).byteLength;
  const report = [
    '# Farm demo browser evidence',
    '',
    `- Date: ${new Date().toISOString()}`,
    `- Browser: Chromium ${browser.version()}`,
    `- Desktop view: 1440 × 960; mobile view: 390 × 844`,
    `- Herd stress run: 100 animals; browser animation-frame rate: ${performance.fps} fps; observed long tasks: ${performance.longTasks}`,
    `- Scene bundle: ${rawBytes.toLocaleString('en-US')} bytes; gzip: ${gzipBytes.toLocaleString('en-US')} bytes`,
    '- Verified in-browser: transparent isometric scene with autonomous cattle movement, keyboard selection and one-time hint dismissal, photo-backed animal card, local record verification, Solana preview with no mutation plus wallet-unavailable failure without false confirmation, mobile layout, API-independent scene startup, and 100-animal rendering.',
    '',
  ].join('\n');
  await writeFile(resolve(output, 'README.md'), report);
  assert.deepEqual(errors, [], `browser console errors: ${errors.join(' | ')}`);
  console.log(report);
} finally {
  await browser.close();
}
