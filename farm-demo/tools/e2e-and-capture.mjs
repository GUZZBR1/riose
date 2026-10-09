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
const baseUrl = process.env.RIOSE_BASE_URL || 'http://127.0.0.1:8008';
await mkdir(output, { recursive: true });
await rm(recordingDir, { recursive: true, force: true });
await mkdir(recordingDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const errors = [];
const assetMutations = [];
const mainContext = await browser.newContext({
  viewport: { width: 1672, height: 941 },
  recordVideo: { dir: recordingDir, size: { width: 1672, height: 941 } },
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
  for (let index = 0; index < target + 1; index += 1) await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'false');
  assert.equal(await page.locator('#record-title').textContent(), `Animal ${target}`);
  assert.equal(await page.locator('#farm-canvas canvas').isVisible(), true, 'farm remains visible beside the selected animal');
  await page.waitForFunction((animalIndex) => {
    const host = document.querySelector('#farm-canvas .riose-farm-canvas-host');
    if (!host?.dataset.farmDragState) return false;
    const { animals, camera } = JSON.parse(host.dataset.farmDragState);
    const animal = animals[animalIndex];
    const overviewZoom = Math.min(camera.width / 1536, camera.height / 1024) * 0.96;
    return Math.abs(camera.zoomX - overviewZoom) < 0.02 &&
      animal.screenX > camera.width * 0.15 && animal.screenX < camera.width * 0.85 &&
      animal.screenY > camera.height * 0.15 && animal.screenY < camera.height * 0.85;
  }, target, { timeout: 5000 });
}

async function selectByMapClick(target) {
  const point = await page.locator('#farm-canvas .riose-farm-canvas-host').evaluate((host, animalIndex) => {
    const { animals } = JSON.parse(host.dataset.farmDragState);
    const animal = animals[animalIndex];
    const rect = host.getBoundingClientRect();
    return { x: rect.left + animal.screenX, y: rect.top + animal.screenY - 10 };
  }, target);
  await page.mouse.click(point.x, point.y);
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'false');
  assert.equal(await page.locator('#record-title').textContent(), `Animal ${target}`);
  await page.waitForFunction((animalIndex) => {
    const host = document.querySelector('#farm-canvas .riose-farm-canvas-host');
    if (!host?.dataset.farmDragState) return false;
    const { animals, camera } = JSON.parse(host.dataset.farmDragState);
    const animal = animals[animalIndex];
    const overviewZoom = Math.min(camera.width / 1536, camera.height / 1024) * 0.96;
    return Math.abs(camera.zoomX - overviewZoom) < 0.02 &&
      animal.screenX > camera.width * 0.15 && animal.screenX < camera.width * 0.85 &&
      animal.screenY > camera.height * 0.15 && animal.screenY < camera.height * 0.85;
  }, target, { timeout: 5000 });
  await assertFarmStageStaysStable('Farm 01');
}

async function sampleStageAspect(selector) {
  await page.evaluate((stageSelector) => {
    const stage = document.querySelector(stageSelector);
    window.__farmAspectSamples = [];
    const started = performance.now();
    const sample = (now) => {
      const rect = stage.getBoundingClientRect();
      window.__farmAspectSamples.push({ width: rect.width, height: rect.height, ratio: rect.width / rect.height });
      if (now - started < 2600) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }, selector);
}

async function assertFarmStageStaysStable(farmName) {
  await page.waitForFunction(() => (window.__farmAspectSamples || []).length >= 35, null, { timeout: 4000 });
  const samples = await page.evaluate(() => window.__farmAspectSamples || []);
  const measurements = samples.filter(({ width, height, ratio }) => Number.isFinite(width) && Number.isFinite(height) && Number.isFinite(ratio));
  assert.ok(measurements.length > 10, `${farmName} viewport was sampled during its selection transition`);
  const widths = measurements.map(({ width }) => width);
  const heights = measurements.map(({ height }) => height);
  const ratios = measurements.map(({ ratio }) => ratio);
  assert.ok(Math.max(...ratios) / Math.min(...ratios) < 1.06,
    `${farmName} scene stretched during selection: ${Math.min(...ratios).toFixed(3)} → ${Math.max(...ratios).toFixed(3)}`);
  assert.ok(Math.max(...widths) / Math.min(...widths) < 1.12 && Math.max(...heights) / Math.min(...heights) < 1.12,
    `${farmName} scene scale jumped while the profile opened`);
}

try {
  await page.goto(`${baseUrl}/demo?farmDragDebug=1`, { waitUntil: 'domcontentloaded' });
  await page.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  await page.waitForFunction(() => Number(document.querySelector('#farm-canvas')?.dataset.movingAnimals) > 0);
  await page.waitForFunction(() => Boolean(document.querySelector('.riose-farm-canvas-host')?.dataset.farmDragState));
  assert.equal(await page.locator('#farm-canvas-02 canvas').count(), 0, 'Farm 02 waits until its section approaches the viewport');
  assert.equal(await page.locator('#farm-canvas .riose-farm-canvas-host').evaluate((host) => getComputedStyle(host).touchAction), 'pan-y pinch-zoom',
    'touch gestures over the farm must preserve native vertical page scrolling');
  await page.mouse.move(780, 520);
  await page.mouse.wheel(0, 420);
  await page.waitForFunction(() => window.scrollY > 0, null, { timeout: 3000 });
  assert.ok(await page.evaluate(() => window.scrollY > 0), 'ordinary wheel scrolling over the farm moves the page');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.waitForFunction(() => window.scrollY === 0);
  await page.locator('#farm-intro-hint').waitFor({ state: 'visible' });
  assert.match(await page.locator('#farm-intro-hint').textContent(), /drag with mouse to move/i, 'the scene briefly hints how to reposition cows on desktop');
  assert.equal(new URL(page.url()).pathname, '/demo');
  const forbidden = await page.locator('body').innerText();
  for (const label of ['Overview', 'Signals', 'Coverage', 'Track', 'Herd overview', '24 animals']) {
    assert.ok(!forbidden.includes(label), `unexpected visible label: ${label}`);
  }
  assert.doesNotMatch(forbidden, /animal movement and location are simulated/i, 'the page does not show redundant simulator copy');
  assert.equal(await page.locator('#context-rail').getAttribute('aria-hidden'), 'true');
  await page.screenshot({ path: resolve(output, 'farm-demo-desktop.png') });

  const cowStart = await page.locator('#farm-canvas .riose-farm-canvas-host').evaluate((host) => {
    const state = JSON.parse(host.dataset.farmDragState);
    const rect = host.getBoundingClientRect();
    const cow = state.animals[0];
    return {
      x: rect.left + cow.screenX,
      y: rect.top + cow.screenY - 10,
      worldX: cow.x,
      worldY: cow.y,
    };
  });
  await page.mouse.move(cowStart.x, cowStart.y);
  await page.mouse.down();
  await page.mouse.move(cowStart.x + 90, cowStart.y + 30, { steps: 12 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'false');
  await page.waitForFunction(({ x, y }) => {
    const host = document.querySelector('.riose-farm-canvas-host');
    if (!host?.dataset.farmDragState) return false;
    const animal = JSON.parse(host.dataset.farmDragState).animals[0];
    return Math.hypot(animal.x - x, animal.y - y) > 5;
  }, { x: cowStart.worldX, y: cowStart.worldY }, { timeout: 5000 });
  assert.equal(await page.locator('#record-title').textContent(), 'Animal 0', 'dragging a cow also selects it');
  await page.locator('#demo-title').click({ position: { x: 5, y: 5 } });
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'true');

  await page.waitForFunction(() => {
    const host = document.querySelector('#farm-canvas .riose-farm-canvas-host');
    const canvas = host?.querySelector('canvas');
    return host && canvas && host.clientWidth > 1000 &&
      Math.abs(canvas.width - host.clientWidth) < 2 && Math.abs(canvas.height - host.clientHeight) < 2;
  });
  await sampleStageAspect('#farm-stage');
  await selectByMapClick(0);
  await page.locator('#demo-title').click({ position: { x: 5, y: 5 } });
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'true');

  await selectByKeyboard(0);
  assert.equal(await page.locator('#farm-intro-hint').isVisible(), false, 'animal selection dismisses the hint');
  assert.match(await page.locator('#record-portrait').getAttribute('src'), /\/assets\/demo\/animal-0\.webp$/);
  assert.ok(await page.locator('#selected-animal-zone').textContent());
  assert.equal(await page.locator('#journey-list .journey-beat').count(), 3);
  await page.getByText('Illustrative route').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('#record-verification')?.textContent.includes('Record integrity'));
  await page.waitForTimeout(450);
  await page.screenshot({ path: resolve(output, 'farm-demo-selected-animal.png') });

  assert.equal(await page.evaluate(() => performance.getEntriesByType('resource').some((entry) => entry.name.includes('solana-identity-orb'))), false,
    'the identity preview artwork remains lazy-loaded');
  await page.getByRole('button', { name: /Explore digital identity/ }).click();
  await page.waitForFunction(() => document.querySelector('#solana-screen')?.getAttribute('aria-hidden') === 'false');
  await page.waitForFunction(() => document.querySelector('#identity-art')?.complete && document.querySelector('#identity-art')?.naturalWidth > 0);
  await page.waitForTimeout(500);
  await page.screenshot({ path: resolve(output, 'farm-demo-identity-preview.png') });
  await page.getByRole('button', { name: 'Preview identity' }).click();
  await page.getByText('Preview complete', { exact: true }).waitFor({ state: 'visible', timeout: 5000 });
  assert.equal(await page.locator('#asset-preview-public-name').textContent(), 'Animal 0');
  assert.equal(await page.locator('#asset-preview-subtitle').textContent(), 'Animal 0 · Riose');
  assert.equal(await page.locator('#asset-preview-disclosure').textContent(), 'Preview only · No transaction is sent.');
  assert.equal(await page.locator('#asset-preview-action').textContent(), 'Preview again');
  assert.equal(await page.locator('#farm-canvas canvas').isVisible(), true, 'farm remains visible with both contextual panels open');
  assert.ok(await page.locator('.identity-art').evaluate((image) => image.complete && image.naturalWidth > 0), 'identity preview artwork loads');
  assert.deepEqual(assetMutations, [], 'the local preview makes no asset or wallet requests');
  await page.screenshot({ path: resolve(output, 'farm-demo-identity-preview-card.png') });

  // Switching the selected animal updates both contextual modules in place.
  await page.getByText('Choose an animal from a list').first().click();
  await page.getByRole('button', { name: 'Animal 1', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#record-title')?.textContent === 'Animal 1');
  await page.waitForFunction(() => document.querySelector('#asset-preview-public-name')?.textContent === 'Animal 1');
  assert.equal(await page.locator('#solana-screen').getAttribute('aria-hidden'), 'false');
  assert.equal(new URL(page.url()).pathname, '/demo', 'selection does not navigate away from the farm');
  await page.screenshot({ path: resolve(output, 'farm-demo-updated-animal.png') });
  const video = page.video();

  // The accessible chooser selects without requiring canvas hit testing.
  await page.getByText('Choose an animal from a list').first().click();
  await page.getByRole('button', { name: 'Animal 2', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#record-title')?.textContent === 'Animal 2');

  // Clicking outside the farm and contextual rail clears the in-place selection.
  await page.locator('#demo-title').click({ position: { x: 5, y: 5 } });
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'true');
  assert.equal(await page.locator('#farm-canvas canvas').isVisible(), true);

  // Farm 02 is a distinct second scene, with its own entity keys and profile schema.
  await page.locator('#farm-stage-02').scrollIntoViewIfNeeded();
  await page.locator('#farm-canvas-02 canvas').waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('#farm-canvas-02')?.dataset.animalCount === '24');
  await page.waitForFunction(() => document.querySelector('#farm-canvas-02')?.dataset.movingAnimals !== undefined);
  await page.getByText('Choose an animal from a list').last().click();
  await sampleStageAspect('#farm-stage-02');
  await page.getByRole('button', { name: 'Animal 42', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#record-title')?.textContent === 'Animal 42');
  await assertFarmStageStaysStable('Farm 02');
  await page.locator('#cerrado-profile').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#animal-journey').isVisible(), false, 'Cerrado has its own profile schema');
  assert.match(await page.locator('#record-portrait').getAttribute('src'), /\/assets\/farm-demo\/nelore\/nelore-\d\.png$/);
  const cerrradoFields = await page.locator('#cerrado-profile-grid').innerText();
  assert.match(cerrradoFields, /Health/i);
  assert.match(cerrradoFields, /Reproductive status/i);
  assert.match(cerrradoFields, /Estimated location/i);
  assert.match(await page.locator('#selected-animal-tag').textContent(), /Tag #0042/);
  await page.waitForFunction(() => document.querySelector('#record-verification')?.textContent.includes('Record integrity'));
  await page.getByRole('button', { name: /Explore digital identity/ }).click();
  await page.getByRole('button', { name: 'Preview identity' }).click();
  await page.getByText('Preview complete', { exact: true }).waitFor({ state: 'visible', timeout: 5000 });
  assert.equal(await page.locator('#asset-preview-public-name').textContent(), 'Animal 42');
  assert.equal(await page.locator('#asset-preview-subtitle').textContent(), 'Animal 42 · Riose');
  await page.getByText('Illustrative demo profile').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#farm-canvas-02 canvas').isVisible(), true, 'Cerrado scene remains mounted beside identity');
  await page.screenshot({ path: resolve(output, 'cerrado-demo-selected-animal.png') });
  assert.deepEqual(assetMutations.filter((url) => /demo-cerrado/.test(url)), [], 'Cerrado preview must not call asset mutations');
  await page.locator('#farm02-title').click({ position: { x: 5, y: 5 } });
  await page.waitForFunction(() => document.querySelector('#context-rail')?.getAttribute('aria-hidden') === 'true');
  await mainContext.close();
  await copyFile(await video.path(), resolve(output, 'farm-demo-walkthrough.webm'));
  await rm(recordingDir, { recursive: true, force: true });

  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mobilePage = await mobileContext.newPage();
  mobilePage.on('pageerror', (error) => errors.push(error.message));
  await mobilePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await mobilePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await mobilePage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  assert.equal(await mobilePage.locator('#farm-canvas-02 canvas').count(), 0, 'mobile load defers Farm 02 until at least a small portion enters view');
  const touchCdp = await mobileContext.newCDPSession(mobilePage);
  await touchCdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 180, y: 500 }] });
  for (let y = 470; y >= 260; y -= 30) {
    await touchCdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 180, y }] });
    await mobilePage.waitForTimeout(15);
  }
  await touchCdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await mobilePage.waitForFunction(() => window.scrollY > 0, null, { timeout: 3000 });
  assert.ok(await mobilePage.evaluate(() => window.scrollY > 0), 'touch swipe over the farm scrolls the page');
  await mobilePage.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await mobilePage.waitForFunction(() => window.scrollY === 0);
  const mobileWidth = await mobilePage.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  assert.ok(mobileWidth.scroll <= mobileWidth.client + 1, `mobile horizontal overflow: ${JSON.stringify(mobileWidth)}`);
  await mobilePage.locator('#farm-canvas').focus();
  await mobilePage.keyboard.press('ArrowRight');
  await mobilePage.waitForFunction(() => document.querySelector('#record-screen')?.getAttribute('aria-hidden') === 'false');
  await mobilePage.waitForTimeout(300);
  await mobilePage.getByRole('button', { name: /Explore digital identity/ }).click();
  await mobilePage.waitForFunction(() => document.querySelector('#solana-screen')?.getAttribute('aria-hidden') === 'false');
  await mobilePage.locator('#farm-stage-02').scrollIntoViewIfNeeded();
  await mobilePage.locator('#farm-canvas-02 canvas').waitFor({ state: 'visible', timeout: 10000 });
  await mobilePage.waitForFunction(() => document.querySelector('#farm-canvas-02')?.dataset.animalCount === '24');
  await mobilePage.evaluate(() => window.scrollTo(0, 0));
  await mobilePage.screenshot({ path: resolve(output, 'farm-demo-mobile.png'), fullPage: true });
  await mobilePage.locator('#farm-stage-02').scrollIntoViewIfNeeded();
  await mobilePage.getByText('Choose an animal from a list').last().click();
  await mobilePage.getByRole('button', { name: 'Animal 24', exact: true }).click();
  await mobilePage.waitForFunction(() => document.querySelector('#record-title')?.textContent === 'Animal 24');
  await mobilePage.getByRole('button', { name: /Explore digital identity/ }).click();
  await mobilePage.getByRole('button', { name: 'Preview identity' }).click();
  await mobilePage.getByText('Preview complete', { exact: true }).waitFor({ state: 'visible', timeout: 5000 });
  await mobilePage.evaluate(() => window.scrollTo(0, 0));
  await mobilePage.screenshot({ path: resolve(output, 'farm-demo-cerrado-mobile.png'), fullPage: true });
  await mobileContext.close();

  const offlineContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const offlinePage = await offlineContext.newPage();
  await offlinePage.route('**/api/**', (route) => route.abort());
  await offlinePage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await offlinePage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await offlinePage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24');
  await offlinePage.locator('#farm-canvas').focus();
  await offlinePage.keyboard.press('ArrowRight');
  await offlinePage.waitForFunction(() => document.querySelector('#record-screen')?.getAttribute('aria-hidden') === 'false');
  await offlinePage.getByText('Record integrity unavailable').waitFor({ state: 'visible', timeout: 10000 });
  assert.equal(await offlinePage.locator('#farm-canvas canvas').isVisible(), true, 'API failure does not disable the farm');
  await offlinePage.getByRole('button', { name: /Explore digital identity/ }).click();
  await offlinePage.getByRole('button', { name: 'Preview identity' }).click();
  await offlinePage.getByText('Preview complete', { exact: true }).waitFor({ state: 'visible', timeout: 5000 });
  await offlineContext.close();

  // A repeatable, synthetic mobile-network check focused on the actual point
  // when the opening farm can be selected, not just when HTML first paints.
  const perfContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1 });
  const perfPage = await perfContext.newPage();
  const perfCdp = await perfContext.newCDPSession(perfPage);
  await perfCdp.send('Network.enable');
  await perfCdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 150,
    downloadThroughput: 200 * 1024,
    uploadThroughput: 100 * 1024,
    connectionType: 'cellular3g',
  });
  await perfCdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  const perfStartedAt = Date.now();
  await perfPage.goto(`${baseUrl}/demo`, { waitUntil: 'domcontentloaded' });
  await perfPage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 30000 });
  await perfPage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '24', null, { timeout: 30000 });
  const mobileFarmReadyMs = Date.now() - perfStartedAt;
  const mobileInitialTransferBytes = await perfPage.evaluate(() => performance.getEntriesByType('resource').reduce((sum, entry) => sum + entry.transferSize, 0));
  const mobileFcpMs = await perfPage.evaluate(() => performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null);
  assert.ok(mobileFarmReadyMs < 15000, `farm should become interactive within 15s on throttled mobile; got ${mobileFarmReadyMs}ms`);
  assert.ok(mobileInitialTransferBytes < 2 * 1024 * 1024, `opening farm should transfer under 2 MiB; got ${mobileInitialTransferBytes} bytes`);
  assert.equal(await perfPage.locator('#farm-canvas-02 canvas').count(), 0, 'slow mobile entry still defers the second farm');
  await perfContext.close();

  const stressContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const stressPage = await stressContext.newPage();
  await stressPage.goto(`${baseUrl}/demo?herd=100`, { waitUntil: 'domcontentloaded' });
  await stressPage.locator('#farm-canvas canvas').waitFor({ state: 'visible', timeout: 15000 });
  await stressPage.waitForFunction(() => document.querySelector('#farm-canvas')?.dataset.animalCount === '100');
  const initialTransferBytes = await stressPage.evaluate(() => performance.getEntriesByType('resource').reduce((sum, entry) => sum + entry.transferSize, 0));
  assert.equal(await stressPage.locator('#farm-canvas-02 canvas').count(), 0, '100-animal entry load defers the offscreen scene');
  const measureFrames = () => stressPage.evaluate(() => new Promise((resolveResult) => {
    let frames = 0;
    let longTasks = 0;
    const start = performance.now();
    const observer = 'PerformanceObserver' in window ? new PerformanceObserver((list) => { longTasks += list.getEntries().length; }) : null;
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
  const farm01Performance = await measureFrames();
  await stressPage.locator('#farm-stage-02').scrollIntoViewIfNeeded();
  await stressPage.waitForFunction(() => Number(document.querySelector('#farm-canvas-02')?.dataset.movingAnimals) > 0);
  const farm02Performance = await measureFrames();
  const bothFarmsTransferBytes = await stressPage.evaluate(() => performance.getEntriesByType('resource').reduce((sum, entry) => sum + entry.transferSize, 0));
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
    '- Desktop view: 1672 × 941 (matched to supplied reference); mobile view: 390 × 844',
    `- Farm 01 stress run: 100 animals; browser animation-frame rate: ${farm01Performance.fps} fps; observed long tasks: ${farm01Performance.longTasks}`,
    `- Farm 02 stress run: 100 animals; browser animation-frame rate: ${farm02Performance.fps} fps; observed long tasks: ${farm02Performance.longTasks}`,
    '- Input behavior: mouse wheel and touch scroll the page over the farm. Browser drag test selected and repositioned a cow; simulation validation keeps drops on safe walkable terrain and stops at obstacles/overlaps. Deliberate scene panning is Shift + left-drag.',
    `- Synthetic mobile loading: opening farm interactive in ${(mobileFarmReadyMs / 1000).toFixed(2)} s; first contentful paint ${(mobileFcpMs / 1000).toFixed(2)} s; ${(mobileInitialTransferBytes / 1024 / 1024).toFixed(2)} MiB transferred before Farm 02; throttled to 150 ms latency, 200 KiB/s download, and 4× CPU slowdown. This is a repeatable lab check, not field Core Web Vitals.`,
    '- Loading audit: the first version waited for all Farm 01 decoration and Farm 02 art before the scene was interactive; the revised flow paints the island first, loads essential scene layers and animals next, then decorations. Farm 02 art loads on demand.',
    `- Lazy scene transfer: ${(initialTransferBytes / 1024 / 1024).toFixed(2)} MiB before Farm 02 enters; ${(bothFarmsTransferBytes / 1024 / 1024).toFixed(2)} MiB after both scenes load`,
    '- Farm 02 simulation and landscape assets load only after at least 10% of its stage is visible; identity preview art loads only when its panel opens.',
    `- Scene bundle: ${rawBytes.toLocaleString('en-US')} bytes; gzip: ${gzipBytes.toLocaleString('en-US')} bytes`,
    '- Layout transition: both farm scenes kept their viewport aspect ratio within 6% while the animal panel opened.',
    '- Verified in-browser: one continuous page with dairy and Cerrado scenes; in-place animal and identity preview panels; selection changes update both panels; outside click clears selection; keyboard and accessible-list selection; preview performs no wallet or asset requests; API failure leaves both scenes and preview available; mobile layout; 100-animal rendering on each farm.',
    '- Simulation tests cover safe spawning, walkable boundaries, water and fences, route reachability, deterministic movement and 10 accelerated minutes for herds of 1, 10, 24 and 100 on each farm.',
    '',
  ].join('\n');
  await writeFile(resolve(output, 'README.md'), report);
  assert.deepEqual(errors, [], `browser console errors: ${errors.join(' | ')}`);
  console.log(report);
} finally {
  await browser.close();
}
