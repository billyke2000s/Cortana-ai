# 3D character model

`avatar.js` loads **`cortana.glb`** (Cortana, binary glTF with WebP textures) together with **`rig.json`**, the bone axes used to
animate the jaw, lips, tongue, eyes, head, neck and spine.

| Part | Used for |
|---|---|
| Bones `Jaw`, `Lips Lower`, `Lips Upper`, `Tongue_2` | mouth shapes while she speaks |
| Bones `bip_head`, `bip_neck`, `bip_spine_3` | head turns, nods, breathing |
| Bones `Eye_L`, `Eye_R` | gaze and eye darts |
| Morphs `Eyes-Blink`, `Mouth-EE`, `Mouth-OO`, `Mouth-Smile`, `Mouth-Smirk-L`, `Eyebrows-Up`, `Eyebrows-Worried`, `Eyes-Squint` | blinks, expressions, visemes |

The page recolours the materials to the blue hologram look, cuts out the hair with an alpha test, validates every texture after
loading and reloads the model automatically if one failed (see `docs/DECISIONS.md` D-010).

Replacing the model: keep the same bone and morph names (or update `rig.json` and `avatar.js`), export as `.glb` from Blender,
and check it in the browser at several phone sizes. Missing bones or morphs are skipped rather than crashing.
