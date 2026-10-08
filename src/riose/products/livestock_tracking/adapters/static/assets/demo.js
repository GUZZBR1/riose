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
  assetPreviewComplete: false,
  assetPreviewRunning: false,
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
  setMessage('asset-state', 'Preview only · no blockchain transaction.', 'no-asset');
  updateIdentityToggle();
}

function resetRecordState(profile) {
  $('record-title').textContent = profile.name;
  $('selected-animal-tag').textContent = profile.tagLabel;
  $('record-portrait').src = profile.image;
  $('record-portrait').alt = `${profile.name}, cattle portrait`;
  $('record-portrait').classList.toggle('is-nelore', profile.farmId === 'farm02');
  $('selected-animal-status').parentElement.classList.toggle('is-cerrado', profile.farmId === 'farm02');
  $('animal-journey').hidden = profile.farmId === 'farm02';
  $('cerrado-profile').hidden = profile.farmId !== 'farm02';
  if (profile.farmId === 'farm02') {
    $('journey-title').textContent = 'Cerrado profile';
    $('selected-animal-status').textContent = profile.breed + ' · ' + profile.sex + ' · ' + profile.age;
    const field = (name) => $('cerrado-profile').querySelector(`[data-cerrado="${name}"]`);
    field('health').textContent = profile.health;
    field('activity').textContent = statusLabels[state.selectedSceneAnimal?.status] || 'Resting';
    field('location').textContent = profile.location;
    field('signal').textContent = profile.signal;
    field('condition').textContent = profile.condition;
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
      $('cerrado-profile').querySelector('[data-cerrado="activity"]').textContent = statusLabels[active.status] || 'Resting';
      $('cerrado-profile').querySelector('[data-cerrado="location"]').textContent = active.zone;
    }
  }
}

async function initFarm() {
  try {
    const { mountFarmDemo } = await import('/assets/farm-demo/farm-demo.js?v=20261007-33');
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
      setMessage('asset-state', 'Preview only · no blockchain transaction.', 'no-asset');
    }
  }
}

function updateIdentityToggle(confirmed = false) {
  const button = $('continue-solana');
  button.replaceChildren(document.createTextNode('Open identity preview'));
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = '↗';
  button.append(arrow);
}

async function refreshAsset(requestId = state.selectionGeneration) {
  if (requestId !== state.selectionGeneration) return;
  state.assetStatus = 'PREVIEW_ONLY';
  state.assetStatusLoaded = true;
  setMessage('asset-state', 'Preview only · no blockchain transaction.', 'no-asset');
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
  setMessage('asset-state', 'Preview only · no blockchain transaction.', 'no-asset');
  if (!state.assetStatusLoaded) {
    void refreshAsset(requestId);
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
$('asset-preview-action').addEventListener('click', () => void previewAsset());

document.addEventListener('pointerdown', (event) => {
  if (!state.selectedSceneAnimal || !(event.target instanceof Element)) return;
  if (event.target.closest('.farm-canvas, #context-rail, .animal-access-list, #demo-header')) return;
  state.farms.get(state.activeFarmId)?.selectAnimal(null);
});

window.addEventListener('scroll', () => {
  $('demo-header').classList.toggle('is-scrolled', window.scrollY > 72);
}, { passive: true });

void initFarm();
