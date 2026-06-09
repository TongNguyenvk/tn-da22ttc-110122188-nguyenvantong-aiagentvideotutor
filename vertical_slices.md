# Vertical Slices: Dynamic LLM Configuration Management

This document breaks down the implementation into independent, testable vertical slices. Each slice covers the database schema, backend API, worker integration, or UI representation.

---

## 🍕 Slice 1: Database Schema, API Key Security & Admin CRUD APIs

### Goal

Establish the backend storage for LLM configurations with secure key encryption and basic CRUD endpoints.

### Tasks

1. **Database Schema:**
   - Define a MongoDB model for `ai_providers` inside `backend/models` or CRUD directories.
   - Add a database index on the `is_active` field.
2. **Encryption Utility:**
   - Create a simple symmetric encryption utility (e.g., using `cryptography.fernet` or a helper using standard python hashes) to encrypt `api_key` before writing to MongoDB and decrypt it when read.
3. **FastAPI Routes:**
   - In `backend/routes/admin.py`, register:
     - `GET /api/admin/ai-settings/providers` (returns all providers with masked API keys like `sk-...xxxx`).
     - `POST /api/admin/ai-settings/providers` (saves a new provider, encrypts key).
     - `PUT /api/admin/ai-settings/providers/{id}` (updates provider, re-encrypts key if changed).
     - `DELETE /api/admin/ai-settings/providers/{id}` (removes provider).
     - `POST /api/admin/ai-settings/providers/{id}/activate` (sets provider active, deactivates others).
4. **Unit/Integration Tests:**
   - Create a test file `backend/test_ai_settings.py` checking that key encryption works and CRUD operations persist data correctly.

---

## 🍕 Slice 2: Connection Testing & Vision Capability Verification

### Goal

Implement validation tools to ensure that admin-configured LLM providers and models function properly and support vision.

### Tasks

1. **Test Endpoint:**
   - Implement `POST /api/admin/ai-settings/test-connection` in `backend/routes/admin.py`.
2. **Connection Testing Logic:**
   - Initialize the langchain LLM using the provided parameters.
   - Query a simple text message (`"Hello"`) to verify the endpoint is valid and authentication is successful.
3. **Vision Testing Logic:**
   - Send a small 1x1 base64 transparent PNG image along with the prompt `"What is the color of this image?"`.
   - If the model accepts the image payload and responds, mark `vision_supported: true`. Otherwise, mark it `false`.
4. **Verification:**
   - Test using local standard Gemini env variables to verify both text and vision detection outputs are correct.

---

## 🍕 Slice 3: Worker & Pipeline Integration (Job Payload, Dynamic LLM, Fallback)

### Goal

Connect the dynamic configurations with the queue payload and worker executions, with a reliable env-based fallback.

### Tasks

1. **Schema Update:**
   - Update `JobConfig` in `backend/job_models.py` to support `llm_config` (which holds `provider_type`, `base_url`, `api_key`, `model`).
2. **Job Packaging (FastAPI):**
   - Update `submit_job` in `backend/main.py` to retrieve the active provider from MongoDB, decrypt the API Key, and inject it into the `JobConfig` before pushing the job to Redis.
3. **Worker Pipeline Update:**
   - Update `desktop_app/pipeline.py` (specifically `run_pipeline_v3`) to check for the presence of `llm_config` arguments.
   - Initialize `ChatGoogle` or `ChatOpenAI` accordingly based on `llm_config`.
4. **Fallback Mechanism:**
   - Wrap the dynamic LLM connection/scout loop in a try-except block.
   - On connection failure or invalid model errors, log a critical warning and automatically instantiate the default LLM using system environment variables (`GEMINI_API_KEY`, `GEMINI_MODEL`).
5. **Testing:**
   - Submit a test job with incorrect settings and verify it gracefully falls back and succeeds.

---

## 🍕 Slice 4: Admin Settings Page (React UI)

### Goal

Create a beautiful, responsive user interface within the Admin Dashboard to manage settings.

### Tasks

1. **Admin Page Layout & Navigation:**
   - Register the route `/admin/settings` in `frontend/src/App.tsx`.
   - Add the **"Cấu hình AI"** nav item to the admin Sidebar component.
2. **Settings UI Components:**
   - Create `frontend/src/pages/AdminSettings.tsx`.
   - Table showing active/inactive providers, provider type, model names, and action buttons.
   - Modal for "Add New Provider" and "Edit Provider".
3. **Interactive Features:**
   - Form inputs with selection between Gemini / OpenAI Compatible, endpoint URL, model name tags, and API Key (with reveal/hide toggles).
   - "Test Connection" button calling Slice 2 API, showing success status and whether Vision is supported.
   - Quick toggles to activate/deactivate a provider.
