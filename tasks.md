# Tasks

Backlog of known improvements and future work, separate from the main phase plan.

## Before production run

- [ ] **Increase `after_skin_select` delay** — set to `3.0`s in `config.yaml` once done testing.
  Currently at `0.5`s for fast iteration. The 3D model needs time to fully load and stop animating before the screenshot is taken.

## Future ideas

- [ ] **Animated capture per skin** — instead of (or in addition to) a static model screenshot, record a short animated capture:
  - Option A: 5-second screen recording of the model view → save as GIF or animated WebP
  - Option B: automatically rotate the in-game model (if the UI supports click-drag rotation), capture a front→side→back sweep over ~2 seconds, encode as GIF/WebP
  - Pillow supports saving animated WebP/GIF natively; OpenCV can encode video (MP4/WebM)
  - Animated WebP is likely the best format for a wiki (smaller than GIF, supports transparency)
