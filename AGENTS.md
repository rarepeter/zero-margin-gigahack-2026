Status: Hackathon ideation brief; not a final product or technical specification

We are still in the ideation phase. The logical blocks below describe responsibilities and information flow, not final services, technologies, models, interfaces, or team assignments. Those decisions should follow only after the team has validated the concept and agreed on the smallest convincing prototype.

## Hackathon context

Secure MOM is a challenge proposed by Medpark International Hospital for DeepTech GigaHack 2026. The event is a 48-hour prototype-building sprint, ending on the 27th of September, 2026 at 12:00. You are an AI agent doing the work, so assume your own working time which could be minutes/hours instead of human days, for example, for developing features.

Our goal is not to build a production hospital platform. Our goal is to demonstrate the core value proposition credibly, end to end, on our own hardware (Macbook Pro M4 Pro with 48GB of RAM - unified memory).

Meetings across a medical institution—clinical, financial, administrative, executive, operational, and crisis-response—contain important decisions, responsibilities, deadlines, domain-specific considerations, and technical detail. Today, producing reliable Minutes of Meeting (MoM) from these discussions requires someone who attended the meeting to reconstruct and compress the discussion manually, this being secretary work.

The MVP is institution-wide: it must support the hospital's medical, financial, administrative, and executive workflows without treating any one meeting category as an optional extension. Medical terminology can arise in any of these meetings, alongside logistics, cost, procurement, staffing, operations, and urgent-crisis discussions.

General-purpose meeting assistants do not adequately solve Medpark's problem because:

- confidential meeting information cannot be sent to external cloud services;
- meetings may switch between Romanian, Russian, and English, including within the same conversation or even the same sentence. Someone could be stuck explaining some idea in Romanian and switch to Russian, even for one word. Or vice versa.
- discussions contain specialized medical and technical terminology, including jargons;
- a transcript or generic summary is not enough—the hospital needs usable decisions and follow-up actions.

## The challenge

Create a functional, fully on-premise assistant that turns a medical-institution meeting recording into structured Minutes of Meeting while keeping all meeting information inside the hospital environment.

The central transformation is:

```text
Meeting audio
    → reconstructed multilingual discussion
    → identified meaning and outcomes
    → professional Minutes of Meeting with all relevant and important information, in one language chosen by the user
```

For our MVP, the meeting audio is the only input and the only source of meeting content. We do not assume that a meeting-type label, agenda, participant list, meeting title, written notes, location, or other metadata is available. The system must work from what can be heard in the recording, whether it was captured in a clinical room, a departmental cabinet or office with desks, a boardroom, or another hospital workspace, with traceability to the actual recording and explicit treatment of uncertainty.

User accounts, profiles, hospital integrations, and other user data are outside the core MVP scope.

## Mandatory challenge constraints

These are challenge requirements rather than optional product ideas:

- Runtime processing must be fully local and on-premise.
- No external AI API, cloud service, or external SMTP call may be used during runtime or the demonstration; violating this is disqualifying.
- Audio and derived meeting content must not leave the internal environment.
- The solution must handle Romanian, Russian, and English language switching.
- The solution must recognize specialized medical terminology, including local medical jargon.
- The result must be a structured MoM, not only a transcript or general summary.
- The result must identify decisions, action items, owners, and deadlines when they are present in the recording.
- The challenge's complete target flow includes local routing and delivery to a predefined distribution list through a local mail environment.
- The prototype must be able to run while disconnected from the internet.
- No dedicated hardware is supplied; development and the demonstration must run on the team's own equipment.
- Models and dependencies may be obtained during development, but everything required for inference and delivery must already be available locally during the offline demonstration.
- The challenge gives processing a 60-minute recording in under 15 minutes as an example performance target, not a hard jury time limit. The team should still measure and report processing time and test hardware because speed and reproducibility influence evaluation.

The proposed experience keeps audio as the only content input (in m4a, mp3 formats): the user does not need to supply a meeting type. The system may conservatively infer a likely clinical, financial, administrative, executive, operational, or crisis context from the recording to adapt wording, formatting, or routing, but it must not invent a category when the audio does not support one.

## Judging criteria and priorities

### 1. Security and architecture — pass/fail gate, then 20%

Any external inference, cloud, or SMTP call at runtime disqualifies the solution. The prototype must operate locally, protect audio and transcripts, and be reproducible on the constrained hospital hardware described in the challenge.

### 2. Linguistic accuracy — 30%

The system should handle abrupt Romanian/Russian/English switching, preserve medical terminology, and minimize transcription errors and hallucinations.

### 3. Output quality and structure — 30%

The system should produce useful meeting minutes, correctly distinguish actual decisions from general discussion, and identify actions, owners, and deadlines. A polished summary that misses operational outcomes is not sufficient.

### 4. User experience — 10%

Although UX represents 10% of the formal score, it is critical for adoption: any authorized hospital staff member who already has an audio recording should be able to submit it from the internal desktop portal in approximately one action, without entering metadata or supervising the process, and receive a clear indication when the MoM is ready within a reasonable processing time. How a phone recording reaches the desktop or server is outside the MVP; the guiding principle is that the solution must create less work than manually writing the minutes.

### 5. Presentation and team clarity — 10%

The team should explain the medical context, problem, choices, limitations, and demonstrated value consistently and convincingly.

### What this means for prioritization

Passing the offline-security gate comes first. After that, linguistic accuracy and MoM quality together represent the majority of the score. We should therefore favor a narrow, trustworthy audio-to-MoM experience over a broad interface with many secondary features.

## Our solution proposal

We propose an on-premise assistant application that accepts a recorded meeting from across the medical institution and produces a concise, professionally structured draft of the minutes that resembles what an accountable meeting participant would write after attending it.

The solution is not intended to reproduce every sentence. Its value is in compressing a long, multilingual, technically dense conversation into an accurate working document that preserves:

- the central subjects discussed;
- important clinical, financial, administrative, operational, or technical findings;
- confirmed decisions and conclusions;
- actions that need to happen next;
- explicitly stated owners and deadlines;
- risks, concerns, and unresolved questions, without overstating content that the recording does not support confidently.

The generated document is a draft until a person reviews it. Human review is a trust and safety mechanism, not a substitute for poor generation quality. The initial draft should already be useful and require substantially less effort than writing the minutes from scratch.

### Scope priority

The core MVP covers clinical, financial, administrative, executive, operational, and urgent-crisis meetings across the medical institution. It remains a single audio-to-MoM workflow, not separate products by department. The output must preserve relevant medical terminology wherever it appears, including in logistics, cost, procurement, or crisis discussions.

## Core product principles


| Principle                                                           | Practical implication                                                                                                                                                                          |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The recording is the source of truth**                            | Do not invent meeting titles, people, roles, decisions, owners, deadlines, clinical, financial, operational, or technical conclusions that are not supported by the audio.                     |
| **Missing information remains missing**                             | If an owner or deadline was not stated, mark it as not assigned/not stated or omit it according to the agreed format; never make a plausible guess.                                            |
| **Compression must preserve meaning**                               | Remove repetition, hesitation, and conversational noise while preserving negation, uncertainty, measurements, units, medical distinctions, and the difference between proposals and decisions. |
| **The transcript is an intermediate result**                        | Accurate transcription is essential, but success is measured by the quality and usefulness of the resulting MoM.                                                                               |
| **Important statements should be verifiable**                       | A reviewer should be able to compare important decisions, actions, findings, and uncertain terms with the relevant transcript text without requiring timestamps or other transcript metadata.  |
| **The system must be honest about uncertainty**                     | Highlight low-confidence terminology, unclear ownership, ambiguous deadlines, and conflicting conclusions instead of silently resolving them.                                                  |
| **Institutional usefulness is more important than generic fluency** | Produce concise, evidence-focused, domain-accurate, and action-oriented minutes rather than a fluent but vague summary.                                                                        |




## Proposed logical building blocks

These blocks describe the conceptual flow. They do not imply that each block must become a separate application or service.

### 1. Audio intake

Accept the meeting recording as the only content input and pass it into the processing flow. For the MVP, the transcription model handles the audio as provided; separate quality analysis, enhancement, and noise reduction are outside scope and can be considered later if testing shows they are necessary.

**Receives:** meeting audio  
**Produces:** accepted meeting recording

### 2. Multilingual institution-aware audio-to-text transcription

Convert the meeting audio into transcript text while preserving the order and the languages in which the discussion occurred. The transcript should remain in the Romanian, Russian, or English actually spoken rather than being translated into a single language, and should preserve medical, financial, administrative, logistics, and technical terminology—as well as names, numbers, costs, dates, measurements, and units—as accurately as possible. Speech reconstruction and transcription may be separate internal processing steps, but they form one logical block for the MVP.

**Receives:** accepted recording  
**Produces:** transcript text in the languages spoken during the meeting

Timestamps and other transcript metadata are not required for the MVP.

### 3. Institution-aware transcript-to-MoM generation

Transform the transcript text into structured, professionally worded minutes for clinical, financial, administrative, executive, operational, or crisis meetings. The block must identify the relevant facts and outcomes—including key topics, findings, decisions, actions, owners, deadlines, risks, disagreements, and open questions—while removing conversational repetition without changing clinical, financial, administrative, operational, or technical meaning. It must also check the draft against the transcript for unsupported conclusions, incorrect terminology, changed numbers, costs, dates, or units, missing negations, and confusion between proposals and decisions, highlighting uncertainty that requires human attention.

It must distinguish discussion from decisions, suggestions from assigned actions, possible deadlines from confirmed deadlines, and observations from confirmed clinical, financial, or operational conclusions. It must not invent identities, roles, facts, or outcomes that are not supported by the transcript.

**Receives:** transcript  
**Produces:** a review-ready structured MoM containing the relevant meeting facts and outcomes, with any uncertainty represented within the affected content

The internal layers needed to understand context, extract information, compose the document, and validate consistency are intentionally not defined here. The team members working on transcript-to-MoM generation will design and validate that processing approach.

### 4. Human review and final document

Allow an authorized meeting reviewer to correct important details, resolve highlighted uncertainties, and approve the result. Present the approved MoM as a clear document suitable for download and, for the complete challenge flow, local delivery to the appropriate distribution list.

**Receives:** review-ready MoM  
**Produces:** approved, distributable Minutes of Meeting

## Initial MoM content concept

The final format still needs validation with clinical, financial, administrative, and executive users. A useful starting structure is:

1. **Meeting subject** — inferred conservatively from the recording.
2. **Executive summary** — the purpose, central discussion, and overall outcome.
3. **Key topics discussed** — concise clinical, financial, administrative, operational, or technical summaries by topic.
4. **Evidence or findings reviewed** — relevant results, costs, measurements, observations, or technical performance.
5. **Decisions and conclusions** — only outcomes supported as agreed or concluded.
6. **Actions and follow-ups** — action, owner, and deadline when stated.
7. **Risks and concerns** — clinical, safety, technical, regulatory, or data-quality issues.
8. **Open questions** — unresolved matters or points requiring verification.

Uncertainty should be represented within the relevant decision, action, finding, or open question rather than as a separate MoM section. Empty or unsupported sections should be omitted rather than filled with generic text.

## MVP scope

### In scope

- One recorded meeting audio file as the source of meeting content.
- Clinical, financial, administrative, executive, operational, and crisis meetings across the medical institution.
- Local processing with no external runtime calls.
- Romanian/Russian/English language switching.
- Medical, financial, administrative, logistics, and technical vocabulary.
- Transcript generation as an intermediate result.
- Structured extraction of decisions, actions, owners, and deadlines.
- A concise, professional MoM draft that does not overstate ambiguous information.
- Human review of the generated draft.
- A final distributable document.
- A minimal path for demonstrating local routing and email delivery if required by the challenge.

### MVP boundary

The MVP begins when an institution-meeting audio file is already available for submission and ends with a reviewed, distributable MoM plus the minimal local-delivery demonstration required by the challenge. It does not cover recording transfer, user accounts, hospital/calendar/video/medical-record integrations, separate audio enhancement, collaborative workflows, automatic identification of unnamed speakers, or site-specific room/cabinet capture hardware. Speaker diarization is optional only if it improves attribution without risking the core flow.

## Definition of a convincing prototype

During the demo, the team should be able to:

1. Disconnect the machine from the internet.
2. Provide representative multilingual recordings from the institution's clinical, financial, administrative, executive, operational, or crisis workflows through the minimal portal journey.
3. Process the recording locally.
4. Show a structured MoM containing real decisions and follow-up actions.
5. Demonstrate that missing owners or deadlines were not invented.
6. Produce the final document and demonstrate the required local delivery path.
7. Report the processing time and hardware used.

## Open ideation questions

The team should treat the following as decisions to explore, not settled requirements:

- What does a professional, institution-wide MoM look like for Medpark in practice across clinical and non-clinical departments?
- Which sections make the generated document useful to meeting participants in each supported workflow without fragmenting the product?
- Should the reviewer see the complete transcript, only supporting excerpts, or both?
- How should the output represent tentative, conflicting, or later-revoked decisions?
- How should relative deadlines such as “next Friday” be represented without external meeting metadata?
- How much speaker attribution is possible when no participant list is provided?
- Which medical, financial, administrative, logistics, and technical terms, abbreviations, names, costs, measurements, and language transitions are most error-prone in the supplied recordings?
- What is the simplest human-review experience that provides trust without turning the product into a manual editing tool?
- How will we compare the generated MoM with what accountable participants from each workflow would actually write?
- What common structure serves clinical, financial, administrative, executive, operational, and crisis audio without changing the audio-only interaction?
- Which parts of the complete challenge flow must be fully functional in the demo, and which can remain intentionally minimal?

## Shared vocabulary

- **Transcript:** A time-ordered textual reconstruction of what was said.
- **MoM:** Minutes of Meeting; a compressed, structured record of relevant discussion and outcomes.
- **Decision:** An outcome that participants agreed, approved, selected, or concluded—not merely an idea that was discussed.
- **Action item:** A concrete follow-up task arising from the meeting.
- **Owner:** A person or role explicitly made responsible for an action.
- **Deadline:** A date or time constraint explicitly connected to an action.
- **Language-switching:** Changing between languages within a conversation, sentence, or phrase.
- **Hallucination:** Content presented by the system that is not supported by the recording.
- **Traceability:** The ability to connect an output statement to supporting transcript or audio evidence.
- **On-premise/offline:** Runtime processing stays inside the local environment and does not depend on an external service.

## Guidance for all workstreams

Every product, AI, design, development, testing, and pitch decision should be checked against the same questions:

1. Does it preserve the fully local, offline requirement?
2. Does it improve multilingual institution-wide terminology accuracy or the usefulness of the MoM?
3. Can we demonstrate it convincingly within the hackathon?
4. Does it reduce rather than hide uncertainty?
5. Is it necessary for the core audio-to-MoM promise, or is it distracting us from that promise?

When a decision is still uncertain, record it as an assumption or open question. Do not silently turn an ideation choice into a fixed requirement.