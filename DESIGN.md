# RIOSE visual system

## Direction

RIOSE should feel like a small hardware research project: quiet, precise, and grounded in animal identity and verifiable records. The landing page introduces the product and links to the guided demo; `/demo` opens on a living top-down pixel-art farm, then follows a selected animal into its local history and optional Solana Devnet asset. The manifesto has its own route so it can be read without adding another section to the product hero.

## Palette and surfaces

- Page background: warm neutral `#F2F2F0` across routes; avoid pure white and hard section changes.
- Primary text: `#20211F`; secondary text: `#73746F`.
- Header: transparent, blurred glass with a faint light border and restrained shadow.
- Product: matte yellow polymer, black fastening hardware, and only the transparent/internal parts supported by supplied references. Preserve the broad, squared shield silhouette; do not make the tag circular.

## Typography

- Wordmark and navigation: a restrained technical grotesk, medium to semibold, with modest tracking. Never use a fashion serif or sci-fi display face.
- Header identity uses live “Riose” text in Sora SemiBold, with the supplied emblem as a small raised mark and a glass definition that opens on hover, focus, or touch.
- The hero headline uses a restrained regular grotesk at 72–96px on desktop, with a 0.98 line height and soft charcoal color. Its supporting line stays quieter at 20–24px.
- Editorial copy and metadata: system monospace, small and legible. Use spacing and hierarchy rather than oversized text or decorative rules.
- Keep the interface to these two typographic roles.

## Interaction and motion

- Keep the product dominant and the page naturally scrollable.
- Lower the hero model by roughly 60–112px to create room above the ear attachment without changing the model or camera.
- Keep the interactive 3D ear-tag model on the central landing page. It should respond to intentional hover, drag, touch, and keyboard input; it must not move randomly or run a continuous scene.
- Keep the farm demo in 2D. Use authored tilemap art and deterministic ambient movement; do not add random drift or camera motion.
- Use small, intentional hover and selection transitions on records and controls. Respect reduced-motion preferences and keep all interactions usable with touch and keyboard.
- The header contracts to a centered wordmark while scrolling. A small dictionary-style definition may appear on wordmark hover, focus, or tap.
- Header navigation and the São Paulo location link use a restrained lift and animated underline on hover/focus; the location opens its map destination.
- Motion should ease softly and not delay the first usable frame. Do not add glow, particles, animated gradients, or game-like bounce.

## Content and evidence

- The brand definition connects RIOSE with Bel Riose from Isaac Asimov's *Foundation* and the historical Belisarius; do not invent an acronym expansion.
- The manifesto describes the intent to build a cattle ear tag and the resolve to bring hardware from prototype toward field use. Keep aspirations distinct from measured product claims.
- Do not present the independent Nature Communications article as RIOSE research.
- Treat internal 3D components as illustrative until confirmed by an accessible product reference.

## Layout

- The root landing page preserves the product headline “The next-generation livestock ear tag.” and its supporting line, with a direct link to the guided demo. Keep the interactive 3D model as the hero; the independent paper entry follows below.
- `/demo` opens directly on a living, illustrated pixel-art farm with 24 visible animals, meadows, winding paths, a barn, pond, trees and receiver anchors. Keep the environment composition organic and detailed rather than repeating a grid of equally sized paddocks. Signals, coverage and movement are local simulation/estimates, not physical RF telemetry. Selecting an animal opens a compact panel; the full narrative and optional Solana asset remain secondary. The demo does not alter the landing-page 3D tag hero.
- `/manifesto` uses the same floating glass header and centered live-text Riose wordmark as the product page. Center the headline and reading column on the viewport; keep paragraph lines left-aligned for comfortable reading and preserve generous spacing.
- Build the manifesto's monumental communications structure from browser text characters. Keep it monochrome, legible but restrained, cropped beyond the viewport, and free of gradients or illustrated assets; use only low-amplitude pointer and scroll movement.
- Keep the manifesto link secondary in the expanded header. Do not add a card grid or promotional section to the landing page.
