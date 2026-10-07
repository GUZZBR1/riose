# Live demo visual QA

## Source and implementation

- Source visual truth: user-provided attachment `22ab1071-e665-47d0-9cdc-6937f149c61e.png` (1672 × 941 px).
- Implementation: [farm-demo-solana-ready.png](docs/demo-preview/farm-demo-solana-ready.png) (1672 × 941 px) and [farm-demo-solana-preview.png](docs/demo-preview/farm-demo-solana-preview.png) (1672 × 941 px).
- Viewport: desktop, 1672 × 941 CSS px; Playwright device scale factor 1. The source and implementation have matching pixel dimensions and no density normalization was needed.
- Compared states: source reference shows the selected animal and expanded digital identity, before preview; implementation has the same state in `farm-demo-solana-ready.png` and the completed local preview in `farm-demo-solana-preview.png`.
- Full-view comparison: opened the source and identity-ready implementation together at matching scale. The comparison checked the hero, farm-to-panel balance, page background, whitespace, and lack of a framed map.
- Focused comparison: opened the source and implementation context rails together, covering the portrait, timeline, integrity status, identity orb, Devnet indicator, and preview action.
- Responsive evidence: [farm-demo-mobile.png](docs/demo-preview/farm-demo-mobile.png), captured at 390 × 844 CSS px; it includes the stacked farm, animal card, and identity card without horizontal overflow.

## Findings and iteration history

The first browser capture exposed three actionable visual issues: the portrait used its intrinsic height and stretched vertically; supporting timeline/action text was too small; and the identity artwork's intrinsic height made the right rail sit too low and clipped its bottom disclosure in the reference-sized viewport.

Fixes: set explicit automatic image heights while preserving aspect ratios, increased supporting text sizes, tightened spacing, reduced the identity-art box to its rendered width, and moved the desktop context rail upward to align with the supplied composition. The final matching-size screenshots show a square portrait, readable timeline, both cards in the side rail, and the complete Devnet disclosure. The focused comparison confirms the orb is a separate transparent image asset rather than CSS placeholder art.

## Fidelity review

- **Fonts and typography:** uses the site's existing Helvetica/Arial editorial sans, Sora wordmark, and monospace system labels. Hero and panel hierarchy match the reference direction; body copy and timeline remain legible at full-size capture. Small technical labels are secondary and limited to tag, journey-source, and network details.
- **Spacing and layout:** preserves a broad farm on the left and a narrower stacked context rail on the right. Both cards float on the page without a border around the farm. Panel and hero alignment follows the supplied composition; mobile switches to a vertical stack.
- **Colors and tokens:** warm off-white page, white translucent cards, subtle neutral borders and shadows, and the source's restrained cyan/violet/green identity accents. Status color is only used for the actual record verification result.
- **Image quality and asset fidelity:** the diorama stays the dominant visual; cattle portraits use the project's generated photo assets. The new Solana identity orb is a standalone transparent PNG at `src/riose/products/livestock_tracking/adapters/static/assets/demo/solana-identity-orb.png`. Portrait and orb aspect ratios are preserved.
- **Copy and content:** hero copy follows the supplied reference. The animal timeline is identified as illustrative. “Record integrity verified” only appears after the local hash-chain API succeeds. The preview says it is not created; Devnet confirmation is not shown after the missing-wallet failure.
- **Interaction and accessibility:** browser QA covered keyboard selection, the accessible animal list, in-place selection changes, outside-click deselection, panel expansion, API failure, preview-only behavior, missing-wallet failure, and mobile layout. Reduced-motion styles remain active. No browser console errors were observed.

No actionable P0, P1, or P2 visual findings remain. Full-view and focused comparisons were both completed after the fixes above.

## Verification evidence

- `npm test` passed: TypeScript typecheck, scene build, build checks, and 12 navigation tests.
- `npm run test:e2e` passed: one-page desktop flow, preview without transaction, wallet-unavailable failure without false confirmation, API-offline fallback, responsive mobile view, and 100-animal browser rendering.
- Browser stress sample at 100 animals: 60 fps, 1 observed long task over the 4-second sample. These are local Chromium measurements, not production performance claims.
- Browser and bundle details: [docs/demo-preview/README.md](docs/demo-preview/README.md).

final result: passed
