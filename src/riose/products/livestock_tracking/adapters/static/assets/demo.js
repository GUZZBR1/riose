const $ = (id) => document.getElementById(id);
const animals = [
  { index: 0, animal_id: 'demo-animal-0', hardware_id: 'demo-tag-0000', name: 'Animal 0', image: '/assets/demo/animal-0.webp', weight: '428 kg', weightDate: '24 Sep 2026', vaccinations: '03 records', vaccinationDate: '14 Aug 2026', healthEvents: '02 records', healthDate: '10 Mar 2026' },
  { index: 1, animal_id: 'demo-animal-1', hardware_id: 'demo-tag-0001', name: 'Animal 1', image: '/assets/demo/animal-1.webp', weight: '391 kg', weightDate: '22 Sep 2026', vaccinations: '02 records', vaccinationDate: '02 Jul 2026', healthEvents: '01 record', healthDate: '18 Feb 2026' },
  { index: 2, animal_id: 'demo-animal-2', hardware_id: 'demo-tag-0002', name: 'Animal 2', image: '/assets/demo/animal-2.webp', weight: '446 kg', weightDate: '20 Sep 2026', vaccinations: '03 records', vaccinationDate: '09 Jun 2026', healthEvents: '02 records', healthDate: '03 Jan 2026' },
  { index: 3, animal_id: 'demo-animal-3', hardware_id: 'demo-tag-0003', name: 'Animal 3', image: '/assets/demo/animal-3.webp', weight: '407 kg', weightDate: '19 Sep 2026', vaccinations: '02 records', vaccinationDate: '21 May 2026', healthEvents: '01 record', healthDate: '12 Dec 2025' },
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

function eventDescription(eventType) {
  const labels = {
    ANIMAL_CREATED: 'Animal identity added',
    SIMULATION_RUN_RECORDED: 'Simulation run recorded',
    VACCINATION: 'Vaccination event recorded',
    HEALTH_EVENT: 'Health event recorded',
    WEIGHT_RECORDED: 'Weight event recorded',
    TRANSFER: 'Transfer recorded',
    OWNER_CHANGED: 'Ownership change recorded',
  };
  return labels[eventType] || `${String(eventType || 'EVENT').replaceAll('_', ' ').toLowerCase()} recorded`;
}

function renderProfile(sample) {
  $('continue-solana').disabled = true;
  $('record-title').textContent = sample.name;
  $('record-portrait').src = sample.image;
  $('record-portrait').alt = `${sample.name} portrait`;
  $('record-tag-id').textContent = sample.hardware_id;
  $('profile-weight').textContent = sample.weight;
  $('profile-weight-date').textContent = sample.weightDate;
  $('profile-vaccinations').textContent = sample.vaccinations;
  $('profile-vaccination-date').textContent = sample.vaccinationDate;
  $('profile-health-events').textContent = sample.healthEvents;
  $('profile-health-date').textContent = sample.healthDate;
  $('record-animal-id').textContent = sample.animal_id;
  $('asset-animal-name').textContent = sample.name;
  $('asset-animal-id').textContent = sample.animal_id;
  $('event-name').textContent = 'Animal identity added';
  $('event-time').textContent = 'Waiting for the local record';
  $('record-verification').textContent = 'Checking local record integrity…';
  $('record-verification').classList.remove('is-verified', 'is-error');
  $('api-state').hidden = true;
}

function renderAnimal(animal, sample) {
  state.animal = animal;
  $('continue-solana').disabled = false;
  $('record-animal-id').textContent = animal.animal_id;
  $('record-tag-id').textContent = animal.hardware_id;

  const latestEvent = animal.events?.[0];
  $('event-name').textContent = latestEvent ? eventDescription(latestEvent.event_type) : 'No events recorded';
  $('event-time').textContent = latestEvent?.timestamp
    ? new Date(latestEvent.timestamp).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
    : 'No local history is available for this record';
  $('asset-animal-name').textContent = sample.name;
  $('asset-animal-id').textContent = animal.animal_id;
}

async function verifyRecord(animalId) {
  const status = $('record-verification');
  status.textContent = 'Checking local record integrity…';
  status.classList.remove('is-verified', 'is-error');
  try {
    const verification = await requestJson(`/api/animals/${encodeURIComponent(animalId)}/events/verify`);
    if (verification.valid !== true || verification.evidence !== 'LOCAL_HASH_CHAIN') {
      throw new Error('The local event history did not verify.');
    }
    status.textContent = 'Local history verified';
    status.classList.add('is-verified');
  } catch (error) {
    status.textContent = 'Local history could not be verified';
    status.classList.add('is-error');
    setMessage('api-state', `The profile is available, but its local record could not be checked. ${error.message}`, true);
    $('api-state').hidden = false;
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
    $('record-verification').textContent = 'Local history unavailable';
    $('record-verification').classList.add('is-error');
    $('continue-solana').disabled = true;
    setMessage('api-state', `The profile is available, but the local record could not be opened. ${error.message}`, true);
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
