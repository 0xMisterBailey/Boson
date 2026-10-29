# refs-licences: which real references may appear on screen

Each `-real` studio's refs are labelled "found reference, private, not redistributed" inside the studio repo. That
label stays: the image files never leave the studio repos and are never copied into a tracked file. This sidecar
says which of those refs **may still be shown** (in the app, in the demo video) because their source, Wikimedia
Commons, licenses them for reuse, and what credit must go with them. It sits outside the studio repos so writing it
never moves a studio's sha.

Rebuild (cached, a rerun makes no calls; metadata only, no image downloads):

    python3 tools/ref_licences.py --cache /tmp/boson-ref-licences

One `<studio>.jsonl` per studio, one line per ref, in `refs.jsonl` order:

- `n`, `file`, `url`: copied from the studio's `refs/refs.jsonl`
- `licence`, `licence_url`, `author`: Commons' `LicenseShortName`, `LicenseUrl`, `Artist` (HTML stripped)
- `attribution`: the exact credit line to show, Commons' own form: `Author, Licence, via Wikimedia Commons`
- `showable`: true or false; `reason` says why when false
- also kept from Commons: `attribution_required`, `usage_terms`, `commons_credit`

## What "showable" means

`showable: true` means the file's Commons licence is CC0, public domain, CC BY or CC BY-SA (any version), so the
picture may be shown on screen and in the published video **as long as its `attribution` line is shown with it**.
Everything else is `false`: a ref with no Commons page (we hold no licence record, so it stays private and on this
box only), no URL at all, a file missing from Commons, or any other licence.

## How to credit

- Put the `attribution` line on screen, in the frame, while the picture is visible (a small caption under it or a
  credits strip on the same beat). A line only in the video description is not enough for a picture shown in frame.
- Also list every shown ref's `attribution` and `url` in the video description and the repo's credits.
- CC BY-SA: the picture itself is shared under BY-SA; showing it unchanged in a frame is fine; a crop or edit of it
  that we publish is a derivative and goes out under CC BY-SA too. Say "cropped" in the credit when we crop.
- CC0 and public domain need no credit; give the line anyway as a courtesy.
- One `Artist` field on Commons was a note, not a name (architecture-real 10, Henderson Wave Bridge); the note asks
  to be credited by name, so the credit uses that name (`CREDIT_AS` in the tool).

## Counts (2026-10-23)

- architecture-real: 43 refs, 25 showable (CC BY-SA 4.0 13, CC BY-SA 2.0 4, CC BY 2.0 2, CC BY-SA 3.0 2,
  CC BY 4.0 2, CC BY 3.0 1, CC0 1); 18 have no Commons page
- cars-real: 28 refs, 15 showable (CC BY-SA 4.0 8, CC BY 2.0 4, CC0 2, CC BY 4.0 1); 13 have no Commons page
- cars-s4471-real: 12 refs, 5 showable (CC BY-SA 2.0 2, CC BY 3.0 1, CC BY 2.0 1, CC0 1); 7 have no Commons page
- fashion-real, posters-real: 21 refs each, 0 showable: no source URL was recorded for any of them
