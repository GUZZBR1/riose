# Riose hardware assembly view

The live demo assembly in `src/riose/products/livestock_tracking/frontend/src/HardwareAssembly.tsx`
is an interactive Three.js illustration. Its outer tag silhouette follows the
procedural shape used by the homepage viewer in
`src/riose/products/livestock_tracking/adapters/static/assets/product-scene.js`.

This checkout does not contain source-accurate, separated GLB/GLTF/CAD meshes
for the four exploded parts. The existing tag `OBJ`/`DAE` files are provisional
outer-housing geometry, and the mechanical model describes assumed envelopes,
not reviewed production drawings. The assembly view therefore reconstructs the
upper and lower housings, PCB details, and cylindrical power cell as conceptual
geometry, using the supplied exploded image for visual proportions and order.
The exploded vertical spacing is compositional; it is not a verified assembly
axis or bill of materials. No claim is made about 360-degree accuracy, physical
fit, materials, electrical layout, or production hardware.

The section itself repeats these limitations in its “About this model”
disclosure. Replace the conceptual parts with reviewed source geometry before
using this view as an engineering or manufacturing reference.
