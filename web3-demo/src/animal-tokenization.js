import { create, fetchAssetV1, mplCore } from '@metaplex-foundation/mpl-core';
import { publicKey, generateSigner } from '@metaplex-foundation/umi';
import { createUmi } from '@metaplex-foundation/umi-bundle-defaults';
import { walletAdapterIdentity } from '@metaplex-foundation/umi-signer-wallet-adapters';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { Connection, PublicKey } from '@solana/web3.js';
import bs58 from 'bs58';

const DEVNET_RPC = 'https://api.devnet.solana.com';
const CORE_EXPLORER = 'https://core.metaplex.com/explorer';
const CORE_PROGRAM_ID = 'CoREENxT6tW1HoK8ypY1SxRMZTcVPm7R94rH4PZNhX7d';
const pendingKey = (animalId) => `riose:asset-pending:${animalId}`;
const mintLocks = new Map();

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`RIOSE API ${response.status}: ${body}`);
  }
  return response.json();
}

function makeUmi(wallet) {
  return createUmi(DEVNET_RPC)
    .use(mplCore())
    .use(walletAdapterIdentity(wallet));
}

function savePending(animalId, submission) {
  localStorage.setItem(pendingKey(animalId), JSON.stringify(submission));
}

function readPending(animalId) {
  try {
    return JSON.parse(localStorage.getItem(pendingKey(animalId)) || 'null');
  } catch {
    return null;
  }
}

async function persistSubmission(animalId, submission) {
  await api(`/api/animals/${encodeURIComponent(animalId)}/asset-submission`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      asset_address: submission.asset_address,
      owner_address: submission.owner_address,
      transaction_signature: submission.transaction_signature,
      attempt_ref: submission.attempt_ref,
    }),
  });
}

async function releaseUnsignedAttempt(animalId, submission) {
  submission.release_requested = true;
  savePending(animalId, submission);
  await api(`/api/animals/${encodeURIComponent(animalId)}/asset-release`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attempt_ref: submission.attempt_ref }),
  });
  localStorage.removeItem(pendingKey(animalId));
}

export async function connectWallet() {
  const wallet = new PhantomWalletAdapter();
  await wallet.connect();
  return { wallet, address: wallet.publicKey.toBase58() };
}

export async function verifyAsset(record) {
  if (!record?.asset_address || !record?.transaction_signature || !record?.owner_address || !record?.metadata_uri) {
    return { evidence: 'NOT_READY', valid: false };
  }
  const connection = new Connection(DEVNET_RPC, 'confirmed');
  const signature = record.transaction_signature;
  const signatureStatus = await connection.getSignatureStatuses([signature], { searchTransactionHistory: true });
  const status = signatureStatus.value[0];
  if (!status) return { evidence: 'RPC_NOT_FOUND', valid: false };
  if (status.err) return { evidence: 'ONCHAIN_FAILED', valid: false, error: status.err };
  if (!['confirmed', 'finalized'].includes(status.confirmationStatus)) {
    return { evidence: 'ONCHAIN_PENDING', valid: false };
  }

  const transaction = await connection.getTransaction(signature, {
    commitment: 'confirmed',
    maxSupportedTransactionVersion: 0,
  });
  if (!transaction) return { evidence: 'TRANSACTION_LOOKUP_PENDING', valid: false };
  const message = transaction.transaction.message;
  const accountKeys = message.staticAccountKeys ?? message.accountKeys;
  const keyAt = (index) => accountKeys[index]?.toBase58?.() ?? String(accountKeys[index]);
  if (!accountKeys.some((key) => (key?.toBase58?.() ?? String(key)) === record.owner_address)) {
    return { evidence: 'TRANSACTION_OWNER_MISMATCH', valid: false };
  }
  const instructions = message.compiledInstructions ?? message.instructions;
  const createTouchedAsset = instructions.some((instruction) => {
    const programId = instruction.programId?.toBase58?.()
      ?? keyAt(instruction.programIdIndex);
    const accountIndexes = instruction.accountKeyIndexes ?? instruction.accounts;
    return programId === CORE_PROGRAM_ID
      && accountIndexes.some((index) => keyAt(index) === record.asset_address);
  });
  if (!createTouchedAsset) return { evidence: 'TRANSACTION_ASSET_MISMATCH', valid: false };

  const umi = createUmi(DEVNET_RPC).use(mplCore());
  const asset = await fetchAssetV1(umi, publicKey(record.asset_address));
  const metadataResponse = await fetch(record.metadata_uri, { cache: 'no-store' });
  if (!metadataResponse.ok) return { evidence: 'METADATA_NOT_FOUND', valid: false };
  const metadata = await metadataResponse.json();
  const valid = asset.owner === record.owner_address && asset.uri === record.metadata_uri && asset.name === metadata.name;
  return {
    evidence: valid ? 'VALIDATED_ON_DEVNET' : asset.name !== metadata.name ? 'ONCHAIN_NAME_MISMATCH' : 'ONCHAIN_MISMATCH',
    valid,
    asset_address: record.asset_address,
    owner_address: asset.owner,
    metadata_uri: asset.uri,
    signature,
    explorer_url: `${CORE_EXPLORER}/${record.asset_address}?cluster=devnet`,
  };
}

async function recoverPendingWithoutSignature(animalId, pending) {
  const connection = new Connection(DEVNET_RPC, 'confirmed');
  const address = new PublicKey(pending.asset_address);
  const account = await connection.getAccountInfo(address, 'confirmed');
  if (!account) return null;

  const umi = createUmi(DEVNET_RPC).use(mplCore());
  const asset = await fetchAssetV1(umi, publicKey(pending.asset_address));
  if (asset.owner !== pending.owner_address || asset.uri !== pending.metadata_uri) {
    throw new Error('O endereço reservado existe na Devnet, mas dono ou URI não correspondem. A tentativa foi mantida para revisão.');
  }
  const signatures = await connection.getSignaturesForAddress(address, { limit: 10 }, 'confirmed');
  for (const entry of signatures) {
    const candidate = { ...pending, transaction_signature: entry.signature };
    const result = await verifyAsset(candidate);
    if (result.valid) {
      savePending(animalId, candidate);
      await persistSubmission(animalId, candidate);
      return result;
    }
  }
  return null;
}

async function performMintAnimalAsset(animalId) {
  if (!animalId) throw new Error('Selecione um bovino registrado antes de criar o ativo.');
  const previous = readPending(animalId);
  if (previous?.release_requested) {
    await releaseUnsignedAttempt(animalId, previous);
  } else if (previous) {
    if (!previous.transaction_signature) {
      const recovered = await recoverPendingWithoutSignature(animalId, previous);
      if (recovered) return recovered;
      throw new Error('A tentativa anterior não tem assinatura local nem resultado recuperável na Devnet. Ela foi mantida para evitar criar um segundo ativo para o mesmo bovino.');
    }
    const reconciled = await verifyAsset(previous);
    if (reconciled.valid) {
      await persistSubmission(animalId, previous);
      return reconciled;
    }
    if (reconciled.evidence === 'ONCHAIN_PENDING' || reconciled.evidence === 'RPC_NOT_FOUND') {
      throw new Error('A transação anterior ainda não tem resultado verificável. Não vou enviar outra criação para o mesmo bovino.');
    }
    if (reconciled.evidence === 'ONCHAIN_FAILED') {
      await api(`/api/animals/${encodeURIComponent(animalId)}/asset-reconcile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transaction_signature: previous.transaction_signature }),
      });
      localStorage.removeItem(pendingKey(animalId));
    } else {
      throw new Error(`A verificação da tentativa anterior retornou ${reconciled.evidence}. Resolva esse estado antes de tentar novamente.`);
    }
  }

  const intent = await api(`/api/animals/${encodeURIComponent(animalId)}/asset-intent`, { method: 'POST' });
  if (intent.cluster !== 'devnet') throw new Error('A criação deste demo está limitada à Devnet Solana.');
  if (intent.status === 'SIGNING') {
    throw new Error('Já existe uma tentativa reservada para este bovino. Confira o estado da transação antes de iniciar outra.');
  }
  if (intent.status === 'SUBMITTED') {
    const existing = await getAnimalAsset(animalId);
    if (existing.valid || existing.evidence !== 'ONCHAIN_FAILURE_CONFIRMED') return existing;
  }

  const publicMetadataResponse = await fetch(intent.metadata_uri, { cache: 'no-store' });
  if (!publicMetadataResponse.ok) throw new Error('Could not load the public asset metadata from RIOSE.');
  const publicMetadata = await publicMetadataResponse.json();
  const allowedPublicName = typeof publicMetadata.name === 'string'
    && (/^Animal \d{1,2}$/.test(publicMetadata.name) || publicMetadata.name === 'RIOSE · Ativo bovino');
  if (!allowedPublicName) {
    throw new Error('The public asset name is not valid for this RIOSE demo.');
  }

  const { wallet } = await connectWallet();
  const umi = makeUmi(wallet);
  const signer = generateSigner(umi);
  const ownerAddress = wallet.publicKey.toBase58();
  const attemptRef = crypto.randomUUID().replaceAll('-', '');
  const reservation = await api(`/api/animals/${encodeURIComponent(animalId)}/asset-reserve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      asset_address: signer.publicKey,
      owner_address: ownerAddress,
      attempt_ref: attemptRef,
    }),
  });
  const submission = {
    asset_address: signer.publicKey,
    owner_address: ownerAddress,
    metadata_uri: reservation.metadata_uri,
    cluster: 'devnet',
    attempt_ref: reservation.attempt_ref,
  };
  // Save the generated asset address before sending so an interrupted request
  // can be reconciled without minting a second asset for the same animal.
  savePending(animalId, submission);

  const transaction = create(umi, {
    asset: signer,
    name: publicMetadata.name,
    uri: reservation.metadata_uri,
    owner: umi.identity.publicKey,
  });
  let rawSignature;
  try {
    rawSignature = await transaction.send(umi);
  } catch (error) {
    if (isExplicitWalletRejection(error)) {
      await releaseUnsignedAttempt(animalId, submission);
      throw new Error('A assinatura foi recusada na carteira; nenhuma transação foi enviada.');
    }
    throw error;
  }
  submission.transaction_signature = bs58.encode(rawSignature);
  savePending(animalId, submission);

  await persistSubmission(animalId, submission);

  const connection = new Connection(DEVNET_RPC, 'confirmed');
  await connection.confirmTransaction(submission.transaction_signature, 'confirmed');
  const verification = await verifyAsset(submission);
  if (!verification.valid) throw new Error(`A criação foi enviada, mas a leitura on-chain não confirmou o ativo (${verification.evidence}).`);
  return verification;
}

function isExplicitWalletRejection(error) {
  let current = error;
  for (let depth = 0; current && depth < 5; depth += 1) {
    if (current.code === 4001 || current.code === '4001') return true;
    if (typeof current.message === 'string' && /user rejected|rejected by user/i.test(current.message)) return true;
    current = current.error ?? current.cause;
  }
  return false;
}

export function mintAnimalAsset(animalId) {
  if (!animalId) return Promise.reject(new Error('Selecione um bovino registrado antes de criar o ativo.'));
  const run = () => performMintAnimalAsset(animalId);
  if (typeof navigator !== 'undefined' && navigator.locks?.request) {
    return navigator.locks.request(`riose-mint:${animalId}`, run);
  }
  if (mintLocks.has(animalId)) return mintLocks.get(animalId);
  const pending = run().finally(() => mintLocks.delete(animalId));
  mintLocks.set(animalId, pending);
  return pending;
}

export async function getAnimalAsset(animalId) {
  const record = await api(`/api/animals/${encodeURIComponent(animalId)}/asset`);
  if (record.status === 'PREPARED' || record.status === 'SIGNING') {
    let pending = readPending(animalId);
    if (!pending && record.status === 'SIGNING') {
      pending = {
        asset_address: record.asset_address,
        owner_address: record.owner_address,
        metadata_uri: record.metadata_uri,
        attempt_ref: record.attempt_ref,
        cluster: 'devnet',
      };
      savePending(animalId, pending);
    }
    if (pending) {
      if (pending.transaction_signature) {
        const verified = await verifyAsset(pending);
        if (verified.valid) await persistSubmission(animalId, pending);
        return { ...record, ...verified };
      }
      const recovered = await recoverPendingWithoutSignature(animalId, pending);
      if (recovered) return { ...record, ...recovered };
    }
  }
  if (record.status !== 'SUBMITTED') return { ...record, valid: false };
  const verified = await verifyAsset(record);
  if (verified.evidence === 'ONCHAIN_FAILED') {
    await api(`/api/animals/${encodeURIComponent(animalId)}/asset-reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_signature: record.transaction_signature }),
    });
    const pending = readPending(animalId);
    if (pending?.transaction_signature === record.transaction_signature) {
      localStorage.removeItem(pendingKey(animalId));
    }
    return { ...record, status: 'PREPARED', evidence: 'ONCHAIN_FAILURE_CONFIRMED', valid: false };
  }
  return { ...record, ...verified };
}

export function assetExplorerUrl(assetAddress) {
  return `${CORE_EXPLORER}/${assetAddress}?cluster=devnet`;
}
