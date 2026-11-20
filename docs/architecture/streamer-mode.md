# Streamer mode (split layout)

Clip Generator → **streamed video** is a single-video option for clipping a
streamer's VOD or livestream. It turns each normal 9:16 clip into a two-part
frame: the streamer's marked box on top, the viral clip on the bottom.

## Marking

- The toggle is only offered for a single video; bulk/queue runs never show it.
- The user marks the streamer's box once, **before** the render, on the
  original source at its true resolution. The modal plays the source and lets
  the user draw, move and **resize** a box freely; its shape is whatever the
  streamer's cam is (a 16:9 webcam, a square inset, a 9:8 crop…).
- The box shape sets the split. The top panel keeps the box's pixel aspect
  exactly, and the viral clip gets the rest of the height: the bottom panel's
  shape is `(9/16) / (1 - top share)`. The modal shows the live split (e.g.
  `streamer 16:9 · split 32% / 68%`).
- The split is clamped to **15%–85%** so neither panel can disappear. A box
  outside that shape range is refused by the renderer (normal clip), and the
  modal keeps the selection inside it while resizing.
- The box is stored as `{x, y, w, h}` fractions of the source frame. A saved
  box is tied to the source: changing the tab, link, file or collector item
  clears it.
- A **prevention area** is a second, independent box: the streamer's whole cam
  box (or a chat/overlay panel) that the clip's half must never show. It cannot
  reuse the streamer box, because that one is usually only a zoom on the face
  while the whole cam is much bigger. It is free-form (no split/aspect rules),
  stored next to the streamer box, and optional — no prevention area means the
  old behaviour. The modal has a `streamer box` / `prevent area` switch, shows
  the prevention area dashed in red, and can copy the streamer box as a
  starting point (`copy streamer box`). The panel also has its own
  `mark prevent area` button, which opens the modal on that box.
- Only the **selected** box takes the pointer. A drag always edits/draws the
  selection on the current chip — the other box is a reference (dashed, faded,
  `pointer-events: none`). Without that rule, drawing the prevent area over the
  cam (which is exactly where the streamer box sits) would silently move the
  streamer box instead, and the split would end up showing the prevent area.
  The banner over the video states which selection a drag creates.
- A file upload is played straight from the browser (`URL.createObjectURL`).
  A Collector item is played from its local `/collector/files/...` copy. A link
  is first downloaded into the Collector through
  `POST /api/streamer/prepare` (the modal polls `GET /api/streamer/source/{id}`
  while it downloads), and the job then processes that Collector item so the
  same source is not fetched twice.

## Rendering

`app.py` validates the box (`streamer_layout.clean_rect`), refuses a horizontal
or square output, and puts `STREAMER_MODE=1` + `STREAMER_RECT_JSON` in the job
environment (`STREAMER_AVOID_JSON` too when prevention areas are marked). In
`main.py`, after `render_clip` and **before** auto-hook and captions,
`streamer_layout.apply` composes:

- **Top panel** — the marked source crop, cut from the source at the clip's
  `start`/`end` and scaled to fill `1080 x top`, where `top` comes from the
  box's aspect. The marker is that same aspect, so the box lands on the panel
  un-cropped. A 9:8 box gives the familiar 1080x960 (50%); a 16:9 box gives
  1080x608 (~32%).
- **Bottom panel** — the reframe is rendered natively at the remaining shape
  (e.g. 1080x1312 for a 16:9 streamer box) instead of the usual 9:16 one. It
  fills its panel edge to edge, with no blurred filler: fitting a 9:16 picture
  inside a wider panel left two blurred bands either side of it, which is what
  users saw as a "double processed" bottom half. Top + bottom always add up to
  the normal 9:16 delivery (1080x1920).
- **No blurred filler** — inside the bottom panel every scene is framed as a
  full-bleed tracked crop (`no_blur`), including the wide/face-less shots that
  would otherwise use GENERAL/WIDE's blurred backdrop. The panel is narrower
  than the usual 9:16, so a blurred bed there shrinks the picture instead of
  filling the frame. This is automatic framing, not a framing override: the v2
  engine can still fall back to v1 on failure.
- **Subject tracking** — the marked box is the streamer, not the clip's
  subject. In streamer mode the face/person detectors run on a copy of the
  frame with **both** marked boxes blanked (the streamer crop and the whole
  prevention area), so the bottom half follows the viral content instead of
  locking onto the streamer. The rendered frames keep every pixel; the mask
  exists only inside detection. This applies to scene classification (TRACK vs
  GENERAL) and to every layout that samples faces or people.
- **Prevention area** — the clip panel is a tracked crop of the same source, so
  a streamer cam in the source would otherwise be framed into it. After the
  camera trajectory is computed, each frame's crop window keeps its size and
  slides to the nearest position that shows none of the marked areas
  (`streamer_layout.avoid_zones_crop_x`). Only the horizontal position moves,
  and a marker outside the crop's vertical span is ignored. If the areas leave
  no clear window (they cover most of the width), the window takes the smallest
  possible overlap instead of pushing the subject out of frame, and the job log
  says how many frames could not be cleared. The v1 fallback loop applies the
  same rule, so a v2 failure does not bring the cam back.
- **Captions on the seam** — in streamer mode every caption event is anchored
  on the line between the two panels (`\an5` + `\pos` at the box's share of the
  height, e.g. 32% for a 16:9 box). A line of text therefore overlaps a little
  of the streamer box and a little of the clip, instead of covering the video
  alone. The chosen font/colour/effect is unchanged. The share is recorded as
  `streamer.caption_seam` in the job metadata so the subtitle modal, hook and
  recut re-burns put the text back on the same line.
- **Audio** — the viral clip's audio only. A silent clip composes without any
  audio stream.
- The reframe's `.layout.json` sidecar is removed, so captions are not re-placed
  on the bottom clip's old SPLIT seam; the composition seam above replaces it.

Failure is deliberately soft: a bad/invalid box, a box shape outside the
15%–85% split range, or an ffmpeg error leaves the normal reframed clip in place
and logs the reason. The composer also keeps a legacy fit-over-blur path for a
bottom clip whose shape does not match the panel (an older render); new
streamer jobs always take the full-bleed path.

## AI context

`gemini_worker` appends `STREAMER_NOTE` to the scoring/detail prompts when
`STREAMER_MODE=1`: it tells the model this is a stream, that the streamer's
reaction is often the payoff, and not to favour long gameplay stretches with no
commentary. Clip counts and length rules are unchanged.

## API

`POST /api/process` accepts `streamer: {"x": ..., "y": ..., "w": ..., "h": ...}`
(JSON object or JSON string in a form post). The box must be inside `0..1`
and at least 2% per side; the render also measures its real pixel aspect on that
source and requires it to leave both panels between 15% and 85% of the height
(2% rounding window). Anything else falls back to the normal clip. The output is
forced to vertical.

`streamer_avoid` takes one prevention box or a JSON list of them, in the same
fractions. It needs `streamer`: without the split there is no clip panel to keep
it out of, so it is ignored. An unreadable or off-frame value is a `400` at
submit; the job itself never fails over it — `main.py` logs a bad value and
drops it, keeping the split. The metadata's `streamer.avoid` records what the
render used.

`POST /api/streamer/prepare` and `GET /api/streamer/source/{id}` back the
link-to-Collector flow.

## Tests

`tests/test_streamer_layout.py` covers rectangle validation, the split geometry
(9:8 = 50/50, 16:9 = ~32/68, square = 56/44, out-of-range rejected), the
detection mask that keeps the tracker off the streamer and the prevention area,
the prevention-area crop steering (corner cams, an unavoidable centre cam, a
marker outside the crop), the pure filtergraph shape (native panel + the legacy
blurred fit), a real ffmpeg composition with a 16:9 box on synthetic clips, the
caption seam (metadata -> ASS `\an5\pos`), the soft failure that keeps the
normal clip, and the UI/backend wiring.
