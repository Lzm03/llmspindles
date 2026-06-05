# EEG Spindle Annotation MVP

Web platform for uploading EEG `.mat` or `.edf` files, visualizing stacked clinical-style EEG windows, rendering selected segments, and asking a backend-only OpenAI vision call for conservative sleep spindle proposals.

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
5. Load a time window for interactive browsing.
6. Select segment start/end seconds, for example `1654` to `1664`.
7. Render a broad or sigma PNG.
8. Click `Analyze with LLM`.
9. Review proposed annotations. Accept, reject, or delete them.

## Batch Analysis

- Choose a start time, end time, and seconds per segment in `Batch analysis`.
- The UI calculates the number of segments before submission.
- A single job supports up to 500 segments.
- Jobs run in the backend and expose live percentage, completed count, annotations created, failures, and estimated remaining time.
- Refreshing the browser does not restart an active job. The workspace and active job are restored automatically.

## Export

Use `Export` in the top bar to download a versioned JSON file containing:

- `schema_version`
- recording metadata
- all annotations and review statuses
- analysis job history and progress metadata

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
