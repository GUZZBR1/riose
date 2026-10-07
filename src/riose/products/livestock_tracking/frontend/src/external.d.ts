/// <reference types="vite/client" />

declare module '/assets/animal-tokenization.bundle.js' {
  export function getAnimalAsset(animalId: string): Promise<import('./api').DigitalAssetState>;
  export function mintAnimalAsset(animalId: string): Promise<import('./api').DigitalAssetState>;
  export function assetExplorerUrl(address: string): string;
}
