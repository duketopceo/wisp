# Demo media

Real recordings of real turns, made the same way each time. Rough and honest
beats polished: nothing is faked, sped up or scripted around the model.

## The five scripts

| script | shows | proof (must be in the decision log) |
|---|---|---|
| `draw-and-teach` | draw a ring on the screen, ask, hear it explained | answered, transcript has "what does this" |
| `circle-and-ask` | ask where a setting lives, get pointed at it | answered, transcript has "where" |
| `dictate-a-reply` | dictate into the focused field, nothing sent | answered, transcript has "reply" |
| `helper-finishes` | background helper finishes and says so | answered, transcript has "background" |
| `day-cost` | what the day cost, from the local ledger | answered, transcript has "cost" |

Scripts live in `scripts/demo/scripts/*.md`: header lines (`title`,
`length`, `setup`, `proof`), `## steps`, and `## captions` with one line per
channel (`readme`, `release`, `omarchy`, `x`, `short`). A script must carry a
`proof:` line and all five captions or the harness refuses to load it.

## Recording

```sh
python3 scripts/demo/record.py --list
python3 scripts/demo/record.py --dry-run draw-and-teach     # plan only
python3 scripts/demo/record.py draw-and-teach --out build/demo
python3 scripts/demo/record.py draw-and-teach --out build/demo --publish
```

Needs `wf-recorder`, `ffmpeg`, `ffprobe` and a running daemon on the desktop
you record. Optional: `tesseract` (frame text check), `espeak-ng` (`--tts`,
speaks the words instead of you).

The harness starts `wf-recorder --audio`, drives the daemon with
`wispd trigger start|stop`, runs the steps, then:

1. **Proof.** The script's `proof:` line (`field=value`, `field~substring`,
   `field>=n`, joined with `&&`, dotted paths into a `decisions.jsonl`
   record) must be satisfied by a decision logged since the recording began.
   If not, the raw file is deleted and nothing is written: a demo that did
   not do what it claims fails.
2. **Blanking.** Once a second the same deny policy as whole-screen privacy
   (`wisp/redact.py`, `[cua]` deny lists) lists every visible sensitive
   window. Those rectangles are burned out of the encode (`drawbox`, per
   second). If the window list cannot be read, recording stops: an unblanked
   screen is never encoded.
3. **Text scrub.** Captions and any error text go through the same home path
   and token patterns as crash reports; a caption that still matches fails.
   With `tesseract` installed the encoded video is sampled at 1 frame a
   second and a visible home path or token fails the run; without it the
   run says "not checked", so keep the clip's setup clean (see each
   script's `setup:` line).
4. **Size caps.** Video at most 5 MB (re-encoded once at a lower quality,
   then it fails and the script must be cut), poster PNG at most 250 KB.

Output in `--out`: `<name>.mp4`, `<name>.poster.png` and
`<name>.<channel>.txt` for each channel. `--publish` copies the mp4 and
poster to `assets/readme/` and fills the README block between
`<!-- hero:start -->` and `<!-- hero:end -->`; `tests/test_readme_media.py`
then holds both to the caps.

## What this does not do

It uploads nothing, posts nothing and holds no credentials for any channel.
Cutting one recording for each channel and posting it is a person's job.
