# Short Story Reviewer

A small web app. A writer uploads or pastes a short story, fills in a short
brief, and gets back an editorial letter plus notes located in the
manuscript, produced by running the editorial method one stage at a time.
By default it diagnoses and never rewrites the writer's prose.

Python (FastAPI) with the Anthropic Python SDK and python-docx. Plain HTML,
CSS and JavaScript, no build step.

## Run it locally

Python 3.10 or later.

```sh
cd short-story-reviewer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=...        # server-side only
uvicorn reviewer.main:app --reload  # http://127.0.0.1:8000
```

Put the method files in `content/` first (see `content/README.md`). Without
the method, the page loads but runs are switched off.

To try the interface with canned responses and no API key:

```sh
python scripts/preview_server.py
```

## Tests

```sh
pytest                          # offline: fake model, real docx, real counts
python scripts/acceptance.py    # live: the three test stories through the API (costs money)
```

The offline suite covers the counting module, upload reading, the docx
annotator (run merging, single-run anchors, the unique-phrase fallback, the
text-unchanged check, validation), the pipeline (stage order, skipped
layers, cached prefix, sampling, retries, cancellation, rewrite mode), the
market notice and the API (rate limits, caps, access code, no echo of story
text in errors).

The acceptance script runs Saki's "The Open Window", Poe's "The Cask of
Amontillado" and Wells's "The Country of the Blind" (public domain, from
Project Gutenberg, in `tests/fixtures/stories/`), as fragmented .docx
uploads. It checks what code can check and prints the rest as a reading
checklist.

## How a run works

1. **Story.** Paste, or upload .docx, .txt or .md (up to 3 MB). The page
   shows the word count and length band (flash under 1,500 words, short story
   under 7,500, novelette 7,500 to 17,500) and what the counting module found.
2. **Brief.** Market (optional), draft stage, level of edit, the writer's
   questions, UK or US conventions, and the mode: diagnosis only (default) or
   diagnosis plus suggested rewrites.
3. **Market notice.** Choosing a market shows its AI-policy wording, quoted,
   with the date it was checked (`data/markets.json`). If the market bars AI
   writing, editing, assistance or use at any point, rewrite mode is
   switched off, and the server refuses it too.
4. **Run.** The page shows the estimated cost, then progress through the
   stages.
5. **Results.** The letter on screen; the letter as .docx and .md; for .docx
   uploads, the manuscript with margin comments.

### The stages

One model call per stage. Each receives the method (system prompt), the
story, the brief and every earlier stage's output, and returns JSON with
quoted anchors.

| # | Stage | Default model | Notes |
|---|---|---|---|
| 1 | Cold read | Sonnet 5.5 | reaction log tied to quotations |
| 2 | Design statement | Sonnet 5.5 | also classifies register and whether the story is speculative |
| 3 | Scene map and structure | Sonnet 5.5 | names the turning point and climax |
| 4 | Genre layer | Sonnet 5.5 | speculative fiction only; loads the report's SF/fantasy sections |
| 5 | Register layer | Sonnet 5.5 | comic, deadpan or dark registers only; loads matching report sections |
| 6 | Line pass | Sonnet 5.5 | gets the deterministic counts; over 5,000 words, samples opening, turning point, climax and ending |
| 7 | Triage | Opus 5.5 | three to five headline issues, pattern notes, taste notes, margin notes |
| 8 | Editorial letter | Opus 5.5 | in the method's order; suggestions only in rewrite mode, in their own field |

The letter is rendered from the JSON. Before the line pass, code counts
lower-case speech after a comma or colon, speech verbs other than "said",
exclamation marks outside speech, ellipses, filter verbs, name variants,
straight versus curly quotation marks and candidate tense shifts, and passes
the counts in as data. Code counts; the model judges.

### Located notes in the .docx

Triage returns each margin note with a short exact quotation. The annotator
removes `w:lastRenderedPageBreak` and `w:proofErr` markers, merges adjacent
runs with identical formatting, then matches each quotation inside a single
run only (tolerating curly versus straight quotes, dashes and whitespace).
If the quotation is not found or not unique, it falls back to the longest
shorter phrase from it that is unique (at least two words and a third of the
quotation); otherwise the note is listed as unplaced rather than guessed.
After writing, it extracts the plain text of the upload and of the annotated
file with an independent extractor and refuses to return the file unless they
are identical, then validates the package (comment parts, relationships, id
pairing, range order, reopening).

## Configuration

Defaults are in `reviewer/config.py`. Override any part with a JSON file
named by `SSR_CONFIG`, for example to run Opus throughout:

```json
{"stages": {"cold_read": {"model": "claude-opus-5-5"}, "design": {"model": "claude-opus-5-5"},
            "scene_map": {"model": "claude-opus-5-5"}, "genre": {"model": "claude-opus-5-5"},
            "register": {"model": "claude-opus-5-5"}, "line": {"model": "claude-opus-5-5"}}}
```

Each stage has a model, an effort level and an output cap (`max_tokens`,
which covers thinking as well as the answer). A stage that hits its cap is
retried once at 1.5 times the cap if the run stays under the per-run limit.
Environment variables are listed in `.env.example`.

### Cost

Prices per million tokens (October 2026): Opus 5.5 $4 input, $20 output,
$0.20 cache read; Sonnet 5.5 $2, $10, $0.20. Cache writes cost 1.25 times
input. (The build brief gives Sonnet 5.5 cache reads as $0.10; the API
reference current at build time says $0.20, which is what the app uses.)

The method and story are cached: the first stage on each model writes them,
later stages read them at the cache price. With a 40,000-character method,
the planning estimates are:

| Story | Opus throughout | Default split | Sonnet throughout |
|---|---|---|---|
| 15,000 words | ~$0.93 (max $1.58) | ~$0.79 (max $1.24) | ~$0.49 (max $0.82) |
| 3,000 words | ~$0.61 (max $1.47) | ~$0.49 (max $1.08) | ~$0.32 (max $0.75) |

The page shows an estimate before every run and the actual cost (from the
API's usage counts) after it. Calibrate `reviewer/cost.py` against real runs.

## Guardrails

- **No rewrites by default.** Every stage is told not to supply replacement
  prose. In rewrite mode, suggestions exist only in the letter's
  `suggestions` field, labelled as suggestions, and never reach the
  manuscript file. In diagnosis mode the app also flags any quotation in the
  letter that is not in the story.
- **Voice.** Every stage is told to ask whether an oddity is the joke in
  comic or deadpan writing (checklist M8) and that British spelling and
  punctuation are a valid house style.
- **Privacy.** Stories arrive inside JSON requests (files base64-encoded, so
  nothing is spooled to a temporary file), are processed in memory, are never
  logged, and are dropped when the request ends. Validation errors never echo
  the submitted text. The page and `/privacy` say so.
- **Market facts** live in `data/markets.json` with the name, URL, length
  limits, AI-policy wording (quoted) and the date checked, shown wherever the
  facts appear. Recheck them; they go stale.
- **API key** is read by the SDK from `ANTHROPIC_API_KEY` on the server and
  never reaches the browser.
- **Refusals.** Requests opt into Anthropic's server-side fallback
  (`fallbacks: "default"`), so a safety-classifier decline is retried on the
  recommended fallback model within the same call.
- **Limits.** Per-IP rate limits, a per-run cost cap (checked against the
  worst-case estimate), a daily spending cap, and an optional access code.
  These are in-process; on serverless hosting each instance counts
  separately, so also set a spend limit on the API key in the Anthropic
  Console.

## Deploying

A full run takes several minutes and streams progress, so the host must
allow long-running streamed responses.

- **Any long-running Python host** (Render, Railway, Fly.io, a VPS):
  `uvicorn reviewer.main:app --host 0.0.0.0 --port $PORT`, with the root
  directory set to `short-story-reviewer`.
- **Vercel:** `app.py` exposes the app and `vercel.json` raises the function
  duration and bundles the static, data and content folders. Set the
  project's root directory to `short-story-reviewer` and add the environment
  variables. Function duration limits depend on the plan, and request bodies
  are limited to 4.5 MB (hence the 3 MB upload limit). This configuration
  has not been tested on Vercel yet.
