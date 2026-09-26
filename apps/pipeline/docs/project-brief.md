# Project brief

Status: accepted pipeline context for the hackathon MVP  
Last updated: 26 September 2026

## Problem

Meetings across the medical institution—including clinical, financial,
administrative, executive, operational, and urgent-crisis meetings—contain
decisions, follow-up actions, owners, deadlines, and domain-specific detail.
Producing useful minutes manually is slow, while general-purpose meeting
assistants cannot satisfy the requirement that confidential meeting content
remain inside the hospital environment.

Secure MOM must turn a recorded multilingual institution meeting into concise,
structured Minutes of Meeting while running entirely on local hardware.

## Pipeline objective

Provide the smallest reliable orchestration layer that connects the user-facing
application to independently developed audio-processing and text-processing ML
components.

The pipeline must:

1. accept one audio recording and safely persist it;
2. return a job identifier without waiting for inference;
3. invoke the local audio-processing service asynchronously;
4. accept and persist its structured transcription JSON, then extract the
   complete transcript text as a UTF-8 plain-text file;
5. upload that file to the local text-processing service asynchronously;
6. persist its review-ready draft MoM and compact review context as JSON; and
7. expose job status, review context, transcript, and MoM through separate local
   HTTP reads.

## Product principles relevant to the pipeline

- The recording is the source of meeting truth.
- Missing owners, deadlines, identities, or conclusions must not be invented.
- The transcript is an intermediate artifact; a useful draft MoM is the goal.
- Clinical, financial, administrative, operational, and technical meaning—as
  well as uncertainty, negation, costs, dates, measurements, and units—must
  survive the transformation.
- All meeting content and processing stay on the local machine at runtime.
- The MVP should favor clarity and reproducibility over infrastructure breadth.

## Operating context

- 48-hour hackathon prototype
- clinical, financial, administrative, executive, operational, and
  urgent-crisis meetings are supported by the same audio-to-MoM workflow
- recordings may be made in clinical rooms, departmental cabinets or offices
  with desks, boardrooms, or other hospital workspaces; location is not input
- Romanian, Russian, and English may be mixed in one recording
- presentation target is a team MacBook
- the application must be prepared before the demo and run without internet
- approximately 10-20 stored jobs are expected
- the two ML services are owned and operated independently from this pipeline

## Success for this workstream

The frontend can submit a recording, receive a job ID, show meaningful progress,
and retrieve a valid draft MoM JSON after both local ML stages finish. Restarting
the API or worker does not lose already persisted job state or valid artifacts.
