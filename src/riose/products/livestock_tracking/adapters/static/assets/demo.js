const $ = (id) => document.getElementById(id);

const pastureStories = [
  {
    edges: ['the willow shade', 'the orchard edge', 'the pond-side grass', 'the old fence line', 'the meadow clearing', 'the lower gate'],
    middays: ['the pond edge', 'the shaded water point', 'the meadow trough', 'the willow trees', 'the barn-side path', 'the quiet clearing'],
    evenings: ['the barn-side yard', 'the orchard shade', 'the meadow shelter', 'the upper path', 'the willow edge', 'the pond-side grass'],
  },
  {
    edges: ['the tall grass edge', 'the eastern tree line', 'the open meadow', 'the north gate', 'the long-grass clearing', 'the path to the shed'],
    middays: ['the eastern water point', 'the shaded trough', 'the old oak', 'the meadow path', 'the field shed', 'the open clearing'],
    evenings: ['the long-grass shelter', 'the eastern tree line', 'the barn-side yard', 'the north gate', 'the meadow path', 'the shaded edge'],
  },
  {
    edges: ['the southern tree line', 'the open meadow', 'the south gate', 'the orchard edge', 'the long-grass patch', 'the lower path'],
    middays: ['the southern trough', 'the willow edge', 'the shaded water point', 'the meadow path', 'the lower gate', 'the quiet clearing'],
    evenings: ['the southern shelter', 'the barn-side path', 'the tree line', 'the south gate', 'the meadow clearing', 'the shaded edge'],
  },
  {
    edges: ['the creek-side grass', 'the eastern fence', 'the willow bend', 'the south gate', 'the open paddock', 'the field shed'],
    middays: ['the creek water point', 'the shaded trough', 'the lower pasture path', 'the willow edge', 'the shed yard', 'the grass clearing'],
    evenings: ['the creek-side shelter', 'the barn-side path', 'the shaded bend', 'the eastern fence', 'the lower gate', 'the willow edge'],
  },
];

function profileFor(index) {
  const pasture = pastureStories[index % pastureStories.length];
  const route = Math.floor(index / pastureStories.length) % pasture.edges.length;
  const name = `Animal ${index}`;
  return {
    index,
    animal_id: `demo-animal-${index}`,
    hardware_id: `demo-tag-${String(index).padStart(4, '0')}`,
    tagLabel: `Tag #${String(index).padStart(4, '0')}`,
    name,
    image: `/assets/demo/animal-${index % 4}.webp`,
    journeySource: 'illustrative',
    journey: [
      { moment: 'Morning', story: `Grazes near ${pasture.edges[route]}.` },
      { moment: 'Midday', story: `Pauses for water at ${pasture.middays[route]}, then returns to the herd.` },
      { moment: 'Evening', story: `Moves with the group toward ${pasture.evenings[route]}.` },
    ],
  };
}

const state = {
  farm: null,
  animalCount: 24,
  selectedSceneAnimal: null,
  selectedProfile: null,
  animal: null,
  asset: null,
  assetStatus: 'NO_ASSET',
  assetStatusLoaded: false,
  assetPreviewComplete: false,
  assetPreviewRunning: false,
  identityExpanded: false,
  selectionGeneration: 0,
};

const statusLabels = { IDLE: 'Resting', GRAZE: 'Grazing', WALK: 'Walking', DRINK: 'At the water point', REST: 'Resting' };

async function requestJson(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return response.json();
}

function setContextOpen(element, open) {
  element.classList.toggle('is-open', open);
  element.setAttribute('aria-hidden', String(!open));
  element.inert = !open;
}

function setMessage(id, message, status) {
  const node = $(id);
  node.textContent = message;
  if (status) node.dataset.state = status;
}

function dismissFarmHint() {
  const hint = $('farm-intro-hint');
  hint.hidden = true;
  hint.classList.remove('is-ready', 'is-typing');
  try { sessionStorage.setItem('riose:farm-hint-dismissed', '1'); } catch {}
}

function revealFarmHint() {
  let dismissed = false;
  try { dismissed = sessionStorage.getItem('riose:farm-hint-dismissed') === '1'; } catch {}
  if (dismissed) return;
  const hint = $('farm-intro-hint');
  hint.hidden = false;
  hint.classList.add('is-ready', 'is-typing');
  window.setTimeout(() => hint.classList.remove('is-typing'), 1400);
}

function renderJourney(profile) {
  const list = $('journey-list');
  list.replaceChildren(...profile.journey.map(({ moment, story }) => {
    const item = document.createElement('li');
    item.className = 'journey-beat';
    const label = document.createElement('span');
    label.className = 'journey-moment';
    label.textContent = moment;
    const copy = document.createElement('p');
    copy.className = 'journey-copy';
    copy.textContent = story;
    item.append(label, copy);
    return item;
  }));
}

function renderAnimalChooser(count) {
  const options = $('animal-access-options');
  options.replaceChildren(...Array.from({ length: count }, (_, index) => {
    const item = document.createElement('div');
    item.setAttribute('role', 'listitem');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'animal-access-option';
    button.textContent = `Animal ${index}`;
    button.addEventListener('click', () => {
      $('animal-access-list').open = false;
      state.farm?.selectAnimal(`animal-${index}`);
    });
    item.append(button);
    return item;
  }));
}

function updateAnimalChooserSelection(id) {
  for (const button of $('animal-access-options').querySelectorAll('button')) {
    const selected = button.textContent === (id ? `Animal ${id.slice('animal-'.length)}` : '');
    button.setAttribute('aria-pressed', String(selected));
  }
}

function resetIdentityCard(profile) {
  state.asset = null;
  state.assetStatus = 'NO_ASSET';
  state.assetStatusLoaded = false;
  state.assetPreviewComplete = false;
  state.assetPreviewRunning = false;
  $('asset-preview-public-name').textContent = profile.name;
  $('asset-preview-portrait').src = profile.image;
  $('asset-preview-card').hidden = true;
  $('asset-preview-card').classList.remove('is-revealed');
  $('asset-preview-status').hidden = true;
  $('asset-preview-status').textContent = '';
  $('asset-preview-action').hidden = false;
  $('asset-preview-action').disabled = false;
  $('asset-preview-action').textContent = 'Preview asset';
  $('asset-action').hidden = true;
  $('asset-action').disabled = false;
  $('asset-explorer').hidden = true;
  setMessage('asset-state', 'Digital identity not created.', 'no-asset');
  $('continue-solana').textContent = 'Create digital identity';
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = '↗';
  $('continue-solana').append(arrow);
}

function resetRecordState(profile) {
  $('record-title').textContent = profile.name;
  $('selected-animal-tag').textContent = profile.tagLabel;
  $('record-portrait').src = profile.image;
  $('record-portrait').alt = `${profile.name}, cattle portrait`;
  renderJourney(profile);
  setMessage('record-verification', 'Checking record integrity…', 'pending');
  $('api-state').hidden = true;
}

function clearAnimalSelection() {
  state.selectionGeneration += 1;
  state.selectedSceneAnimal = null;
  state.selectedProfile = null;
  state.animal = null;
  state.asset = null;
  state.identityExpanded = false;
  updateAnimalChooserSelection(null);
  setContextOpen($('record-screen'), false);
  setContextOpen($('solana-screen'), false);
  $('product-stage').classList.remove('has-selection');
  $('context-rail').setAttribute('aria-hidden', 'true');
  $('context-rail').inert = true;
  $('selected-animal-announcement').textContent = '';
}

function selectAnimal(animal) {
  if (!animal) {
    clearAnimalSelection();
    return;
  }

  const index = Number(animal.id.replace('animal-', '')) || 0;
  const profile = profileFor(index);
  const requestId = ++state.selectionGeneration;
  const keepIdentityOpen = state.identityExpanded;
  state.selectedSceneAnimal = animal;
  state.selectedProfile = profile;
  state.animal = null;
  state.identityExpanded = keepIdentityOpen;
  dismissFarmHint();
  updateAnimalChooserSelection(animal.id);
  $('product-stage').classList.add('has-selection');
  $('context-rail').setAttribute('aria-hidden', 'false');
  $('context-rail').inert = false;
  setContextOpen($('record-screen'), true);
  setContextOpen($('solana-screen'), keepIdentityOpen);
  $('selected-animal-status').textContent = statusLabels[animal.status] || 'Resting';
  $('selected-animal-zone').textContent = animal.zone;
  resetRecordState(profile);
  resetIdentityCard(profile);
  if (keepIdentityOpen) setContextOpen($('solana-screen'), true);
  $('selected-animal-announcement').textContent = `${animal.label}, ${statusLabels[animal.status] || 'Resting'}, ${animal.zone}`;
  void loadSelectedAnimal(animal, profile, requestId);
}

function publishSceneState(animals) {
  $('farm-canvas').dataset.animalCount = String(animals.length);
  $('farm-canvas').dataset.movingAnimals = String(animals.filter((animal) => animal.status === 'WALK').length);
}

async function initFarm() {
  try {
    const { mountFarmDemo } = await import('/assets/farm-demo/farm-demo.js?v=20261007-16');
    const requestedCount = Number(new URLSearchParams(window.location.search).get('herd'));
    state.animalCount = Number.isInteger(requestedCount) && requestedCount >= 1 && requestedCount <= 100 ? requestedCount : 24;
    renderAnimalChooser(state.animalCount);
    state.farm = mountFarmDemo($('farm-canvas'), {
      animalCount: state.animalCount,
      onSelect: selectAnimal,
      onStates: publishSceneState,
      onReady: revealFarmHint,
    });
  } catch (error) {
    const fallback = document.createElement('p');
    fallback.className = 'farm-load-error';
    fallback.setAttribute('role', 'status');
    fallback.textContent = 'The farm scene could not load. Refresh to try again.';
    $('farm-stage').append(fallback);
  }
}

async function ensureAnimal(profile) {
  const stored = await requestJson('/api/animals');
  const existing = stored.find((animal) => animal.animal_id === profile.animal_id || animal.hardware_id === profile.hardware_id);
  if (existing) return requestJson(`/api/animals/${encodeURIComponent(existing.animal_id)}`);
  try {
    return await requestJson('/api/animals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animal_id: profile.animal_id, hardware_id: profile.hardware_id, name: profile.name }),
    });
  } catch (error) {
    const afterConflict = await requestJson('/api/animals');
    const created = afterConflict.find((animal) => animal.animal_id === profile.animal_id || animal.hardware_id === profile.hardware_id);
    if (!created) throw error;
    return requestJson(`/api/animals/${encodeURIComponent(created.animal_id)}`);
  }
}

async function verifyRecord(animalId, requestId) {
  try {
    const verification = await requestJson(`/api/animals/${encodeURIComponent(animalId)}/events/verify`);
    if (requestId !== state.selectionGeneration) return;
    if (verification.valid !== true || verification.evidence !== 'LOCAL_HASH_CHAIN') {
      throw new Error('The local record did not verify.');
    }
    setMessage('record-verification', 'Record integrity verified', 'verified');
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    setMessage('record-verification', 'Record integrity unavailable', 'error');
    $('api-state').textContent = 'The local animal record could not be verified.';
    $('api-state').hidden = false;
  }
}

async function loadSelectedAnimal(sceneAnimal, profile, requestId) {
  try {
    const animal = await ensureAnimal(profile);
    if (requestId !== state.selectionGeneration) return;
    state.animal = animal;
    await verifyRecord(animal.animal_id, requestId);
    if (requestId !== state.selectionGeneration) return;
    if (state.identityExpanded) await refreshAsset(requestId);
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    setMessage('record-verification', 'Record integrity unavailable', 'error');
    $('api-state').textContent = 'Animal record unavailable. The farm remains available.';
    $('api-state').hidden = false;
    if (state.identityExpanded) {
      state.assetStatus = 'ERROR';
      state.assetStatusLoaded = true;
      setMessage('asset-state', 'Connect to the local record before creating an asset.', 'error');
    }
  }
}

function tokenizationModule() {
  return import('/assets/animal-tokenization.bundle.js?v=20261007-13');
}

function setAssetButton(label, { disabled = false, hidden = false } = {}) {
  const button = $('asset-action');
  button.textContent = label;
  button.disabled = disabled;
  button.hidden = hidden;
}

function updateIdentityToggle(confirmed = false) {
  const button = $('continue-solana');
  button.replaceChildren(document.createTextNode(confirmed ? 'View digital identity' : 'Create digital identity'));
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = '↗';
  button.append(arrow);
}

async function refreshAsset(requestId = state.selectionGeneration) {
  $('asset-explorer').hidden = true;
  if (!state.animal) {
    state.assetStatus = 'ERROR';
    state.assetStatusLoaded = true;
    setMessage('asset-state', 'Animal record unavailable. Try again when connected.', 'error');
    setAssetButton('Retry Devnet check', { hidden: !state.assetPreviewComplete });
    return;
  }

  state.assetStatusLoaded = false;
  setMessage('asset-state', 'Checking Solana Devnet…', 'checking');
  setAssetButton('Checking Devnet…', { disabled: true, hidden: !state.assetPreviewComplete });
  try {
    const module = await tokenizationModule();
    const asset = await module.getAnimalAsset(state.animal.animal_id);
    if (requestId !== state.selectionGeneration) return;
    state.asset = asset;
    state.assetStatusLoaded = true;
    if (asset.valid && asset.asset_address) {
      state.assetStatus = 'CONFIRMED';
      setMessage('asset-state', 'Verified on Solana Devnet.', 'confirmed');
      setAssetButton('Asset verified', { disabled: true, hidden: true });
      const explorer = $('asset-explorer');
      explorer.href = module.assetExplorerUrl(asset.asset_address);
      explorer.hidden = false;
      updateIdentityToggle(true);
      return;
    }

    const status = asset.evidence || asset.status || 'UNREGISTERED';
    if (status === 'UNREGISTERED' || status === 'PREPARED') {
      state.assetStatus = state.assetPreviewComplete ? 'SIGNATURE_REQUIRED' : 'NO_ASSET';
      setMessage('asset-state', state.assetPreviewComplete ? 'A wallet signature is required to create this identity.' : 'Digital identity not created.', state.assetStatus === 'SIGNATURE_REQUIRED' ? 'signature-required' : 'no-asset');
      setAssetButton('Create asset', { hidden: !state.assetPreviewComplete });
      updateIdentityToggle(false);
    } else {
      state.assetStatus = 'SUBMITTING';
      setMessage('asset-state', 'A submitted transaction is still awaiting verification.', 'submitting');
      setAssetButton('Check status again', { hidden: !state.assetPreviewComplete });
    }
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    state.assetStatus = 'ERROR';
    state.assetStatusLoaded = true;
    setMessage('asset-state', `Devnet status unavailable: ${error.message}`, 'error');
    setAssetButton('Retry Devnet check', { hidden: !state.assetPreviewComplete });
  }
}

function waitForPreviewBeat(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function previewAsset() {
  if (state.assetPreviewRunning || !state.selectedProfile) return;
  const requestId = state.selectionGeneration;
  state.assetPreviewRunning = true;
  state.assetPreviewComplete = false;
  state.assetStatus = 'PREVIEW';
  const button = $('asset-preview-action');
  const card = $('asset-preview-card');
  const status = $('asset-preview-status');
  button.disabled = true;
  button.textContent = 'Preparing preview…';
  $('asset-action').hidden = true;
  card.hidden = false;
  card.classList.remove('is-revealed');
  void card.offsetWidth;
  card.classList.add('is-revealed');
  status.hidden = false;
  const beat = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 480;
  status.textContent = 'Showing the public identity';
  await waitForPreviewBeat(beat);
  if (requestId !== state.selectionGeneration) return;
  status.textContent = 'Keeping farm data private';
  await waitForPreviewBeat(beat);
  if (requestId !== state.selectionGeneration) return;
  status.textContent = 'Preview complete · not created';
  state.assetPreviewComplete = true;
  state.assetPreviewRunning = false;
  button.disabled = false;
  button.textContent = 'Replay preview';
  if (state.assetStatusLoaded && state.assetStatus !== 'ERROR' && state.assetStatus !== 'SUBMITTING') {
    if (state.assetStatus !== 'CONFIRMED') {
      state.assetStatus = 'SIGNATURE_REQUIRED';
      setMessage('asset-state', 'A wallet signature is required to create this identity.', 'signature-required');
      setAssetButton('Create asset');
    }
  } else if (!state.assetStatusLoaded) {
    void refreshAsset(requestId);
  }
}

async function performAssetAction() {
  if (!state.animal || !state.assetPreviewComplete || state.assetStatus !== 'SIGNATURE_REQUIRED') return;
  const requestId = state.selectionGeneration;
  state.assetStatus = 'SUBMITTING';
  setAssetButton('Waiting for wallet…', { disabled: true });
  setMessage('asset-state', 'The identity is confirmed only after Devnet verification.', 'submitting');
  try {
    const module = await tokenizationModule();
    const result = await module.mintAnimalAsset(state.animal.animal_id);
    if (requestId !== state.selectionGeneration) return;
    if (!result.valid || result.evidence !== 'VALIDATED_ON_DEVNET') {
      throw new Error(`The asset is not verified (${result.evidence || result.status || 'unknown state'}).`);
    }
    await refreshAsset(requestId);
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    state.assetStatus = 'ERROR';
    state.assetStatusLoaded = true;
    setMessage('asset-state', `Creation not confirmed: ${error.message}`, 'error');
    setAssetButton('Retry Devnet check');
  }
}

function toggleDigitalIdentity() {
  state.identityExpanded = !state.identityExpanded;
  $('continue-solana').setAttribute('aria-expanded', String(state.identityExpanded));
  setContextOpen($('solana-screen'), state.identityExpanded);
  if (!state.identityExpanded) return;
  if (state.assetStatusLoaded) return;
  void refreshAsset();
}

$('close-animal-panel').addEventListener('click', () => state.farm?.selectAnimal(null));
$('continue-solana').addEventListener('click', toggleDigitalIdentity);
$('asset-preview-action').addEventListener('click', () => void previewAsset());
$('asset-action').addEventListener('click', () => {
  if (state.assetStatus === 'SIGNATURE_REQUIRED' && state.assetPreviewComplete) void performAssetAction();
  else void refreshAsset();
});

document.addEventListener('pointerdown', (event) => {
  if (!state.selectedSceneAnimal || !(event.target instanceof Element)) return;
  if (event.target.closest('#farm-canvas, #context-rail, #animal-access-list, #demo-header')) return;
  state.farm?.selectAnimal(null);
});

window.addEventListener('scroll', () => {
  $('demo-header').classList.toggle('is-scrolled', window.scrollY > 72);
}, { passive: true });

void initFarm();
