const $ = (id) => document.getElementById(id);
const farmStages = new Map();
const contextRail = $('context-rail');
const firstStage = $('product-stage');
const secondStage = $('product-stage-02');
const stageElements = new Map([
  ['farm01', { id: 'farm01', stage: firstStage, canvas: $('farm-canvas'), hint: $('farm-intro-hint'),
    announce: $('selected-animal-announcement'), access: $('animal-access-list'), options: $('animal-access-options') }],
  ['farm02', { id: 'farm02', stage: secondStage, canvas: $('farm-canvas-02'), hint: $('farm-intro-hint-02'),
    announce: $('selected-animal-announcement-02'), access: $('animal-access-list-02'), options: $('animal-access-options-02') }],
]);

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

function stableNumber(value) {
  let hash = 2166136261;
  for (const char of value) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return hash >>> 0;
}

function profileFor(farmId, index, animal = null) {
  const seed = stableNumber(`${farmId}:${index}`);
  const choose = (items, offset = 0) => items[(seed + offset) % items.length];
  const displayIndex = farmId === 'farm02' ? index + 24 : index;
  const name = `Animal ${displayIndex}`;
  const tagNumber = String(displayIndex).padStart(4, '0');
  if (farmId === 'farm02') {
    const sex = seed % 5 === 0 ? 'Male' : 'Female';
    const reproductive = sex === 'Male' ? null : choose([
      'Pregnant · 146 days', 'Open', 'Recently calved · 38 days', 'Pregnant · 82 days', 'Open',
    ], 11);
    return {
      farmId, index, displayIndex, name,
      animal_id: `demo-cerrado-animal-${index}`,
      hardware_id: `demo-cerrado-tag-${tagNumber}`,
      tagLabel: `Tag #${tagNumber}`,
      image: `/assets/farm-demo/nelore/nelore-${index % 6}.png`,
      journeySource: 'illustrative',
      breed: 'Nelore', sex,
      age: `${(1.8 + (seed % 56) / 10).toFixed(1)} years`,
      health: choose(['No demo alert', 'Observation noted', 'Review planned', 'Within demo range'], 19),
      reproductive,
      condition: `${(3 + (seed % 12) / 10).toFixed(1)} / 5`,
      signal: `14:${String(seed % 60).padStart(2, '0')}`,
      location: animal?.zone || 'North range',
      journey: [],
    };
  }

  const pasture = pastureStories[(seed >>> 4) % pastureStories.length];
  const morning = choose(pasture.edges, 3);
  const midday = choose(pasture.middays, 17);
  const evening = choose(pasture.evenings, 29);
  return {
    farmId, index, displayIndex,
    animal_id: `demo-animal-${index}`,
    hardware_id: `demo-tag-${tagNumber}`,
    tagLabel: `Tag #${tagNumber}`,
    name,
    image: `/assets/demo/animal-${index % 4}.webp`,
    journeySource: 'illustrative',
    journey: [
      { moment: 'Morning', story: `Grazes near ${morning}.` },
      { moment: 'Midday', story: `Pauses for water at ${midday}, then returns to the herd.` },
      { moment: 'Evening', story: `Moves with the group toward ${evening}.` },
    ],
  };
}

const state = {
  farms: new Map(),
  animalCount: 24,
  activeFarmId: null,
  activeStage: null,
  selectedSceneAnimal: null,
  selectedProfile: null,
  animal: null,
  asset: null,
  assetStatus: 'NO_ASSET',
  assetStatusLoaded: false,
  recordDigest: null,
  identityRunId: 0,
  identityExpanded: false,
  selectionGeneration: 0,
};

const statusLabels = { IDLE: 'Resting', GRAZE: 'Grazing', WALK: 'Walking', DRINK: 'At the water point', REST: 'Resting', SHADE: 'Resting in shade' };

class FarmAudioManager {
  constructor() {
    this.audio = new Audio('/assets/farm-demo/audio/single-cow-moo.ogg');
    this.audio.preload = 'none';
    this.audio.volume = 0.055;
    this.enabled = false;
    this.unlocked = false;
    this.anyFarmVisible = true;
    this.timer = null;
    try { this.enabled = localStorage.getItem('riose:farm-audio') === 'on'; } catch {}
    this.renderButtons();
    document.addEventListener('pointerdown', () => this.unlock(), { once: true, passive: true });
    document.addEventListener('keydown', () => this.unlock(), { once: true });
    document.addEventListener('visibilitychange', () => this.schedule());
  }

  toggle() {
    this.enabled = !this.enabled;
    try { localStorage.setItem('riose:farm-audio', this.enabled ? 'on' : 'off'); } catch {}
    this.renderButtons();
    if (this.enabled) this.unlock();
    this.schedule();
  }

  setFarmVisibility(visible) {
    this.anyFarmVisible = visible;
    this.schedule();
  }

  unlock() {
    this.unlocked = true;
    this.schedule();
  }

  renderButtons() {
    for (const button of document.querySelectorAll('[data-farm-sound]')) {
      button.textContent = this.enabled ? 'Sound on' : 'Sound off';
      button.setAttribute('aria-pressed', String(this.enabled));
    }
  }

  schedule() {
    window.clearTimeout(this.timer);
    this.audio.pause();
    if (!this.enabled || !this.unlocked || !this.anyFarmVisible || document.hidden) return;
    const delay = 42000 + Math.floor(Math.random() * 36000);
    this.timer = window.setTimeout(async () => {
      if (!this.enabled || !this.anyFarmVisible || document.hidden) return;
      this.audio.currentTime = 0;
      try {
        await this.audio.play();
        this.audio.onended = () => this.schedule();
      } catch {
        this.enabled = false;
        try { localStorage.setItem('riose:farm-audio', 'off'); } catch {}
        this.renderButtons();
      }
    }, delay);
  }
}

const farmAudio = new FarmAudioManager();

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
  if (open && element.id === 'solana-screen') {
    const artwork = $('identity-art');
    if (!artwork.getAttribute('src')) artwork.src = artwork.dataset.src;
  }
}

function setMessage(id, message, status) {
  const node = $(id);
  node.textContent = message;
  if (status) node.dataset.state = status;
}

function dismissFarmHint(stage = state.activeStage) {
  const hint = stage?.hint;
  if (!hint) return;
  hint.hidden = true;
  hint.classList.remove('is-ready', 'is-typing');
  try { sessionStorage.setItem('riose:farm-hint-dismissed', '1'); } catch {}
}

function revealFarmHint(stage) {
  let dismissed = false;
  try { dismissed = sessionStorage.getItem('riose:farm-hint-dismissed') === '1'; } catch {}
  if (dismissed) return;
  const hint = stage?.hint;
  if (!hint) return;
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

function renderAnimalChooser(stage, count) {
  const options = stage.options;
  const offset = stage.id === 'farm02' ? 24 : 0;
  options.replaceChildren(...Array.from({ length: count }, (_, index) => {
    const item = document.createElement('div');
    item.setAttribute('role', 'listitem');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'animal-access-option';
    button.textContent = `Animal ${index + offset}`;
    button.dataset.animalId = `${stage.id}-animal-${index}`;
    button.addEventListener('click', () => {
      stage.access.open = false;
      state.farms.get(stage.id)?.selectAnimal(button.dataset.animalId);
    });
    item.append(button);
    return item;
  }));
}

function updateAnimalChooserSelection(stage, id) {
  for (const button of stage.options.querySelectorAll('button')) {
    const selected = button.dataset.animalId === id;
    button.setAttribute('aria-pressed', String(selected));
  }
}

function resetIdentityCard(profile) {
  state.asset = null;
  state.assetStatus = 'NO_ASSET';
  state.assetStatusLoaded = false;
  state.recordDigest = null;
  state.identityRunId += 1;
  $('asset-complete').hidden = true;
  $('asset-progress').hidden = true;
  $('asset-actions').hidden = false;
  $('asset-error').hidden = true;
  $('asset-error').textContent = '';
  $('asset-action').hidden = false;
  $('asset-action').disabled = true;
  $('asset-action').textContent = 'Preparing record…';
  $('asset-explorer').hidden = true;
  $('solana-screen').dataset.proofState = 'no-asset';
  $('identity-art-wrap').classList.remove('is-assembling', 'is-confirmed');
  setProofSteps('NO_ASSET');
  $('continue-solana').textContent = 'Digital identity';
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
  $('record-portrait').classList.toggle('is-nelore', profile.farmId === 'farm02');
  $('animal-panel-body').classList.toggle('is-cerrado', profile.farmId === 'farm02');
  $('selected-animal-status').parentElement.classList.toggle('is-cerrado', profile.farmId === 'farm02');
  $('animal-journey').hidden = profile.farmId === 'farm02';
  $('cerrado-profile').hidden = profile.farmId !== 'farm02';
  if (profile.farmId === 'farm02') {
    $('journey-title').textContent = 'Cerrado profile';
    $('selected-animal-status').textContent = profile.breed + ' · ' + profile.sex + ' · ' + profile.age;
    const field = (name) => $('cerrado-profile').querySelector(`[data-cerrado="${name}"]`);
    field('health').textContent = profile.health;
    field('location').textContent = profile.location;
    field('signal').textContent = profile.signal;
    field('condition').textContent = profile.condition;
    field('tag').textContent = profile.tagLabel;
    const reproductive = $('cerrado-profile').querySelector('.reproductive-field');
    reproductive.hidden = !profile.reproductive;
    if (profile.reproductive) field('reproductive').textContent = profile.reproductive;
  } else {
    $('journey-title').textContent = 'A day in the pasture';
    $('selected-animal-status').textContent = statusLabels[state.selectedSceneAnimal?.status] || 'Resting';
    renderJourney(profile);
  }
  $('selected-animal-zone').textContent = state.selectedSceneAnimal?.zone || 'Willow meadow';
  setMessage('record-verification', 'Checking record integrity…', 'pending');
  $('api-state').hidden = true;
}

function clearAnimalSelection() {
  const previousStage = state.activeStage;
  state.selectionGeneration += 1;
  state.selectedSceneAnimal = null;
  state.selectedProfile = null;
  state.animal = null;
  state.asset = null;
  state.identityExpanded = false;
  for (const stage of stageElements.values()) updateAnimalChooserSelection(stage, null);
  setContextOpen($('record-screen'), false);
  setContextOpen($('solana-screen'), false);
  previousStage?.stage.classList.remove('has-selection');
  firstStage.classList.remove('has-selection');
  secondStage.classList.remove('has-selection');
  if (contextRail.parentElement !== firstStage) firstStage.append(contextRail);
  $('context-rail').setAttribute('aria-hidden', 'true');
  $('context-rail').inert = true;
  previousStage?.announce && (previousStage.announce.textContent = '');
  state.activeFarmId = null;
  state.activeStage = null;
}

function selectAnimal(animal) {
  if (!animal) {
    clearAnimalSelection();
    return;
  }

  const farmId = animal.farmId || 'farm01';
  const stage = stageElements.get(farmId);
  const index = Number.isInteger(animal.index) ? animal.index : Number(animal.id.match(/-(\d+)$/)?.[1] || 0);
  const profile = profileFor(farmId, index, animal);
  if (state.selectedSceneAnimal && state.selectedSceneAnimal.farmId !== farmId) {
    state.farms.get(state.selectedSceneAnimal.farmId)?.selectAnimal(null);
  }
  const requestId = ++state.selectionGeneration;
  const keepIdentityOpen = state.identityExpanded;
  state.selectedSceneAnimal = animal;
  state.activeFarmId = farmId;
  state.activeStage = stage;
  state.selectedProfile = profile;
  state.animal = null;
  state.identityExpanded = keepIdentityOpen;
  dismissFarmHint(stage);
  updateAnimalChooserSelection(stage, animal.id);
  firstStage.classList.remove('has-selection');
  secondStage.classList.remove('has-selection');
  if (contextRail.parentElement !== stage.stage) stage.stage.append(contextRail);
  stage.stage.classList.add('has-selection');
  $('context-rail').setAttribute('aria-hidden', 'false');
  $('context-rail').inert = false;
  setContextOpen($('record-screen'), true);
  setContextOpen($('solana-screen'), keepIdentityOpen);
  $('selected-animal-status').textContent = statusLabels[animal.status] || 'Resting';
  resetRecordState(profile);
  resetIdentityCard(profile);
  if (keepIdentityOpen) setContextOpen($('solana-screen'), true);
  stage.announce.textContent = `${profile.name}, ${statusLabels[animal.status] || 'Resting'}, ${animal.zone}`;
  void loadSelectedAnimal(animal, profile, requestId);
}

function publishSceneState(animals) {
  if (!animals.length) return;
  const farmId = animals[0].farmId;
  const stage = stageElements.get(farmId);
  if (!stage) return;
  stage.canvas.dataset.animalCount = String(animals.length);
  stage.canvas.dataset.movingAnimals = String(animals.filter((animal) => animal.status === 'WALK').length);
  const active = animals.find((animal) => animal.id === state.selectedSceneAnimal?.id);
  if (active && state.activeFarmId === farmId) {
    $('selected-animal-status').textContent = farmId === 'farm02'
      ? `${state.selectedProfile.breed} · ${state.selectedProfile.sex} · ${state.selectedProfile.age}`
      : statusLabels[active.status] || 'Resting';
    $('selected-animal-zone').textContent = active.zone;
    if (farmId === 'farm02') {
      $('cerrado-profile').querySelector('[data-cerrado="location"]').textContent = active.zone;
    }
  }
}

async function initFarm() {
  try {
    const { mountFarmDemo } = await import('/assets/farm-demo/farm-demo.js?v=20261008-03');
    const requestedCount = Number(new URLSearchParams(window.location.search).get('herd'));
    state.animalCount = Number.isInteger(requestedCount) && requestedCount >= 1 && requestedCount <= 100 ? requestedCount : 24;

    const mountStage = (farmId, stage, isVisible) => {
      if (farmStages.has(farmId)) return farmStages.get(farmId);
      renderAnimalChooser(stage, state.animalCount);
      const mounted = { ...stage, farm: null, isVisible, ready: false };
      farmStages.set(farmId, mounted);
      const farm = mountFarmDemo(stage.canvas, {
        farmId,
        animalCount: state.animalCount,
        onSelect: selectAnimal,
        onStates: publishSceneState,
        onReady: () => {
          stage.canvas.classList.add('is-ready');
          revealFarmHint(stage);
          mounted.ready = true;
          if (!mounted.isVisible) mounted.farm?.setActive(false);
        },
      });
      mounted.farm = farm;
      state.farms.set(farmId, farm);
      if (mounted.ready && !mounted.isVisible) farm.setActive(false);
      return mounted;
    };

    // Farm 01 is the opening scene. Defer the second Phaser scene and its
    // multi-megabyte art until its section approaches the viewport.
    mountStage('farm01', stageElements.get('farm01'), true);
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const farmId = entry.target.dataset.farmId;
        const stage = stageElements.get(farmId);
        let mounted = farmStages.get(farmId);
        if (!mounted && entry.isIntersecting && entry.intersectionRatio >= 0.1 && stage) {
          mounted = mountStage(farmId, stage, true);
        }
        if (!mounted) continue;
        mounted.isVisible = entry.isIntersecting;
        if (mounted.ready) mounted.farm?.setActive(entry.isIntersecting);
      }
      farmAudio.setFarmVisibility([...farmStages.values()].some((mounted) => mounted.isVisible));
    }, { rootMargin: '0px', threshold: [0, 0.1] });
    for (const stage of stageElements.values()) observer.observe(stage.stage);
    window.addEventListener('pagehide', () => observer.disconnect(), { once: true });
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
    state.recordDigest = verification.record_digest;
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
    if (!state.identityExpanded) {
      $('asset-action').disabled = false;
      $('asset-action').textContent = 'Create digital identity';
    }
    if (state.identityExpanded) await refreshAsset(requestId);
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    setMessage('record-verification', 'Record integrity unavailable', 'error');
    $('api-state').textContent = 'Animal record unavailable. The farm remains available.';
    $('api-state').hidden = false;
    $('asset-action').disabled = true;
    $('asset-action').textContent = 'Record unavailable';
    if (state.identityExpanded) {
      state.assetStatus = 'ERROR';
      state.assetStatusLoaded = true;
      showAssetError('Connect to the local record before creating an asset.');
    }
  }
}

function tokenizationModule() {
  return import('/assets/animal-tokenization.bundle.js?v=20261008-03');
}

function setProofSteps(phase) {
  const completed = {
    NO_ASSET: [], PREPARING_RECORD: [], HASHING: ['record'], SIGNATURE_REQUIRED: ['record', 'hash'],
    SUBMITTING_TO_DEVNET: ['record', 'hash'], CONFIRMING: ['record', 'hash', 'solana'],
    CONFIRMED: ['record', 'hash', 'solana', 'wallet'], ADDED_TO_WALLET: ['record', 'hash', 'solana', 'wallet'],
  }[phase] || [];
  const active = {
    PREPARING_RECORD: 'record', HASHING: 'hash', SIGNATURE_REQUIRED: 'wallet',
    SUBMITTING_TO_DEVNET: 'solana', CONFIRMING: 'wallet',
  }[phase];
  for (const step of document.querySelectorAll('[data-proof-step]')) {
    const name = step.dataset.proofStep;
    step.classList.toggle('is-done', completed.includes(name));
    step.classList.toggle('is-active', name === active);
  }
}

const phaseCopy = {
  PREPARING_RECORD: 'Preparing farm record', HASHING: 'Creating digest',
  SIGNATURE_REQUIRED: 'Waiting for wallet signature', SUBMITTING_TO_DEVNET: 'Anchoring on Solana',
  CONFIRMING: 'Confirming asset', CONFIRMED: 'Digital identity created', ADDED_TO_WALLET: 'Digital identity created',
};

function setAssetPhase(phase) {
  state.assetStatus = phase;
  $('solana-screen').dataset.proofState = phase.toLowerCase().replaceAll('_', '-');
  setProofSteps(phase);
  $('asset-progress').hidden = false;
  $('asset-complete').hidden = true;
  $('asset-actions').hidden = true;
  $('asset-error').hidden = true;
  $('asset-state').textContent = phaseCopy[phase] || 'Preparing digital identity';
  $('asset-state').dataset.state = phase === 'ERROR' ? 'error' : phase === 'CONFIRMED' ? 'confirmed' : 'submitting';
  $('identity-art-wrap').classList.toggle('is-assembling', !['CONFIRMED', 'ADDED_TO_WALLET'].includes(phase));
}

function updateIdentityToggle(confirmed = false) {
  const button = $('continue-solana');
  button.replaceChildren(document.createTextNode(confirmed ? 'View proof' : 'Digital identity'));
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = '↗';
  button.append(arrow);
}

async function refreshAsset(requestId = state.selectionGeneration) {
  if (!state.animal) {
    state.assetStatus = 'ERROR';
    state.assetStatusLoaded = true;
    showAssetError('Animal record unavailable. Try again when connected.');
    return;
  }

  state.assetStatusLoaded = false;
  setAssetPhase('CONFIRMING');
  $('asset-state').textContent = 'Checking Solana Devnet';
  try {
    const module = await tokenizationModule();
    const asset = await module.getAnimalAsset(state.animal.animal_id);
    if (requestId !== state.selectionGeneration) return;
    state.asset = asset;
    state.assetStatusLoaded = true;
    if (asset.valid && asset.asset_address) {
      renderCompletedIdentity(asset, module);
      updateIdentityToggle(true);
      return;
    }

    const status = asset.evidence || asset.status || 'UNREGISTERED';
    if (status === 'UNREGISTERED' || status === 'PREPARED') {
      state.assetStatus = 'NO_ASSET';
      $('solana-screen').dataset.proofState = 'no-asset';
      $('asset-progress').hidden = true;
      $('asset-actions').hidden = false;
      $('asset-action').disabled = false;
      $('asset-action').textContent = 'Create digital identity';
      updateIdentityToggle(false);
    } else {
      state.assetStatus = 'SUBMITTING';
      $('solana-screen').dataset.proofState = 'submitting';
      setAssetPhase('CONFIRMING');
      $('asset-state').textContent = 'Confirming asset';
      $('asset-actions').hidden = false;
      $('asset-action').textContent = 'Check status again';
    }
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    state.assetStatus = 'ERROR';
    state.assetStatusLoaded = true;
    showAssetError(`Devnet status unavailable: ${error.message}`);
  }
}

function showAssetError(message) {
  state.assetStatus = 'ERROR';
  $('solana-screen').dataset.proofState = 'error';
  $('asset-progress').hidden = true;
  $('asset-complete').hidden = true;
  $('asset-actions').hidden = false;
  $('asset-error').textContent = message;
  $('asset-error').hidden = false;
  $('asset-action').disabled = false;
  $('asset-action').textContent = 'Retry';
  $('identity-art-wrap').classList.remove('is-assembling');
}

function shortAddress(value, lead = 7, trail = 5) {
  return value && value.length > lead + trail + 1 ? `${value.slice(0, lead)}…${value.slice(-trail)}` : value || '—';
}

function renderCompletedIdentity(asset, module) {
  state.asset = asset;
  state.assetStatus = 'ADDED_TO_WALLET';
  state.assetStatusLoaded = true;
  $('solana-screen').dataset.proofState = 'added-to-wallet';
  setProofSteps('ADDED_TO_WALLET');
  $('asset-progress').hidden = true;
  $('asset-actions').hidden = true;
  $('asset-error').hidden = true;
  $('asset-complete').hidden = false;
  $('proof-animal-name').textContent = asset.name || state.selectedProfile?.name || 'Animal';
  $('proof-public-tag').textContent = asset.public_tag || state.selectedProfile?.tagLabel || '—';
  $('proof-record-digest').textContent = shortAddress(asset.record_digest || state.recordDigest, 12, 8);
  $('proof-record-digest').title = asset.record_digest || state.recordDigest || '';
  $('proof-transaction').textContent = shortAddress(asset.signature || asset.transaction_signature, 8, 6);
  $('proof-wallet').textContent = shortAddress(asset.owner_address, 8, 6);
  $('proof-wallet').title = asset.owner_address || '';
  const explorer = $('asset-explorer');
  explorer.href = module.assetExplorerUrl(asset.asset_address);
  explorer.hidden = false;
  $('identity-art-wrap').classList.remove('is-assembling');
  $('identity-art-wrap').classList.add('is-confirmed');
  $('asset-state').textContent = 'Digital identity created';
  $('asset-state').dataset.state = 'confirmed';
  updateIdentityToggle(true);
}

function animateIdentityLink(requestId) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const farm = state.farms.get(state.activeFarmId);
  const animalId = state.selectedSceneAnimal?.id;
  if (reduced || !animalId || !farm?.getAnimalScreenPosition) return Promise.resolve();
  const from = farm.getAnimalScreenPosition(animalId);
  const targetRect = $('identity-art-wrap').getBoundingClientRect();
  if (!from || !targetRect.width) return Promise.resolve();
  const to = { x: targetRect.left + targetRect.width / 2, y: targetRect.top + targetRect.height / 2 };
  const dx = to.x - from.x;
  const path = $('identity-motion-path');
  const group = $('identity-motion-fragments');
  const fragments = ['01', '7A', 'D4', '·'];
  path.setAttribute('d', `M ${from.x} ${from.y} C ${from.x + dx * 0.36} ${from.y - 30}, ${to.x - dx * 0.28} ${to.y + 34}, ${to.x} ${to.y}`);
  group.replaceChildren(...fragments.map((fragment, index) => {
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.textContent = fragment;
    text.dataset.index = String(index);
    return text;
  }));
  const length = path.getTotalLength();
  const duration = 1900;
  const start = performance.now();
  const overlay = $('identity-motion-overlay');
  overlay.setAttribute('viewBox', `0 0 ${window.innerWidth} ${window.innerHeight}`);
  overlay.setAttribute('preserveAspectRatio', 'none');
  overlay.classList.add('is-active');
  path.style.strokeDasharray = `${length}`;
  path.style.strokeDashoffset = `${length}`;
  path.animate([{ strokeDashoffset: length }, { strokeDashoffset: 0 }], { duration, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'forwards' });
  return new Promise((resolve) => {
    const tick = (now) => {
      if (requestId !== state.identityRunId) {
        overlay.classList.remove('is-active');
        resolve();
        return;
      }
      const progress = Math.min(1, (now - start) / duration);
      group.querySelectorAll('text').forEach((fragment) => {
        const index = Number(fragment.dataset.index);
        const point = path.getPointAtLength(Math.max(0, progress * length - index * 15));
        fragment.setAttribute('x', String(point.x));
        fragment.setAttribute('y', String(point.y - 7 - index % 2 * 8));
        fragment.style.opacity = String(Math.min(1, progress * 4, (1 - progress) * 4));
      });
      if (progress < 1) requestAnimationFrame(tick);
      else {
        overlay.classList.remove('is-active');
        $('identity-art-wrap').classList.add('is-assembling');
        resolve();
      }
    };
    requestAnimationFrame(tick);
  });
}

async function performAssetAction() {
  if (!state.selectedProfile || ['PREPARING_RECORD', 'HASHING', 'SIGNATURE_REQUIRED', 'SUBMITTING_TO_DEVNET', 'CONFIRMING'].includes(state.assetStatus)) return;
  if (!state.animal) {
    setAssetPhase('PREPARING_RECORD');
    await loadSelectedAnimal(state.selectedSceneAnimal, state.selectedProfile, state.selectionGeneration);
    return;
  }
  const requestId = state.selectionGeneration;
  const runId = ++state.identityRunId;
  state.farms.get(state.activeFarmId)?.pulseAnimalIdentity?.(state.selectedSceneAnimal?.id);
  $('identity-art-wrap').classList.remove('is-confirmed');
  $('asset-action').disabled = true;
  setAssetPhase('PREPARING_RECORD');
  try {
    const module = await tokenizationModule();
    const result = await module.mintAnimalAsset(state.animal.animal_id, {
      onProgress: async ({ state: phase, result: verified, record_digest: digest }) => {
        if (requestId !== state.selectionGeneration || runId !== state.identityRunId) return;
        if (phase === 'PREPARING_RECORD') setAssetPhase(phase);
        else if (phase === 'HASHING') {
          setAssetPhase(phase);
          if (digest || verified?.record_digest) state.recordDigest = digest || verified.record_digest;
          if (state.recordDigest) await animateIdentityLink(runId);
        } else if (phase === 'SIGNATURE_REQUIRED') {
          setAssetPhase(phase);
          if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            await new Promise((resolve) => window.setTimeout(resolve, 560));
          }
        } else if (phase === 'SUBMITTING_TO_DEVNET') {
          setAssetPhase(phase);
          if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            await new Promise((resolve) => window.setTimeout(resolve, 380));
          }
        }
        else if (phase === 'CONFIRMING') setAssetPhase(phase);
      },
    });
    if (requestId !== state.selectionGeneration) return;
    if (!result.valid || result.evidence !== 'VALIDATED_ON_DEVNET') {
      throw new Error(`The asset is not verified (${result.evidence || result.status || 'unknown state'}).`);
    }
    setAssetPhase('CONFIRMED');
    await new Promise((resolve) => window.setTimeout(resolve, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320));
    if (requestId !== state.selectionGeneration) return;
    renderCompletedIdentity(result, module);
  } catch (error) {
    if (requestId !== state.selectionGeneration) return;
    state.assetStatusLoaded = true;
    const detail = typeof error?.message === 'string' ? error.message.trim() : '';
    const fallback = state.assetStatus === 'SIGNATURE_REQUIRED'
      ? 'Wallet connection or signature did not complete. Connect a Devnet wallet and retry.'
      : ['SUBMITTING_TO_DEVNET', 'CONFIRMING'].includes(state.assetStatus)
        ? 'Devnet has not confirmed this identity yet. Check again or retry.'
        : 'The identity could not be prepared. Retry when the record is available.';
    showAssetError((detail || fallback).slice(0, 180));
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

$('close-animal-panel').addEventListener('click', () => state.farms.get(state.activeFarmId)?.selectAnimal(null));
$('continue-solana').addEventListener('click', toggleDigitalIdentity);
$('demo-main').querySelectorAll('[data-farm-sound]').forEach((button) => button.addEventListener('click', () => farmAudio.toggle()));
$('asset-action').addEventListener('click', () => {
  if (state.assetStatus === 'CONFIRMING' && state.assetStatusLoaded) void refreshAsset();
  else void performAssetAction();
});
$('copy-asset-id').addEventListener('click', async () => {
  if (!state.asset?.asset_address) return;
  try {
    await navigator.clipboard.writeText(state.asset.asset_address);
    $('copy-asset-id').textContent = 'Copied';
    window.setTimeout(() => { $('copy-asset-id').textContent = 'Copy asset ID'; }, 1600);
  } catch {
    $('copy-asset-id').textContent = 'Copy unavailable';
    window.setTimeout(() => { $('copy-asset-id').textContent = 'Copy asset ID'; }, 1600);
  }
});

document.addEventListener('pointerdown', (event) => {
  if (!state.selectedSceneAnimal || !(event.target instanceof Element)) return;
  if (event.target.closest('.farm-canvas, #context-rail, .animal-access-list, #demo-header')) return;
  state.farms.get(state.activeFarmId)?.selectAnimal(null);
});

window.addEventListener('scroll', () => {
  $('demo-header').classList.toggle('is-scrolled', window.scrollY > 72);
}, { passive: true });

void initFarm();
