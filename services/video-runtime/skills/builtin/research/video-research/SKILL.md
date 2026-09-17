---
name: video-research
description: Ground a video's creative direction in real references before anything gets generated. Runs batched web searches for visual precedents, sound, technique, and platform taste, then synthesizes 3 genuinely different directions. Use when the brief is vague, when the user asks for 参考 / 好点子 / 特效 / 爆款 / reference / inspiration, or before writing shot prompts for any video type — MV, short drama, product ad, trailer. Invoke with $video-research.
---

# Video Reference Research

Adapted from the OpenMontage Research Director. You research the subject so the shot
prompts that follow are grounded in real references, real moods, and real audience
expectations — before any creative decision is made or any money is spent.

This methodology runs inside the active Harness loop. Read this Skill, perform the
searches directly, and keep the findings in the current planning context; do not
schedule a separate research capability or agent task.

**You do not make the creative decision and you do not generate anything.** You gather
raw material and hand back directions for the active workflow to choose from.

The output is worth having only if it is specific. "Dark and moody" is not a finding.
"Low-key tungsten key, shallow depth of field, cuts landing on the downbeat around 1.2s"
is a finding. Everything below exists to get you the second kind.

## Tools

`web_search` is your research tool. `skill_http_get` reads one specific page when a
search result is worth opening in full.

Know the limit: search returns **text about** videos — titles, descriptions, breakdowns,
comments, articles. It does not watch footage. So mine the writing *around* good work
(breakdowns, making-of, tutorials, cinematography discussion) rather than expecting a
search result to tell you what a shot looked like. Direct footage reading is a later
addition to this skill; do not pretend you have it.

Cite only URLs that came back in a search result. A URL written from memory is a
guess, and a guessed link that resolves to the wrong page is worse than no link.
Every URL you cite must come from the pages search actually returned during this run.
Writing a plausible URL from memory costs you a retry, so
copy the one in front of you — and when you have a finding but no link, keep the
finding and leave the URL empty rather than inventing one to fill the field.

## Process

### Step 0: Check for a reference the user already loves

If the brief arrived with a video the user wants to riff on — an analysis artifact, a
link, or just their description of it — this is a reference-driven production.

Standard research: "What visual/emotional language fits this subject?"
Reference-driven research: "What cinematic approach would DIFFERENTIATE us from the
reference while keeping the elements the user loved?" + "What mood/tone territory
is adjacent but unexplored?"

In `reference_context` record:
- The reference's cinematic language (shot types, pacing, color palette)
- What emotional territory it occupies
- Adjacent emotional territories we could explore instead
- How the reference's visual approach could be evolved or reinterpreted

Directions should position against it explicitly: "The reference uses X
mood/palette/pacing. We could try Y which creates [different emotional impact]
because [research finding]."

No reference? Leave `reference_context` empty and carry on.

### Step 1: Classify the brief

Extract before searching — searching without this produces generic results:

- **Subject**: What is this video about?
- **Source reality**: Does the user have footage, stills, audio, or nothing?
- **Motion requirement**: Is motion a hard requirement, or can it be still-led?
- **Mood hints**: Any emotional direction given? ("dark", "epic", "intimate", "raw", "hopeful")
- **Platform**: Where will this live?
- **Duration hint**: Short (15-30s), medium (30-90s), long (90s+)?
- **Delivery shape**: What kind of finished piece this is, from the brief.
- **Locked elements**: anything already committed — a song, a subject, a
  product, a script, what is on screen. These are brief facts. References
  must work *with* them, not against them. This capability searches from text
  only; it cannot see pixels. If media is in the brief but unnamed, write the
  visible facts first, then search.

### Step 2: Visual reference mining

Find real cinematic precedents that match the mood and subject.

```
SEARCH BATCH 1 — Visual References (run all in parallel)

Q1: "[subject] cinematic [mood hint]" site:youtube.com
    → Find: Existing trailers, brand films, or mood pieces for this subject.
Q2: "[subject] [delivery shape] visual style" (breakdown OR making-of OR tutorial)
    → Find: How professionals approach this type of visual storytelling.
Q3: "[mood hint] color palette cinematography" OR "[mood hint] color grading reference"
    → Find: Color and grade references that match the intended mood.
Q4: "[subject] [mood hint]" (short film OR brand film OR trailer) award OR festival
    → Find: Award-quality references — the ceiling of what this could look like.
```

For each reference, record:
- Title and URL
- What works visually (framing, color, movement, texture)
- What works emotionally (pacing, reveal structure, tension arc)
- Relevance to the user's brief

Then fill `landscape`. Each entry in `landscape.existing_content` carries:

| Field | What | Quality bar |
|-------|------|-------------|
| `title` | What the work is called | The real title, not your paraphrase |
| `url` | Where you found it | From a search result; omit rather than invent |
| `source` | Where it lives | `bilibili`, `youtube`, `douyin`, `blog`, 小红书 … |
| `angle` | The approach it takes | Name the approach, not the subject |
| `what_it_covers` | What it does well | Framing, colour, movement, texture, pacing |
| `what_it_misses` | What it leaves on the table | The load-bearing half — this is where our opening is |
| `engagement_signal` | Views, likes, comments | Whatever the result exposed; leave empty rather than guess |

Then summarise across them: `landscape.saturated_angles` is what has been done to death
and must be avoided, `landscape.underserved_gaps` is what nobody is doing yet. A
landscape with no gaps means you stopped searching too early, not that the space is
full.

### Step 3: Sound and music landscape

Skip Q5 if the song or audio is already locked; still run Q6.

```
SEARCH BATCH 2 — Audio References (run in parallel)

Q5: "[mood hint] [subject] soundtrack" OR "[mood hint] film score reference"
    → Music mood references.
Q6: "[mood hint] sound design" (cinematic OR film OR trailer)
    → Sound design approach: ambient, textural, percussive, silent.
```

Record the music energy and texture (not specific tracks) as each direction's
`mood_direction`. The sound design notes and whether the piece is dialogue-led,
narration-led or music-driven belong to the edit, not to that field.

### Step 4: Subject depth

```
SEARCH BATCH 3 — Subject Depth (run in parallel)

Q7: "[subject]" (story OR history OR origin OR significance)
    → Narrative depth that can inform visual decisions.
Q8: "[subject]" (visual OR texture OR detail OR close-up OR macro)
    → Texture and material references for the subject itself.
Q9: "[subject]" "[current year]" (trend OR development OR news)
    → Current relevance — is there a timeliness angle?
```

### Step 5: Motion and camera language

```
SEARCH BATCH 4 — Technique Research (run in parallel)

Q10: "[mood hint] camera movement" (technique OR cinematography)
     → Which camera movements suit this mood (handheld for raw, steadicam for contemplative, whip pans for energy).
Q11: "[mood hint] editing rhythm" OR "[mood hint] pacing" (film OR trailer)
     → Editing tempo references.
Q12: "[delivery shape] structure" (beat sheet OR pacing OR breakdown)
     → Structural templates for this delivery type.
```

### Step 6: Audience and platform

```
SEARCH BATCH 5 — Audience (run in parallel)

Q13: "[subject] [platform]" (best OR viral OR most watched)
     → What performs well on the target platform for this subject.
Q14: "[subject]" site:reddit.com (mood OR aesthetic OR vibe)
     → How the community talks about and feels about this subject.
```

A usable hit is a work page (a titled video or note), not a search-results URL, a
download farm, or a blog that only mentions the platform. Usable hits go into
`landscape.existing_content`. If a result is empty, say so — do not invent a URL,
a title, or a play count.

### Step 7: Angle synthesis

From Steps 2-6, identify at least 3 genuinely different directions:

| Field | What | Quality bar |
|-------|------|-------------|
| `name` | 5-8 word title | A specific mood, not the subject restated |
| `hook` | One-sentence pitch | Must evoke a feeling, not explain the content |
| `type` | `mood_piece`, `tension_arc`, `reveal`, `intimate`, `epic`, `raw` | Categorize honestly |
| `visual_references` | Which found references inform this — each carries `description`, `url`, `what_works` | Real URLs from search results; `what_works` names the technique, not the vibe |
| `mood_direction` | Music mood: genre + energy + emotional arc | How the music moves, not who sings |
| `motion_commitment` | What motion is needed and how it gets made | Honest about capability |
| `grounded_in` | Which findings support this | Cross-reference your own findings |

**Direction diversity checklist:**
- [ ] At least one direction uses a different emotional arc than the others
- [ ] At least one direction emphasizes texture/intimacy over spectacle
- [ ] No two directions use the same primary camera approach
- [ ] Each direction is grounded in different visual references

### Step 8: Bibliography and handoff

Compile all URLs used. Minimum 5 sources. Each entry carries:

| Field | What | Quality bar |
|-------|------|-------------|
| `url` | The URL a search result returned | Never assembled from memory |
| `title` | The page's own title | As the search result gave it, not your paraphrase |
| `used_for` | Which section of the brief this source supports | landscape, a named direction, or research_summary |
| `reliability` | `primary`, `secondary`, or `anecdotal` | Omit rather than guess |

`research_summary` is one paragraph: the single most important insight from this
research and why it matters for the video.

Hand the active Harness loop `topic`, `research_summary`, `landscape`,
`reference_context`, `directions`, and `sources` in the current planning context.
Pass every one you filled — a field you omit is a batch of searching thrown away,
because nothing downstream re-derives it. Keep `type` in the list above, include at
least 3 existing works and 1 gap, list at least 5 sources, and use only URLs returned
by search.
Every Quality bar column in this file is yours to hold — nothing downstream will
catch a vague `motion_commitment` or a finding that restates the brief. A
Report the directions and the sources, and stop. The
active workflow's prompt writing consumes this. Do not schedule generation tasks
and do not pick the winner yourself unless the user asks you to.

## Execution constraints

| Constraint | Value | Why |
|------------|-------|-----|
| Max searches | 20 | Prevent infinite rabbit holes |
| Min searches | 8 | Ensure adequate coverage |
| Directions produced | 3 | Fewer is not a choice, more is not a decision |
| Sources cited | 5+ | A direction with one source is a hunch |

## Common pitfalls

- **Searching only for "cinematic"** — the word is overused and returns noise. Search
  the specific mood, texture, and subject instead.
- **Generic mood words as findings** — "dark and moody" is not a direction. "Low-key
  tungsten with shallow depth of field, like a Fincher title sequence" is.
- **Ignoring the source reality** — if the user has no footage, the research has to
  account for still-led approaches rather than ignoring the constraint.
- **Skipping audio** — video lives and dies by sound. A mood board with no sound
  direction is incomplete, even when the track is already chosen.
- **Fighting the locked elements** — a direction that works against what the
  brief already committed is not a direction.
- **Researching past the point of use** — stop once 3 directions are grounded.

## Never

- Cite a URL that no search result returned
- Claim you watched a video; search returns text about videos, not footage
- Run one batch and call it research
- Return "cinematic", "dark and moody", "high energy", or "eye-catching" as a finding
- Propose a direction needing footage or capability the user lacks without saying so
- Schedule generation tasks or pick the winning direction unasked
- Invent a URL, title, or play count to fill a slot
- Search without a named subject; write the locked facts first
