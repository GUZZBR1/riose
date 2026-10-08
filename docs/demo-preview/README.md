# Farm demo browser evidence

- Date: 2026-10-08T16:09:39.224Z
- Browser: Chromium 153.0.8010.12
- Desktop view: 1672 × 941 (matched to supplied reference); mobile view: 390 × 844
- Farm 01 stress run: 100 animals; browser animation-frame rate: 60 fps; observed long tasks: 2
- Farm 02 stress run: 100 animals; browser animation-frame rate: 60 fps; observed long tasks: 4
- Input behavior: mouse wheel and touch scroll the page over the farm. Browser drag test selected and repositioned a cow; simulation validation keeps drops on safe walkable terrain and stops at obstacles/overlaps. Deliberate scene panning is Shift + left-drag.
- Synthetic mobile loading: opening farm interactive in 8.47 s; first contentful paint 0.80 s; 1.32 MiB transferred before Farm 02; throttled to 150 ms latency, 200 KiB/s download, and 4× CPU slowdown. This is a repeatable lab check, not field Core Web Vitals.
- Loading audit: the first version waited for all Farm 01 decoration and Farm 02 art before the scene was interactive; the revised flow paints the island first, loads essential scene layers and animals next, then decorations. Farm 02 art loads on demand.
- Lazy scene transfer: 1.32 MiB before Farm 02 enters; 3.49 MiB after both scenes load
- Farm 02 simulation and landscape assets load only after at least 10% of its stage is visible; identity preview art loads only when its panel opens.
- Scene bundle: 1,246,709 bytes; gzip: 345,513 bytes
- Layout transition: both farm scenes kept their viewport aspect ratio within 6% while the animal panel opened.
- Verified in-browser: one continuous page with dairy and Cerrado scenes; in-place animal and identity preview panels; selection changes update both panels; outside click clears selection; keyboard and accessible-list selection; preview performs no wallet or asset requests; API failure leaves both scenes and preview available; mobile layout; 100-animal rendering on each farm.
- Simulation tests cover safe spawning, walkable boundaries, water and fences, route reachability, deterministic movement and 10 accelerated minutes for herds of 1, 10, 24 and 100 on each farm.
