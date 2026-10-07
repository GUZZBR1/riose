const $ = (id) => document.getElementById(id);
const pastureStories = [
  {
    zone: 'Willow meadow',
    edges: ['the willow shade', 'the orchard edge', 'the pond-side grass', 'the old fence line', 'the meadow clearing', 'the lower gate'],
    middays: ['the pond edge', 'the shaded water point', 'the meadow trough', 'the willow trees', 'the barn-side path', 'the quiet clearing'],
    evenings: ['the barn-side yard', 'the orchard shade', 'the meadow shelter', 'the upper path', 'the willow edge', 'the pond-side grass'],
  },
  {
    zone: 'Long grass',
    edges: ['the tall grass edge', 'the eastern tree line', 'the open meadow', 'the north gate', 'the long-grass clearing', 'the path to the shed'],
    middays: ['the eastern water point', 'the shaded trough', 'the old oak', 'the meadow path', 'the field shed', 'the open clearing'],
    evenings: ['the long-grass shelter', 'the eastern tree line', 'the barn-side yard', 'the north gate', 'the meadow path', 'the shaded edge'],
  },
  {
    zone: 'South meadow',
    edges: ['the southern tree line', 'the open meadow', 'the south gate', 'the orchard edge', 'the long-grass patch', 'the lower path'],
    middays: ['the southern trough', 'the willow edge', 'the shaded water point', 'the meadow path', 'the lower gate', 'the quiet clearing'],
    evenings: ['the southern shelter', 'the barn-side path', 'the tree line', 'the south gate', 'the meadow clearing', 'the shaded edge'],
  },
  {
    zone: 'Creek paddock',
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
    name,
    image: `/assets/demo/animal-${index % 4}.webp`,
    journey: [
      { moment: 'Morning', story: `Starts near ${pasture.edges[route]}, then moves into the open pasture to graze.` },
      { moment: 'Midday', story: `Walks to ${pasture.middays[route]}, pauses for water, then returns to the herd.` },
      { moment: 'Evening', story: `Follows the group toward ${pasture.evenings[route]} as the day winds down.` },
    ],
  };
}

const state = {
  selected: profileFor(0),
  animal: null,
  asset: null,
  busy: false,
  farm: null,
  sceneAnimals: [],
  selectedSceneAnimal: null,
  rosterButtons: new Map(),
};
const screens = ['farm-screen', 'record-screen', 'solana-screen'];
const modeCaptions = {
  overview: 'Herd overview',
  signals: 'Local signal estimate',
  coverage: 'Estimated anchor coverage',
  track: 'Select an animal to track',
};
const statusLabels = { IDLE: 'Resting', GRAZE: 'Grazing', WALK: 'Walking', DRINK: 'At the water point' };
const signalLabels = { strong: 'Strong local estimate', moderate: 'Moderate local estimate', edge: 'Coverage edge' };

async function requestJson(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return response.json();
}

function setMessage(id, message, isError = false) {
  const node = $(id);
  node.textContent = message;
  node.classList.toggle('is-error', isError);
}

function showScreen(screenId) {
  for (const id of screens) {
    const screen = $(id);
    screen.hidden = id !== screenId;
    if (id === screenId) {
      screen.classList.remove('is-entering');
      void screen.offsetWidth;
      screen.classList.add('is-entering');
    }
  }
  window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  const focusTarget = screenId === 'farm-screen'
    ? $('farm-roster-toggle')
    : $(screenId === 'record-screen' ? 'record-title' : 'solana-title');
  if (focusTarget) requestAnimationFrame(() => focusTarget.focus({ preventScroll: true }));
}

function setMode(mode) {
  state.farm?.setMode(mode);
  document.querySelectorAll('[data-farm-mode]').forEach((button) => {
    const active = button.dataset.farmMode === mode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  $('farm-mode-caption').textContent = mode === 'track' && state.selectedSceneAnimal
    ? `Tracking ${state.selectedSceneAnimal.label}`
    : modeCaptions[mode];
}

function updateAnimalPanel(animal) {
  state.selectedSceneAnimal = animal;
  const panel = $('farm-animal-panel');
  if (!animal) {
    panel.hidden = true;
    $('farm-mode-caption').textContent = modeCaptions.track;
    return;
  }
  panel.hidden = false;
  $('selected-animal-name').textContent = animal.label;
  $('selected-animal-zone').textContent = animal.zone;
  $('selected-animal-status').textContent = statusLabels[animal.status] || 'Moving';
  $('selected-animal-position').textContent = animal.zone;
  $('selected-animal-signal').textContent = signalLabels[animal.signalLevel] || 'Local estimate';
  if (document.querySelector('[data-farm-mode="track"]')?.getAttribute('aria-pressed') === 'true') {
    $('farm-mode-caption').textContent = `Tracking ${animal.label}`;
  }
  for (const [id, button] of state.rosterButtons) {
    button.setAttribute('aria-selected', String(id === animal.id));
  }
}

function chooseAnimal(animal) {
  if (!animal) return;
  state.farm?.selectAnimal(animal.id);
  updateAnimalPanel(animal);
}

function rosterKeydown(event, button) {
  const buttons = [...$('farm-roster').querySelectorAll('button')];
  const current = buttons.indexOf(button);
  let next = current;
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (current + 1) % buttons.length;
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (current - 1 + buttons.length) % buttons.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = buttons.length - 1;
  else if (event.key === 'Escape') {
    $('farm-roster').hidden = true;
    $('farm-roster-toggle').setAttribute('aria-expanded', 'false');
    $('farm-roster-toggle').focus();
    event.preventDefault();
    return;
  } else return;
  event.preventDefault();
  buttons[next]?.focus();
}

function renderRoster(animals) {
  state.sceneAnimals = animals;
  $('farm-animal-count').textContent = String(animals.length);
  $('farm-roster-count').textContent = String(animals.length);
  const roster = $('farm-roster');
  for (const animal of animals) {
    let button = state.rosterButtons.get(animal.id);
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.role = 'option';
      button.setAttribute('aria-selected', 'false');
      button.dataset.animalId = animal.id;
      button.tabIndex = -1;
      const name = document.createElement('span');
      name.className = 'roster-animal-name';
      name.textContent = animal.label;
      const status = document.createElement('span');
      status.className = 'roster-animal-status';
      button.append(name, status);
      button.addEventListener('click', () => chooseAnimal(state.sceneAnimals.find((item) => item.id === button.dataset.animalId)));
      button.addEventListener('keydown', (event) => rosterKeydown(event, button));
      roster.append(button);
      state.rosterButtons.set(animal.id, button);
    }
    button.querySelector('.roster-animal-status').textContent = `${statusLabels[animal.status] || 'Moving'} · ${animal.zone}`;
    button.setAttribute('aria-selected', String(state.selectedSceneAnimal?.id === animal.id));
  }
}

async function initFarm() {
  try {
    const { mountFarmDemo } = await import('/assets/farm-demo/farm-demo.js');
    const requestedCount = Number(new URLSearchParams(window.location.search).get('herd'));
    const animalCount = Number.isInteger(requestedCount) && requestedCount >= 1 && requestedCount <= 100
      ? requestedCount
      : 24;
    state.farm = mountFarmDemo($('farm-canvas'), {
      animalCount,
      onSelect: updateAnimalPanel,
      onStates: renderRoster,
    });
    setMode('overview');
  } catch (error) {
    const fallback = document.createElement('p');
    fallback.className = 'farm-load-error';
    fallback.setAttribute('role', 'status');
    fallback.textContent = 'The farm scene could not load. Refresh to try again.';
    $('farm-stage').append(fallback);
  }
}

async function ensureAnimal(sample) {
  const stored = await requestJson('/api/animals');
  const existing = stored.find((animal) => animal.animal_id === sample.animal_id || animal.hardware_id === sample.hardware_id);
  if (existing) return requestJson(`/api/animals/${encodeURIComponent(existing.animal_id)}`);
  try {
    return await requestJson('/api/animals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animal_id: sample.animal_id, hardware_id: sample.hardware_id, name: sample.name }),
    });
  } catch (error) {
    const afterConflict = await requestJson('/api/animals');
    const created = afterConflict.find((animal) => animal.animal_id === sample.animal_id || animal.hardware_id === sample.hardware_id);
    if (!created) throw error;
    return requestJson(`/api/animals/${encodeURIComponent(created.animal_id)}`);
  }
}

function renderJourney(sample) {
  const list = $('journey-list');
  list.replaceChildren(...sample.journey.map(({ moment, story }) => {
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

function renderProfile(sample) {
  $('continue-solana').disabled = true;
  $('record-title').textContent = sample.name;
  $('record-portrait').src = sample.image;
  $('record-portrait').alt = `${sample.name}, cattle portrait`;
  renderJourney(sample);
  $('asset-animal-name').textContent = sample.name;
  $('record-verification').textContent = 'Checking record…';
  $('record-verification').classList.remove('is-verified', 'is-error');
  $('record-verification').classList.add('is-pending');
  $('api-state').hidden = true;
}

function renderAnimal(animal, sample) {
  state.animal = animal;
  $('continue-solana').disabled = false;
  $('asset-animal-name').textContent = sample.name;
}

async function verifyRecord(animalId) {
  const status = $('record-verification');
  status.textContent = 'Checking record…';
  status.classList.remove('is-verified', 'is-error');
  status.classList.add('is-pending');
  try {
    const verification = await requestJson(`/api/animals/${encodeURIComponent(animalId)}/events/verify`);
    if (verification.valid !== true || verification.evidence !== 'LOCAL_HASH_CHAIN') {
      throw new Error('The local event history did not verify.');
    }
    status.textContent = 'Record integrity verified';
    status.classList.remove('is-pending');
    status.classList.add('is-verified');
  } catch (error) {
    status.textContent = 'Couldn’t verify record';
    status.classList.remove('is-pending');
    status.classList.add('is-error');
  }
}

async function openAnimalRecord() {
  if (state.busy) return;
  const sceneAnimal = state.selectedSceneAnimal;
  if (!sceneAnimal) return;
  const index = Number(sceneAnimal.id.slice('animal-'.length));
  const sample = profileFor(index);
  state.selected = sample;
  state.animal = null;
  state.asset = null;
  renderProfile(sample);
  showScreen('record-screen');
  state.busy = true;
  try {
    const animal = await ensureAnimal(sample);
    renderAnimal(animal, sample);
    await verifyRecord(animal.animal_id);
  } catch (error) {
    $('record-verification').textContent = 'Record unavailable';
    $('record-verification').classList.remove('is-pending');
    $('record-verification').classList.add('is-error');
    $('continue-solana').disabled = true;
    setMessage('api-state', 'Couldn’t load this record. Try again.', true);
    $('api-state').hidden = false;
  } finally {
    state.busy = false;
  }
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
  const explorer = $('asset-explorer');
  explorer.hidden = true;
  if (!state.animal) {
    setAssetButton('Asset creation unavailable', true);
    setMessage('asset-state', 'The local RIOSE record is unavailable. Reconnect the API before creating an asset.', true);
    return;
  }
  setAssetButton('Checking Devnet status…', true);
  setMessage('asset-state', 'Checking the animal asset registry and Solana Devnet.');
  try {
    const module = await tokenizationModule();
    const asset = await module.getAnimalAsset(state.animal.animal_id);
    state.asset = asset;
    if (asset.valid && asset.asset_address) {
      setAssetButton('Asset verified on Devnet', true);
      setMessage('asset-state', 'The asset address, owner, metadata URI, and transaction were verified against Devnet.');
      explorer.href = module.assetExplorerUrl(asset.asset_address);
      explorer.hidden = false;
      return;
    }
    const status = asset.evidence || asset.status || 'UNREGISTERED';
    if (status === 'UNREGISTERED' || status === 'PREPARED') {
      setAssetButton('Create animal asset on Devnet');
      setMessage('asset-state', 'Optional. Connect a wallet and approve a Devnet transaction to create the generic animal asset.');
    } else {
      setAssetButton('Check asset status on Devnet');
      setMessage('asset-state', `The asset is not verified yet (${status}). A submitted transaction is not shown as confirmed.`);
    }
  } catch (error) {
    setAssetButton('Retry Devnet check');
    setMessage('asset-state', `Devnet status could not be checked: ${error.message}`, true);
  }
}

async function performAssetAction() {
  if (!state.animal) return;
  const button = $('asset-action');
  button.disabled = true;
  setMessage('asset-state', 'Waiting for wallet approval and Devnet confirmation.');
  try {
    const module = await tokenizationModule();
    const result = await module.mintAnimalAsset(state.animal.animal_id);
    if (!result.valid || result.evidence !== 'VALIDATED_ON_DEVNET') {
      throw new Error(`The asset is not verified (${result.evidence || result.status || 'unknown state'}).`);
    }
    await refreshAsset();
  } catch (error) {
    setMessage('asset-state', `No verified mint was recorded: ${error.message}`, true);
    button.disabled = false;
    button.textContent = 'Retry or check asset status';
  }
}

document.querySelectorAll('[data-farm-mode]').forEach((button) => {
  button.addEventListener('click', () => setMode(button.dataset.farmMode));
});
$('farm-zoom-in').addEventListener('click', () => state.farm?.zoomBy(1.12));
$('farm-zoom-out').addEventListener('click', () => state.farm?.zoomBy(0.89));
$('farm-reset-view').addEventListener('click', () => {
  state.farm?.resetView();
  setMode('overview');
});
$('farm-roster-toggle').addEventListener('click', () => {
  const roster = $('farm-roster');
  const opening = roster.hidden;
  roster.hidden = !opening;
  $('farm-roster-toggle').setAttribute('aria-expanded', String(opening));
  if (opening) roster.querySelector('button')?.focus();
});
$('close-animal-panel').addEventListener('click', () => state.farm?.selectAnimal(null));
$('open-animal-record').addEventListener('click', () => void openAnimalRecord());
$('back-to-herd').addEventListener('click', () => showScreen('farm-screen'));
$('back-to-record').addEventListener('click', () => showScreen('record-screen'));
$('continue-solana').addEventListener('click', () => {
  showScreen('solana-screen');
  void refreshAsset();
});
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

void initFarm();
