# 3D character model (not included)

`avatar.js` loads `app/assets/cortana.glb` together with `rig.json` (bone axes used for the jaw, lips, eyes and head).

The model used during development is a fan-made port of a Halo character. Its licence is unverified and the character
belongs to Microsoft / 343 Industries, so **it is not distributed in this repository** (`*.glb` is git-ignored).

To use a model locally:

1. Put a binary glTF file named `cortana.glb` in this folder.
2. It must use `EXT_texture_webp` or standard textures, and provide the bones listed in `rig.json`
   (`Jaw`, `Lips Lower`, `Lips Upper`, `Tongue_2`, `bip_head`, `bip_neck`, `bip_spine_3`, `Eye_L`, `Eye_R`, ...)
   and the morph targets `Eyes-Blink`, `Mouth-EE`, `Mouth-OO`, `Mouth-Smile`, `Eyebrows-Up` for full animation.
   Missing bones or morphs are skipped; the model still renders.
3. Rebuild (`python build/build_cortana.py`) or run from source.

Without a model the app works normally; the hologram stage shows a short message instead of the character.
Only use a model you are allowed to use. Never commit it to a public repository.
