# The Boson guidebook (v4, 2026-10-27)

Plain words, short steps. This version covers the new app: badges on every piece, plain messages, Undo swap, the
before/after slider, and Remove this slot.

## Boson in five lines

1. A **studio** is a small art department for one kind of thing: buildings, cars, outfits, posters.
2. Each studio has its own **taste**, written down in files. You teach it by marking pictures good or bad.
3. A **scene** is one street photo (Austin, a bus stop). Some things in it can be replaced: the car, the outfit,
   the poster, the buildings.
4. You click one of those things, pick a new version from any studio, and press **Swap**. The whole photo is redrawn
   with the new piece, in the same light. Everything else stays.
5. Every swap makes a new numbered photo called a **take**. Old takes are never thrown away.

## Why it is new

Boson is entered as "Most Innovative". The new thing is the whole idea, in five parts:

1. **Studios instead of presets.** A preset is a fixed look someone else made. A studio is a folder of plain files,
   kept in git (a tool that saves every version), that holds one taste.
2. **The curation loop.** You dot pictures red and green and write one sentence. That verdict becomes a rule the next
   round must read. So the taste builds up, with a history you can look back through.
3. **The scene editor.** A street where every piece is a slot (a replaceable thing) any studio can fill. A swap redraws
   and relights only what changed. Even background things, like the taqueria, can become slots.
4. **The engineering underneath.** Ordinary ComfyUI graphs that stop and wait for your judgment, replays that cost
   nothing, and any model behind one switch.
5. **Models for their strengths.** Models on your own machine and models in the cloud, each used for what it does
   best, with your feedback choosing. Next step: test every model on every task, and let your dots pick.

## The words

Each Boson word, once.

- **Studio**: an art department for one field (cars-real, exotic-cars-real, fashion-real, architecture-real, ...).
- **Piece**: one picture a studio made (one car, one outfit, one building).
- **Scene**: the street photo plus the list of things in it you can replace.
- **Slot**: one replaceable thing in the scene (outfit, car, poster, building, corner building). On the photo it is a
  box with a label. The boxes blink a few times the first time you open a scene, so you can see them all.
- **Part of the base**: something in the photo that is not a slot yet (the taqueria). Its box is dashed, its label
  ends in "+", and hovering it says "make it a slot". The bus shelter has no such box: it already holds two slots, the outfit and the poster.
- **Take**: one version of the whole photo. The Austin stop scene ships with 13 of them.
- **The take the scene stands on**: the take the next Swap will change. Under the photo it says so.
- **Shelf**: the grid of small pictures in the side panel when you open a slot. It is what you can pick from.
- **Make 4 for this spot**: the studio looks at that exact spot in the photo and makes 4 new pieces that fit there.
- **Made for this spot**: pieces from a Make. They come first on the shelf, with a ring, under the line "made for
  this spot".
- **Cast**: putting a piece on hold for a slot. Nothing is redrawn yet. The app calls it "staged". **Cast** is also
  the name of the list on the right: one row per slot, with what fills it now.
- **Uncast**: taking that hold off again.
- **Swap**: doing it. The photo is redrawn with every staged piece. The result is a new take.
- **Stored replay** (live calls off): the app only shows again what was really made before. Free and instant, but
  only for the exact same request, in the same order.
- **Live calls** (the switch at the top, "Off: replays what was made before, free"): when on, the app really makes
  new things with paid AI services (about $0.06 a picture). The practice copy has no keys, so it can never spend.
- **Ready**: a green badge. This one is stored and replays instantly, for free.
- **Live** / **needs live calls**: an orange badge. This one was never made here. It needs live calls; next to Swap
  and Make 4 one line says the cost and what the switch does ("needs live calls (about $0.06) · off: replays only").
  You can still click it; the app explains what to do. When nothing from the chosen studio replays at this take, a
  line above the shelf says which studio does, with a button to show it (or that none does).
- **Not yet**: an orange badge. This one is stored, but for a later take: it replays once the swap it names is done
  ("not yet: replays after the outfit swap"). Do that swap first.
- **Stored**: an orange badge. The picture is stored, but the app may need one look (a vision call) to find the
  slots in it. Off the demo path only.
- **In take**: this piece is already in the photo. Picked, the Swap button turns grey and says "Already in this take".
  Pick another piece and its picture shows beside its name.
- **Use this take**: makes an older take the one the scene stands on again. Nothing is deleted.
- **Undo swap**: the same thing, one step back: back to the take before the last swap.
- **Before/after slider**: the bar under the photo after a swap. Drag it to compare with the take before.
- **Shoot**: redraws the whole street from scratch. It is switched off on this page because it spends.
- **Graph**: the button at the top right (or the ` key). It shows the ComfyUI wiring behind the app, full screen.
  While the app is up, that wiring is fully hidden. You don't need it to edit. Press **Back to Boson** to come back.
- **The grey line under the photo**: which take this is, what it was made from and what drew it ("take 10 · edit of
  take 09 · made with Nano Banana 2.1"). A take drawn on your own machine says "made with FLUX 3 Klein (local)". The
  codes behind it are under **details**; you never need them.
- **Remove this slot**: in a slot you made yourself (the corner building), it turns back into part of the photo.
  Free. Every take stays. It is offered only while the slot shows the base photo: after you swap a piece in (the
  hatch), the panel says the piece stays in the picture until you Undo or swap it.
- **Status line**: the line at the very bottom. Every answer from the app appears there, in green (it worked),
  orange (nothing was made, or the app held back, and why) or red (something broke).

## The models, and where they run

Two kinds of model do the work.

- **Open weights**: the model itself (a big file of numbers) is published. Anyone can download it and run it on their
  own machine, or on a rented one. Here: FLUX 3 Klein (draws pictures), Qwen3.8 (writes, and looks at pictures to
  find things), BiRefNet (cuts the person or the car out of a picture).
- **Closed**: you can only reach the model through a company's service. You send a request and get a result back,
  but you never hold the model. Here: Nano Banana 2.1 (pictures), Claude (writing), Gemini (finding things in a
  photo), and the LTX and Omni video models (through Comfy's partner nodes).

This is about the model, not about Boson's own code. Boson's code is open source either way.

**On your own machine**, with the open-weights models, nothing is sent out:

- **Who draws**: FLUX 3 Klein, in ComfyUI on your own graphics card.
- **Who writes**: Qwen3.8, instead of Claude. The studio's writing (its rules, the briefs for each round) comes from it.
- **Who finds things in the photo** (Locate): Qwen3.8 again, the version that can see pictures.
- **Who cuts out the person or the car**: BiRefNet, which ships with ComfyUI.
- **One graphics card**: on one card with 24 GB of memory, the writer, the picture model and the seeing model don't
  fit at once. They take turns. That is why it is slower: a studio round took about 17 minutes on our card, against
  about 2.5 minutes in the cloud. A scene's shoot and two swaps took about 7 minutes.
- **Motion**: turning a take into a short clip still needs a cloud video model. There is no open one on the machine yet.

Both kinds sit behind the same switch. Pictures have one setting called **backend**: `local` for your own machine, or
a cloud service (Nano Banana 2.1) when you have a key. Locate has a model name (`local:...` or Gemini), and the writer
is set once for the whole machine (Qwen3.8 or Claude). The studios don't change either way: they never name a model.
Out of the box, Boson uses the cloud ones (Nano Banana, Claude, Gemini).

How this copy was made: the studios and the Austin street were made with Nano Banana pictures, words written by
Claude, the author's red and green dots, and Gemini finding the boxes. The machine-only path has run too: one studio
round and one scene (a shoot and two swaps), on 2026-10-27. The grey line under each take tells you which model drew
it.

We tested it once (2026-10-28): the same scene from the same prompts, drawn in the cloud (A), all on one home graphics card (B), and mixed (C, the cloud street with the takes drawn at home). The author rated A and C equal on 11 of 12 pictures and B worse, for how its pictures were framed, not for their detail. The scene you get is A.

## The one workflow

Every edit is the same four steps. The side panel shows them as a row of four boxes and lights up the one you are on.

1. **Pick a thing**: click its box on the photo (or its row in the Cast list on the right).
2. **Who makes it**: under **From**, choose a studio. Studios that fit the slot come first; others say "(other field)".
3. **Pick one**: click a piece on the shelf, or press **Make 4 for this spot** first and pick one of those. Look at
   its badge: **ready** is free and instant.
4. **Swap**: press **Swap**. The status line says "working…" with the step it is on, and a Cancel button. When it is
   done it says "New take 09 made." and the new take is on screen.

Then, if you want: drag the before/after slider to compare, or press **Undo swap** to go back.

## Simple edits

- **Change the car**: click the car. From: a car studio. Pick a piece marked ready (or Make 4 first). Swap.
- **Change the outfit**: click the woman. Pick an outfit. Swap.
- **Change the poster**: click the poster in the bus shelter. Pick the one marked ready. Swap. This works in stored
  mode now.
  It moves the scene to a new take, so before the demo, press Undo swap (or start the practice copy over).
- **Change two things at once**: open the first slot, pick a piece, press **Cast** (not Swap). Open the second slot,
  pick a piece. The Swap button now says "Swap 2: car, outfit". Press it. One new take with both changes.
- **Take a hold off**: in the slot panel, press **Uncast** next to "Staged for the next swap".
- **Replace something that isn't a slot yet**: click its dashed box (the taqueria). Type what it is ("the corner
  building") and where ("on the left corner of the street"). Under **Filled by**, choose a studio. Press **Make it a
  slot**. It is free and makes no picture. Now it works like the other slots. Changed your mind? Open it and press
  **Remove this slot** (Undo any swap into it first).
- **Ask for something specific**: in a slot, type your idea in the box above Make 4 (it's optional). Then press
  Make 4 for this spot. New words mean a new request, so in stored mode it will need live calls. The box keeps your
  words for that slot until you reload the page: empty it to get back to the stored request.
- **Look at an older take**: click it in the Takes strip under the photo ("09 · outfit swap"; hover for more). It
  says "viewing only".
- **Go back to an older take**: while looking at it, press **Use this take**. The next Swap changes that take.
- **Undo the last swap**: press **Undo swap (back to take NN)** under the photo. The undone take stays in the strip.

## The one rule that trips people up (stored mode)

With live calls off, the app can only replay what was already made, **exactly**: same studio, same take, same words,
same order. The badges now tell you before you click. **Ready** will work. **Live** and **not yet** will not, in
stored mode; the app says so in orange. On a machine with keys it offers a button to turn on live calls; the practice
copy has no keys, so there it says "This copy has no keys, so it can only replay. Pieces marked ready replay."

That is why the demo has a fixed order. For example, the hatch corner reads **not yet: replays after the outfit
swap** at take 08. That is right: it was made after the outfit swap, on take 09. Do the outfit first and it turns
**ready**.

## What the messages mean

The status line at the bottom is the answer. (ComfyUI's own pop-ups, "Job queued" and the like, are hidden while the
app is up. In Graph view they only mean a request ran, not that anything was made.)

Green: it worked.
- **"New take 09 made."**: the swap worked. The new take is on screen.
- **"4 pieces made, replayed from before (no call)."**: the Make worked, for free.
- **"The corner building is now a slot, filled by the architecture-real studio."**: Make it a slot worked.
- **"The corner building is part of the picture again, not a slot."**: Remove this slot worked.
- **"Ready to swap: car. Press Swap to make the new take, or Uncast."**: a piece is on hold for that slot.
- **"Undo swap: the scene stands on take 08, so the next Swap edits it."**: the undo worked. Same for Use this take.

Orange: nothing was made, and here is why.
- **"This exact swap was never made, so there is nothing to replay."**: that piece was never swapped into this take.
  Pick one marked ready, or follow the demo order.
- **"Nothing was made for this exact request before (this studio, this take, these words)..."**: that Make was never
  done. Use the demo's studio and words, or leave the idea box empty.
- **"Nothing to swap: pick a new piece for a slot first"** or **"Nothing changed since take 08"**: you pressed Swap
  with no new piece picked.
- **"Nothing new: this picture is already take 08."**: the swap would give a take you already have.
- **"The corner building isn't a slot of this take yet"**: click it on the photo and press Make it a slot first.
- **"Boson can't find the slots in this new picture without a vision call."**: the app would need to look at a new
  photo, which costs a call. Stay on the demo order.
- **"(Swap still edits take 04: a newer shoot.)"**: Use this take went to a take older than the last full redraw. The
  next swap still changes the newer one. Not a problem for the demo.
- **"Stopped: nothing was made."**: you pressed Cancel.
- **"You have an unapplied swap (outfit). Swap or Uncast it before opening Posters."**, with an **Uncast** button: you
  clicked another studio or scene while a piece was on hold. Nothing moved. Press Uncast (the app then opens what you
  clicked), or go back and press Swap.

Red: something broke, or the app refused.
- **"Live calls need a key, and this box has none."**: you turned live calls on, on a machine with no keys (the
  practice copy). Press **Turn live calls off**.
- **"Saving didn't finish ... Nothing changed: the scene is as it was."**: the new take could not be saved (another
  save still running, or a full disk). The app put everything back. Try again in a moment.
- **"This scene's files were changed outside Boson, so Boson won't save over them."**: someone edited the scene's
  files by hand. Nothing was made. Undo that edit, then try again.
- **"The corner building still shows its own piece ..."** (orange): Remove this slot while its piece is in the take.
  Undo that swap first.
- A red line naming slots, with **Uncast** buttons: other pieces are on hold. Press Uncast, or press Swap to apply
  them all.

Buttons that are greyed out say why next to them (for example, "off on this page: a Shoot re-renders the whole set").

## Trying it

Everything below replays what was made: no key, no spend. Install as in the README, open
http://127.0.0.1:8188/boson/app, and click **Austin stop** under Scenes.

Good things to try: swap the poster and press Undo swap; tick live calls and read the red message; click a live
piece and read what it says; make the streetcar a slot, then press Remove this slot. Every one of these is a commit
in your working copy under `~/.cache/boson`, so nothing you try touches the shipped bundles.

A walkthrough of everything that ships, scene by scene: [TOUR.md](TOUR.md).
