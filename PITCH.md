# RepoLens — The Pitch Guide

*Read this once and you can explain, demo, and defend the project to anyone —
no programming knowledge needed.*

---

## The one-liner

**RepoLens is a health scanner for software projects.** Point it at any
codebase and it tells you which files are most likely to break next, whether
a proposed change is risky, what kind of developer someone is, and how
disciplined the team's work habits are — and it explains every answer in
plain English.

---

## The problem (start your pitch here)

Software teams generate an enormous paper trail: every change ever made, who
made it, when, and why. Buried in that history are answers to questions every
team asks:

- *"Which part of our code keeps breaking?"*
- *"Is this new change dangerous? Should a senior person look at it first?"*
- *"What are this developer's actual strengths?"*
- *"Are we documenting our changes well enough to understand them next year?"*

Almost nobody mines that history. Teams answer these questions by gut feel —
the senior engineer "just knows" which files are fragile. RepoLens turns that
gut feel into measurable, explainable numbers. **The key insight: a file's
past predicts its future.** A file that was fixed five times this year and is
edited by seven different people will very likely break again — research on
software defects has confirmed this pattern for decades. RepoLens simply puts
it to work.

## What it does — four tools, four questions

**1. Bug Hotspot Predictor — "What breaks next?"**
Reads the project's entire change history, finds every past bug fix, and
ranks every file by risk. Recent trouble counts more than ancient trouble.
Output: a ranked list — *"`session.py`: 9 bug fixes (recent), 6 changes last
month, 7 different authors."* Not a black box — every score comes with its
reasons.

**2. PR Review Assistant — "Is this change risky?"**
Before a human reviews a proposed change, RepoLens checks: does it touch the
fragile files? Did they change code without updating tests? Is it too big or
scattered? Does it *resemble changes that caused bugs before*? (That last one
uses AI that compares the "shape" of code changes.) It produces a
risk-graded report — LOW / MEDIUM / HIGH — and can post it directly on
GitHub. It can also run **automatically** every time someone opens a change.

**3. Developer Skill Profiler — "Who is this developer?"**
Give it a GitHub username and it studies their public work: are they a Bug
Fixer, Feature Builder, Refactorer, Reviewer, Documentation Writer, or
Architect? Plus their languages, and how clear their work descriptions are.
Useful framing: like a scouting report built from a player's actual matches,
not their CV.

**4. Commit Message Quality Analyzer — "Are we writing good records?"**
Every change comes with a short note (a "commit message"). Bad notes — like
just *"fix"* — make projects unmaintainable. RepoLens grades every note 0–10,
shows per-person and per-month trends, and its AI can rewrite the worst notes
properly *by reading what the change actually did*.

Everything is delivered three ways: an interactive terminal app, a web
dashboard with charts and progress bars, and an API that other tools can call.

## Proof it works (real numbers to quote)

We ran it on famous open-source projects, blind:

- On **Flask** (used by millions), its #1 predicted hotspot was `app.py` —
  the core file any Flask maintainer would name.
- On **Express**, the top hotspot had 21 past bug fixes and 23 authors — the
  file's own history screamed risk.
- Commit-message grading matched intuition: Express averaged 8/10; its worst
  messages were meaningless version numbers, correctly flagged.
- **Honesty story for the demo:** our PR reviewer initially rated a
  well-tested Flask change HIGH risk. We investigated, found the tool was
  counting changelog files as "risky code," fixed it, and the same change
  correctly became LOW. The tool is *calibrated*, not just built.

## What makes it genuinely different

1. **Every answer comes with reasons.** Most AI tools say "trust me."
   RepoLens says *"this file is risky because it had 9 recent bug fixes and 7
   authors."* Explainability is the founding principle, not an afterthought.

2. **It runs on a normal laptop, free, offline.** No cloud subscription, no
   sending your company's code anywhere. The AI parts can run on a local
   model — your code never leaves the machine. (You *can* plug in ChatGPT,
   Claude, or Gemini keys if you want.)

3. **It adapts to whatever is installed.** No database? Uses files. No AI?
   Skips summaries, keeps all the analysis. Everything degrades gracefully
   instead of crashing — and it tells you what it's using.

4. **The machine learning is honest.** There's an optional trained model that
   gives a "second opinion" on risk. It's trained the *right* way (it never
   peeks at the future it's predicting) and if it doesn't have enough data,
   it says "not reliable" instead of pretending.

## Handling the obvious objections

- *"Isn't this just ChatGPT for code?"* — No. All scores and rankings come
  from transparent math over the project's history. AI only adds optional
  prose (summaries, rewrites). Unplug the AI and every ranking still works.
- *"Do we have to upload our code somewhere?"* — No. It runs entirely on
  your machine, with local AI. That's a privacy pitch, not a limitation.
- *"Predictions could be wrong."* — Every prediction ships with its
  evidence, so a human can check it in seconds. The tool advises; people
  decide.
- *"Does it scale to teams?"* — Multi-user support is built: GitHub login,
  per-user accounts with encrypted credentials, and an audit trail — off by
  default for solo use, one switch to turn on.

## Numbers for the pitch deck

- **4 analysis tools** on one shared engine
- **~5,300 lines** of engine code, **28 API endpoints**, a React dashboard
- **58 automated tests** — all runnable with zero setup, no internet needed
- Validated on **Flask, Express, and Requests** — three of the most-used
  open-source projects in the world
- Works with **MongoDB + PostgreSQL + a vector database**, yet also runs
  with none of them installed

## The 90-second demo script

1. Paste a GitHub link → watch the live progress bar ("cloning… reading
   history… scoring") → ranked hotspot list appears *with reasons*.
2. Open the dashboard: health score, contributor charts, AI-written insight
   bullets.
3. Point it at a real pull request → risk report in seconds, before any
   human has read the code.
4. Close: *"Every number you just saw came with an explanation. That's the
   product: not artificial intelligence replacing judgment — measurable
   evidence supporting it."*

*(Demo tip: use a project that's already been analyzed — everything loads
instantly from the database. Fresh analyses of big projects take minutes;
that's what the progress bar is for.)*
