const $ = (id) => document.getElementById(id);
const animals = [
  {
    index: 0, animal_id: 'demo-animal-0', hardware_id: 'demo-tag-0000', name: 'Animal 0', image: '/assets/demo/animal-0.webp',
    journey: [
      { moment: 'Morning', story: 'Leaves the resting area and begins grazing in the north pasture.' },
      { moment: 'Midday', story: 'Walks to the water point, pauses, then returns to the herd.' },
      { moment: 'Evening', story: 'Moves with the group toward the sheltered resting area.' },
    ],
  },
  {
    index: 1, animal_id: 'demo-animal-1', hardware_id: 'demo-tag-0001', name: 'Animal 1', image: '/assets/demo/animal-1.webp',
    journey: [
      { moment: 'Morning', story: 'Starts along the eastern pasture, stopping to graze along the way.' },
      { moment: 'Midday', story: 'Crosses toward the water point, then heads back to the center of the herd.' },
      { moment: 'Evening', story: 'Stays close to the group as it returns to the resting area.' },
    ],
  },
  {
    index: 2, animal_id: 'demo-animal-2', hardware_id: 'demo-tag-0002', name: 'Animal 2', image: '/assets/demo/animal-2.webp',
    journey: [
      { moment: 'Morning', story: 'Moves from the shaded area into open pasture and joins a small group.' },
      { moment: 'Midday', story: 'Visits the trough for water, then continues grazing nearby.' },
      { moment: 'Evening', story: 'Rejoins the herd near the central shelter.' },
    ],
  },
  {
    index: 3, animal_id: 'demo-animal-3', hardware_id: 'demo-tag-0003', name: 'Animal 3', image: '/assets/demo/animal-3.webp',
    journey: [
      { moment: 'Morning', story: 'Starts near the shelter and heads toward the far side of the pasture.' },
      { moment: 'Midday', story: 'Pauses to graze along the fence line, then follows the herd.' },
      { moment: 'Evening', story: 'Returns with the group and settles near the overnight pen.' },
    ],
  },
];
const state = { selected: animals[0], animal: null, asset: null, busy: false };
const screens = ['herd-screen', 'record-screen', 'solana-screen'];

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

function showScreen(screenId, { focusRecord = true } = {}) {
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
  const focusTarget = screenId === 'herd-screen'
    ? document.querySelector(`[data-animal-index="${state.selected.index}"]`)
    : $(`${screenId === 'record-screen' ? 'record-title' : 'solana-title'}`);
  if (focusTarget && (screenId !== 'record-screen' || focusRecord)) requestAnimationFrame(() => focusTarget.focus({ preventScroll: true }));
}

function setSelectedRow(index) {
  state.selected = animals[index];
  for (const row of document.querySelectorAll('.animal-row')) {
    const selected = Number(row.dataset.animalIndex) === index;
    row.classList.toggle('is-selected', selected);
    row.setAttribute('aria-selected', String(selected));
    row.tabIndex = selected ? 0 : -1;
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
  $('record-portrait').alt = `${sample.name} portrait`;
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

async function openAnimal(index) {
  if (state.busy) return;
  setSelectedRow(index);
  const sample = state.selected;
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

document.querySelectorAll('.animal-row').forEach((row) => {
  row.addEventListener('click', () => void openAnimal(Number(row.dataset.animalIndex)));
  row.addEventListener('keydown', (event) => {
    const current = Number(row.dataset.animalIndex);
    let next = current;
    if (event.key === 'ArrowDown') next = (current + 1) % animals.length;
    else if (event.key === 'ArrowUp') next = (current - 1 + animals.length) % animals.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = animals.length - 1;
    else return;
    event.preventDefault();
    setSelectedRow(next);
    document.querySelector(`[data-animal-index="${next}"]`).focus();
  });
});

$('back-to-herd').addEventListener('click', () => showScreen('herd-screen'));
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
