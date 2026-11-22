# Opening speech: transcript and findings

The opening speech is useful supplementary context for the [challenge brief](challenge-a.md),
especially its emphasis on selective review, quantity aggregation and hidden scope. The transcript
is machine-generated and useful for understanding the discussion, but is not a verified verbatim
record or an authoritative amendment to the written brief.

- [Full raw transcript](opening-speech-transcript.txt)
- [Timestamped transcript (SRT)](opening-speech-transcript.srt)

## Source and quality

Source: `WhatsApp Audio 2026-11-20 at 17.34.32.mp4`, identical to
`WhatsApp Audio 2026-11-20 at 17.39.32.mp4`. The recording is 384.186 seconds long, in English,
with two speakers, and starts mid-sentence. Timestamps are relative to this recording.

Source SHA-256: `5f82fd704846281aea6c4acef3160ab45b67432c63bf772903607f03d1256ee2`.

Transcribed locally with whisper.cpp, comparing small.en and medium.en-q5_0. The saved raw
transcript and SRT are the medium-model outputs, unchanged. Key passages received a secondary
audio-content review, but the full transcript was not manually verified. Original audio remained
unchanged; downloaded models and temporary audio were removed after extraction.

Known recognition problems include “GAP” for GAEB, “Axel” for Excel, company/place names and
the currency wording in the audio-system example. One project-size example and the phrase
around “summary and duplicate” are unclear. The notes below interpret the clearer passages;
they do not silently correct the raw transcript. No measured word-error rate is available.

## Useful additions and clarifications

| Recording time | Point | Interpretation and boundary |
| --- | --- | --- |
| 01:12–01:24 | “Start with error detections. That's the most important part. Once that works move on to risk.” | Error detection takes priority over risk features. |
| 01:24–01:33 | Price suggestions and material-price what-if scenarios follow “If you still have time.” | Both are stretch goals in the speech. The written brief lists what-if analysis as a milestone; retain this distinction. |
| 01:34–01:54 | Nine anonymized BoQs; two with actual hours, invoiced quantities and change-order lists. | Describes the promised data, not a verification of repository contents. |
| 01:54–02:07 | Upload a BoQ and receive a risk report; pitch from an estimator's perspective. | Demonstrate how the tool changes bid preparation. |
| 02:08–02:18 | “Please keep it inside the hackathon and don't put into public repositories.” | Supplied data remains restricted despite anonymization. This is not permission to share it with external services. |
| 03:14–03:38 | An example contrasts 400 chairs with only 50 tables. | Look for suspicious relationships across positions; do not encode a universal one-chair/one-table rule. |
| 03:39–04:32 | Related items may be split across many positions; the estimator manually sums concrete across a roughly 9,000-item list. | Semantic grouping and quantity rollups could save time. Preserve units and material/specification distinctions rather than merging everything labeled concrete. |
| 05:00–05:44 | A small, vaguely specified audio-system item might represent €50,000 or €200,000 of work. | Flag hidden scope and pricing uncertainty; do not invent a precise estimate. Amounts are illustrative. |
| 05:52–06:08 | “The real challenge is not about processing all these 9,000 items ... figuring out what 100 of them are the most important ones.” | Prioritize a selective, actionable review queue. The numbers are illustrative, not a hard cap or acceptance threshold. |

The unclear phrase around 04:49–05:00 should not by itself become a mandatory duplicate-detector
requirement. The preceding examples more clearly establish aggregation and cross-item plausibility.

## Product implication

An appropriate hypothesis is to help an estimator find the important issues among thousands of
positions, inspect their evidence and decide what to clarify or price. This supports error-first
review, guarded aggregation and uncertainty warnings; it does not establish the accuracy of any
implementation or authorize automatic changes to a bid.
