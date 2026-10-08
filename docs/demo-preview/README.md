# Farm demo browser evidence

- Date: 2026-10-08T00:15:52.468Z
- Browser: Chromium 153.0.8010.12
- Desktop view: 1672 × 941 (matched to supplied reference); mobile view: 390 × 844
- Farm 01 stress run: 100 animals; browser animation-frame rate: 60 fps; observed long tasks: 2
- Farm 02 stress run: 100 animals; browser animation-frame rate: 60 fps; observed long tasks: 2
- Input behavior: mouse wheel and touch scroll the page over the farm. Browser drag test selected and repositioned a cow; simulation validation keeps drops on safe walkable terrain and stops at obstacles/overlaps. Deliberate scene panning is Shift + left-drag.
- Synthetic mobile loading: opening farm interactive in 7.84 s; first contentful paint 0.58 s; 1.32 MiB transferred before Farm 02; throttled to 150 ms latency, 200 KiB/s download, and 4× CPU slowdown. This is a repeatable lab check, not field Core Web Vitals.
- Loading audit: the first version waited for all Farm 01 decoration, Farm 02 art, and unopened Solana artwork before the scene was interactive; the opening scene took about 25 s on this throttled profile. The revised flow paints the island first, loads essential scene layers and animals next, then decorations; Farm 02 and Solana artwork load on demand. Matching runs reached interactive in 4.4–11.3 s, showing variability under CPU/network contention.
- Lazy scene transfer: 1.32 MiB before Farm 02 enters; 3.49 MiB after both scenes load
- Farm 02 simulation and landscape assets load only after at least 10% of its stage is visible; Solana artwork loads only when its panel opens.
- Scene bundle: 1,244,748 bytes; gzip: 344,994 bytes
- Verified in-browser: one continuous page with distinct lush dairy and Cerrado beef farms; in-place animal and Solana panels; selection changes update both panels; outside click clears selection; keyboard and accessible-list selection; local preview without transaction; missing-wallet failure does not confirm an asset; API failure leaves both scenes and preview available; mobile layout; 100-animal rendering on each farm.
- Simulation tests cover safe spawning, walkable boundaries, water and fences, route reachability, deterministic movement and 10 accelerated minutes for herds of 1, 10, 24 and 100 on each farm.
