# Client Intelligence OS

Client Intelligence OS analyzes client–coach conversations into evidence-backed, structured findings, risks, recommended actions, and missing information. Its outputs are designed for human review before they are approved or used in operational workflows.

## Current capabilities

- FastAPI backend with a deterministic analysis baseline
- Provider-isolated LLM architecture
- Evidence verification and exact source references
- React and TypeScript frontend
- Responsive intelligence and review workspace
- Typed integration with the analysis API

## Current status

The project is under active development and is not production-ready. Screens without supporting backend endpoints currently use isolated mock data so that demonstration content remains separate from the analysis API.

## Local setup

### Backend

From the repository root, install backend dependencies into the existing project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Start the FastAPI development server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Run the backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\backend -v
```

### Frontend

From the `frontend` directory, install dependencies and start Vite:

```powershell
npm install
npm run dev
```

Run the frontend quality checks:

```powershell
npm run lint
npm exec -- tsc -p tsconfig.app.json --noEmit
npm test
npm run build
```

## Security

Create local configuration by copying the example file:

```powershell
Copy-Item .env.example .env
```

Never commit `.env`. Do not enable live provider calls without intentional provider and billing configuration.

## Repository structure

```text
backend/       FastAPI application, schemas, and analysis services
frontend/      React and TypeScript application
tests/         Backend test suite
prototype-v0/  Earlier application prototype
```
