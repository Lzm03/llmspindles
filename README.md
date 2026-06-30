# Agent-Assisted Spindle-Supported Sleep Onset

Web platform that extends conservative spindle candidate detection and agent verification into a deterministic sleep-onset estimate.

## Operational sleep-onset definition

Accepted spindle events are assigned to fixed, non-overlapping 30-second epochs using their start time. An epoch containing at least one accepted spindle is labelled `N2_like`; all other epochs are labelled `not_N2_like`. Sleep onset is the start of the first epoch in the first consecutive `N2_like` pair:

```text
Epoch i contains >= 1 accepted spindle
Epoch i+1 contains >= 1 accepted spindle
Sleep onset estimate = start(Epoch i)
```

This is a project-specific spindle-supported N2-like definition, not full clinical sleep staging. GPT verifies spindle candidates only; the epoch aggregation and sleep-onset decision are deterministic.

## Stack

- Frontend: React, TypeScript, Vite, Plotly.js
- Backend: FastAPI, scipy, numpy, matplotlib
- Storage: local JSON annotations in `backend/data/annotations.json`
- LLM: OpenAI API from the backend only

## Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env`:

```bash
OPENAI_API_KEY=your_key_here
OPENAI_VISION_MODEL=gpt-4o-mini
OPENAI_PROMPT_ID=pmpt_6a1fadf598e881949b173ba09638499305643a274f2502a2
OPENAI_PROMPT_VERSION=1
DATA_DIR=./data
MAX_RENDER_SECONDS=120
```

Run the API:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Usage

1. Upload a `.mat` or `.edf` file.
2. Confirm detected metadata and array candidates.
3. Pick filter mode: `raw`, `broad`, or `sigma`.
4. Enter channel ranges such as `1-12` or explicit channels such as `1,2,34`.
5. Run spindle evidence automation over the selected recording range.
6. Accept only definite spindle proposals; reject uncertain candidates.
7. Refresh the onset report. The UI highlights N2-like epochs, the first supporting pair, and the accepted spindle events used.
8. Export spindle GT or request the structured JSON report.

## Spindle Evidence Automation

- Open `Spindle evidence automation` to scan a selected range for spindle-like candidates.
- YASA 0.6.5 generates candidate hints; hints in the same fixed 30-second epoch are reviewed together.
- GPT reviews the complete broad-band target epoch with up to 5 seconds of shaded boundary context on each side. Context events cannot be annotated.
- Prompt, model, reasoning effort, verbosity, and the strict JSON schema are configurable per batch.
- Every reviewed epoch stores YASA hints separately from GPT-accepted events, evidence/exclusion checklists, uncertainty notes, image quality, and its deterministic `N2_like`/`not_N2_like` label.
- The first pair of consecutive `N2_like` reviewed epochs deterministically defines the spindle-supported sleep-onset estimate; GPT never chooses onset directly.
- Spindle evidence does not automatically assign an epoch's sleep stage.
- A single job supports up to 500 candidate windows and can be resumed after refresh.

## Export

Use `Export spindle GT` in the top bar to download a CSV containing:

- fixed epoch index and time boundaries
- `spindle_present` as the manual epoch-level label
- the derived proxy timestamp when the first two consecutive epochs both contain a definite spindle

This is a spindle-based sleep-onset proxy, not the paper's N2-based sleep-onset ground truth.
After the first consecutive spindle-positive pair is confirmed, any missing earlier epochs are automatically stored and exported as `spindle_present=false`; existing labels are never overwritten. This assumes review proceeded chronologically from the recording start.

## Sleep-onset JSON report

`GET /api/spindle-sleep-onset/{file_id}` returns:

- detected status and sleep-onset epoch/time
- the two supporting epochs
- all 30-second N2-like/not-N2-like epoch summaries
- accepted spindle counts per epoch
- the accepted spindle events supporting the decision
- a method note that states the operational definition

Only annotations with `status="accepted"` are consumed. Proposed, rejected, and uncertain candidates cannot trigger sleep onset.

## Supported Inputs

The app supports:

- MATLAB `.mat`
- EDF `.edf`

For EDF:

- channel labels are read from the EDF header
- sampling rate is read from the EDF header
- when multiple sampling rates exist, the app uses the largest group of channels sharing one sampling rate

## Supported `.mat` Shape

Initial support expects:

- EEG data as a numeric 2D array, `channels x samples`
- Sampling rate as a scalar key, often named like `EEGSamplingRate`

If multiple numeric arrays exist, the upload response lists candidates. The backend currently selects the largest plausible 2D EEG candidate.

## API

- `POST /api/upload`
- `GET /api/eeg/window`
- `POST /api/render-segment`
- `POST /api/analyze-segment`
- `GET /api/annotations`
- `POST /api/annotations`
- `DELETE /api/annotations/{annotation_id}`

## Notes

- The frontend never receives the OpenAI API key.
- Uploaded `.mat` files are stored under `backend/data/uploads`.
- Plot windows are filtered and downsampled on the backend for smoother browser rendering.
- Segment rendering uses matplotlib in a stacked EEG style.
- LLM results are saved as `source="llm"` and `status="proposed"` until reviewed by a human.
