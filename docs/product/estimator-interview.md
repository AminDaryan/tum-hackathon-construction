# Estimator interview: transcript and findings

A conversation with a practising estimator during the hackathon, after the
[opening speech](opening-speech.md). It adds concrete workflow detail for the
[challenge brief](challenge-a.md): how an estimator prices a bid in RIB iTWO, a real failure caused
by hidden scope, and which data and integration constraints a tool must respect. The transcript is
machine-assisted and is not a verified verbatim record or an amendment to the written brief.

- [Full transcript (English and German)](estimator-interview-transcript.txt)
- [Timestamped transcript (SRT)](estimator-interview-transcript.srt)

## Source and quality

Source: `WhatsApp Audio 2026-11-20 at 20.08.10.mp4`, 19:49 long, recorded 2026-11-20 around 19:56
Europe/Berlin. Mostly English with German passages, several speakers, overlapping and background
speech. Timestamps are relative to this recording.

Source SHA-256: `60cd1035a4671fad6a009c134da8c449bf9ba5309a03310d1c1be5cf51bb2b71`.

Transcribed locally with whisper.cpp using the multilingual medium-q5_0 model, translation off.
A large-v3-turbo comparison pass hallucinated in the mixed-language section and was not used.
German passages misrendered as English were restored from focused audio review of roughly 01:30–03:35,
06:50–12:00 and 14:30–17:40; the rest was not manually reviewed. German is kept as spoken.
Unrecovered speech is marked `[unclear]` or `[unverständlich]`. Speakers are not separated. Original
audio remained unchanged; downloaded models and temporary audio were removed.

Least reliable: the opening question, the problem statement near 03:47, the document inspection at
06:50–11:40, the file codes near 16:48 and the software names near 17:16 and 19:18. Statements are
the speakers' own and have not been independently verified.

## Findings

| Recording time | Point | Interpretation and boundary |
| --- | --- | --- |
| 00:00–01:02 | The relevant user is the bidder at the construction company: the tender arrives with positions, units and quantities but no prices. | Build for the contractor's estimator, not the owner preparing the tender. |
| 01:02–01:41 | The estimator says every German construction company uses RIB iTWO and calls it old school. | A strong claim about this speaker's view, not a measured market share. Fits the [documented use of iTWO at Züblin](https://www.mtwocloud.com/pdf/567fd9_1d3e0efaa58b4d2cb7f576531ec93123.pdf). |
| 02:02–03:41 | Each price combines material, labour and machine costs. Materials are totalled across the project, suppliers are asked for prices, and the price is copied to every matching position. Other rates come from the iTWO database, earlier projects and framework agreements (Rahmenverträge); labour comes from experience or historical data. | Aggregating quantities feeds a real purchasing step. A tool that totals comparable materials and drafts supplier price requests saves concrete work. |
| 03:41–04:16 | Most problems come from gathering fragmented data by hand. | Consolidating sources is part of the value, not only checking them. |
| 04:16–06:55 | A position for excavating frozen soil (ground frozen with nitrogen) was priced with a small surcharge. The drawings required manual excavation in many small steps, which made it far more expensive. The speakers say “10 times” and then “100 times”. | Flag positions with no historical precedent and link them to the documents that explain the method. The multipliers are conversational, not verified losses. |
| 07:28–11:40 | Participants inspect the supplied data: GAEB files and Leistungsverzeichnisse, mostly without prices, and no matching plans or BIM models. One speaker works at Thinkproject. | Checking BoQs against plans or BIM needs matching models; unrelated IFC files cannot show consistency. Priced projects or public reference prices are needed for price comparison. |
| 11:37–12:41 | The estimator checks bills of quantities against 2D plans and 3D models manually and would value automation. Totalling comparable items gives an overview of project size. | Supports quantity checks against drawings and models when they are available, and guarded aggregation. |
| 13:18–14:52 | The company restricts which AI tools may be used; Microsoft 365 Copilot is approved. General assistants lack interfaces to estimating software and handle plans and 3D models poorly. | Data handling and deployment constraints matter. Integrating with the existing software is preferred to replacing it. |
| 14:52–15:28 | Sending price requests to subcontractors should be automated. | Candidate workflow after aggregation. |
| 16:31–17:37 | A speaker says, for GAEB exchange phases, “83 never, 86 always, 84 depends” on whether prices are included. | Consistent with GAEB: 83 is the tender request without prices, 84 the bid with prices, 86 the awarded contract. The exact file extensions were not reliably heard. |
| 18:10–19:10 | A BoQ has very many small positions nobody cares about. About 20 numbers make up roughly 80% of the price; rank them and treat the rest as noise. Mispricing a large item is a risk, missing a small one is not. | Reinforces the opening speech: a ranked review of the major cost and risk drivers. The 20/80 split is illustrative. |

Around 17:20 someone answers “yes” when asked whether the software runs on a Mac, during a confused
exchange about software names and formats. RIB's
[system requirements](https://www.rib-software.com/pdf/de/itwo-v2026-systemvoraussetzngen-02-2026-4.pdf)
list Windows only.

## Product implication

The interview supports a tool that works alongside the estimator's existing software: it totals
comparable quantities for supplier requests, flags unusual or unprecedented positions with the
documents that explain them, and ranks the few positions that drive most of the price. Checks
against plans and models depend on getting matching data. None of this establishes the accuracy of
an implementation or authorizes automatic changes to a bid.
