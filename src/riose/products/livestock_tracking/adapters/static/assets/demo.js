const $ = (id) => document.getElementById(id);
const svgNamespace = 'http://www.w3.org/2000/svg';
const state = { animalId: null, asset: null, running: false };

async function requestJson(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return response.json();
}

function svgNode(name, attributes = {}) {
  const element = document.createElementNS(svgNamespace, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function coordinate(x, y) {
  return [58 + (Number(x) / 1000) * 604, 58 + ((1000 - Number(y)) / 1000) * 252];
}

function drawAnchors(anchors) {
  const layer = $('anchors-layer');
  layer.replaceChildren();
  anchors.forEach((anchor, index) => {
    const [x, y] = coordinate(anchor.x, anchor.y);
    const marker = svgNode('g', { class: 'anchor-marker', transform: `translate(${x} ${y})` });
    marker.append(svgNode('circle', { r: 15 }));
    const label = svgNode('text', { y: 4 });
    label.textContent = `A${index + 1}`;
    marker.append(label);
    const title = svgNode('title');
    title.textContent = `${anchor.anchor_id} · simulated receiver`;
    marker.append(title);
    layer.append(marker);
  });
}

function drawTrajectory(points) {
  const valid = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  const line = $('trajectory-line');
  const position = $('animal-position');
  const placeholder = $('animal-placeholder');
  line.setAttribute('points', valid.map((point) => coordinate(point.x, point.y).join(',')).join(' '));
  if (!valid.length) {
    position.hidden = true;
    placeholder.hidden = false;
    return;
  }
  const [x, y] = coordinate(valid.at(-1).x, valid.at(-1).y);
  position.setAttribute('cx', x);
  position.setAttribute('cy', y);
  position.hidden = false;
  placeholder.hidden = true;
}

function setRunMessage(message, isError = false) {
  const status = $('run-state');
  status.textContent = message;
  status.classList.toggle('is-error', isError);
}

function setAssetMessage(message, isError = false) {
  const status = $('asset-state');
  status.textContent = message;
  status.classList.toggle('is-error', isError);
}

function tokenizationModule() {
  return import('/assets/animal-tokenization.bundle.js');
}

function setAssetButton(label, disabled = false) {
  const button = $('asset-action');
  button.textContent = label;
  button.disabled = disabled;
}

async function refreshAsset() {
  if (!state.animalId) return;
  const explorer = $('asset-explorer');
  explorer.hidden = true;
  setAssetButton('Checking Devnet asset…', true);
  setAssetMessage('Checking the animal asset registry and Solana Devnet.');
  try {
    const module = await tokenizationModule();
    const asset = await module.getAnimalAsset(state.animalId);
    state.asset = asset;
    if (asset.valid && asset.asset_address) {
      setAssetButton('Asset verified on Devnet', true);
      setAssetMessage('The asset address, owner, metadata URI, and transaction were verified against Devnet.');
      explorer.href = module.assetExplorerUrl(asset.asset_address);
      explorer.hidden = false;
      return;
    }
    const status = asset.evidence || asset.status || 'UNREGISTERED';
    if (status === 'UNREGISTERED' || status === 'PREPARED') {
      setAssetButton('Create animal asset on Devnet');
      setAssetMessage('Optional. Connect a wallet and approve a Devnet transaction to create the generic animal asset.');
    } else {
      setAssetButton('Check asset status on Devnet');
      setAssetMessage(`The asset is not verified yet (${status}). A submitted transaction is not shown as confirmed.`);
    }
  } catch (error) {
    setAssetButton('Retry Devnet check');
    setAssetMessage(`Devnet status could not be checked: ${error.message}`, true);
  }
}

async function runScenario() {
  if (state.running) return;
  const button = $('run-scenario');
  state.running = true;
  button.disabled = true;
  button.querySelector('span:first-child').textContent = 'Running a short scenario…';
  $('stat-scenario').textContent = 'Running';
  $('stat-chain').textContent = 'Pending';
  setRunMessage('Generating a reproducible 120-second simulation. All outputs are marked SIMULATED.');
  try {
    const result = await requestJson('/api/simulation/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        width_m: 1000,
        height_m: 1000,
        animal_count: 1,
        anchor_count: 4,
        duration_s: 120,
        sample_period_s: 5,
        seed: 7,
        packet_loss_probability: 0.05,
        method: 'weighted_centroid',
      }),
    });
    if (result.evidence !== 'SIMULATED' || !result.run_id) throw new Error('The simulator did not return a labeled run.');

    const animalId = 'cow-0001';
    const profile = await requestJson(`/api/animals/${encodeURIComponent(animalId)}`);
    const [points, anchors] = await Promise.all([
      requestJson(`/api/animals/${encodeURIComponent(animalId)}/trajectory?limit=500&run_id=${encodeURIComponent(result.run_id)}`),
      requestJson('/api/anchors'),
    ]);
    if (!points.length) throw new Error('The scenario returned no receiver-derived position estimates.');

    state.animalId = animalId;
    $('animal-id').textContent = `· ${profile.animal_id}`;
    $('position-count').textContent = `${points.length} ESTIMATES · SIMULATED`;
    $('stat-positions').textContent = String(points.length);
    $('stat-scenario').textContent = 'Complete · SIMULATED';
    drawAnchors(anchors);
    drawTrajectory(points);

    const latestPoint = points.at(-1);
    const event = await requestJson('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        animal_id: animalId,
        event_type: 'SIMULATION_RUN_RECORDED',
        payload: {
          run_id: result.run_id,
          evidence: 'SIMULATED',
          estimated_positions: points.length,
          method: latestPoint.method,
        },
      }),
    });
    if (event.evidence !== 'SIMULATED' || event.chain_valid !== true) {
      throw new Error('The run record was saved, but the local event chain did not verify.');
    }

    const verification = await requestJson(`/api/animals/${encodeURIComponent(animalId)}/events/verify`);
    if (!verification.valid || verification.evidence !== 'LOCAL_HASH_CHAIN') {
      throw new Error('The saved run record could not be verified in the local hash chain.');
    }
    $('stat-chain').textContent = 'Verified · local';
    $('chain-detail').textContent = `Run ${result.run_id.slice(0, 12)}… recorded as SIMULATED. Local hash-chain verification passed; this is not an on-chain event.`;
    setRunMessage('Scenario complete. Receiver-derived estimates and the local event record are ready to inspect.');
    await refreshAsset();
  } catch (error) {
    $('stat-scenario').textContent = 'Unavailable';
    $('stat-chain').textContent = 'Not verified';
    setRunMessage(`The scenario could not be completed: ${error.message}`, true);
  } finally {
    state.running = false;
    button.disabled = false;
    button.querySelector('span:first-child').textContent = 'Run the movement scenario';
  }
}

async function performAssetAction() {
  if (!state.animalId) return;
  const button = $('asset-action');
  button.disabled = true;
  setAssetMessage('Waiting for wallet approval and Devnet confirmation.');
  try {
    const module = await tokenizationModule();
    const result = await module.mintAnimalAsset(state.animalId);
    if (!result.valid || result.evidence !== 'VALIDATED_ON_DEVNET') {
      throw new Error(`The asset is not verified (${result.evidence || result.status || 'unknown state'}).`);
    }
    await refreshAsset();
  } catch (error) {
    setAssetMessage(`No verified mint was recorded: ${error.message}`, true);
    button.disabled = false;
    button.textContent = 'Retry or check asset status';
  }
}

$('run-scenario').addEventListener('click', runScenario);
$('asset-action').addEventListener('click', () => {
  if (state.asset?.valid) return;
  if (state.asset?.status && state.asset.status !== 'UNREGISTERED' && state.asset.status !== 'PREPARED') {
    void refreshAsset();
    return;
  }
  void performAssetAction();
});

window.addEventListener('scroll', () => {
  $('demo-header').classList.toggle('is-scrolled', window.scrollY > 72);
}, { passive: true });

requestJson('/api/health')
  .then(() => setRunMessage('Local simulator connected. The next run is reproducible and labeled SIMULATED.'))
  .catch(() => setRunMessage('The API is unavailable. Start the local RIOSE app to run the demo.', true));
