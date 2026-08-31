# Controlled Inference Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, process-local rate and inference admission controls for the one-worker Slice 5B deployment contract.

**Architecture:** App-scoped `threading.Lock` controllers provide isolated bounded fixed-window quotas and non-blocking inference leases. Route helpers read controllers from `Request.app.state` after the existing security/authorization dependencies complete.

**Tech Stack:** FastAPI, Starlette `Request`, Pydantic Settings, Uvicorn, pytest, threading, monotonic time.

**Spec:** `docs/superpowers/specs/2026-08-30-controlled-inference-admission-design.md`

## Global Constraints

- One app process and one app instance only; shared coordination is required before scaling.
- Do not add Redis, queues, migrations, billing, frontend changes, auth redesign, deployment, commit, push, or PR.
- Locks never span database, provider, validation, HTTP, or other slow work.
- Preserve model, prompt, schema, retry semantics, Slice 5A perimeter behavior, and authorization-before-version behavior.

### Task 1: Rate-control primitives and settings

**Files:** create `backend/app/security/admission.py`; modify `backend/app/core/config.py`; test `tests/backend/test_controlled_inference_admission.py`.

- [x] Implement bounded fixed-window primitives and settings with a short `threading.Lock` critical section.
- [x] Verify fixed-window boundaries, expiry, Retry-After, and bounded-state behavior.

### Task 2: Inference admission primitive

**Files:** modify `backend/app/security/admission.py`; test `tests/backend/test_controlled_inference_admission.py`.

- [x] Implement `InferenceAdmissionController` and exception-safe lease counters.
- [x] Verify workspace/global capacity and release behavior with focused deterministic tests.

### Task 3: App state and route integration

**Files:** modify `backend/app/main.py`, `backend/app/api/routes/auth.py`, `backend/app/api/routes/clients.py`, `backend/app/api/routes/analyses.py`, `backend/app/api/routes/actions.py`; test focused API cases.

- [x] Initialize isolated app-scoped controllers and integrate auth/workspace routes.
- [x] Add controller/app-factory adversarial coverage for source fallback, pool isolation, and runner environment overrides.
- [x] Add remaining API route-classification, exhausted-attacker BOLA-before-rate, provider-zero, and deterministic held-provider HTTP concurrency coverage.
- [x] Separate all six policy limiter pools so one policy's key capacity cannot starve another.

### Task 4: Groq ceiling and production runner

**Files:** modify `backend/app/services/groq_intelligence_service.py`, `backend/app/core/config.py`, `.env.example`, `backend/app/run_production.py`, `README.md`; test `tests/backend/test_groq_intelligence.py` and focused runner/config tests.

- [x] Add the completion setting and explicit one-worker runner.
- [x] Add proxy-validation and ambient-environment runner coverage.

### Task 5: Verification and audit

**Files:** tests and documentation only as required above.

- [x] Run prior focused/regression/backend/frontend verification and one live ceiling smoke.
- [x] Re-run final verification after the correction.
- [x] Stop before commit for human diff review.
