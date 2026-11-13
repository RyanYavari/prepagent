# Spec: Dashboard Polish

## Problem
The dashboard currently displays a static "No briefings yet" message and does not fetch or display the user's actual briefing history. The "New Briefing" button routes to `/prep/new`, which does not exist. The backend GET /briefings endpoint exists and works, but the frontend doesn't call it.

## Goal
Users can see their briefing history on the dashboard and can click "New Briefing" to navigate to a working form that creates briefings via POST /briefings.

## Non-goals
- Displaying full briefing content (that's a separate briefing viewer page for Week 2)
- Pagination controls (the endpoint supports limit/offset, but we'll hardcode limit=20 for now)
- Filtering or search
- Real-time status updates (polling for status changes)
- Deleting or editing existing briefings
- LangGraph pipeline execution (that's Week 2+)

## Acceptance Criteria

### Given a user is authenticated and has no briefings
### When they visit /dashboard
### Then they see "No briefings yet. Start your first interview prep to see results here." with a "New Briefing" button

---

### Given a user is authenticated and has briefings in the database
### When they visit /dashboard
### Then they see a list of their briefings sorted by created_at descending, showing company, role, interviewer (if present), status, and created_at for each

---

### Given a user is viewing the dashboard
### When they click "New Briefing"
### Then they are navigated to /prep/new

---

### Given a user is on /prep/new
### When the page loads
### Then they see a form with fields: company (required), interviewer (optional), role (optional), interview_date (optional), resume_text (optional textarea)

---

### Given a user fills out the /prep/new form with at least a company name
### When they submit the form
### Then a POST /briefings request is sent with Authorization: Bearer {token}, the briefing is created, and the user is redirected to /dashboard with the new briefing visible

---

### Given a user submits the /prep/new form
### When the API returns an error (401, 500, 503)
### Then the error message is displayed on the form without navigating away, and the form fields retain their values

---

### Given a user visits /dashboard or /prep/new without a valid token in localStorage
### When the page loads
### Then they are redirected to / (the sign-in page)

---

### Given a briefing has status "pending"
### When it is displayed on the dashboard
### Then it shows a visual indicator (e.g., gray badge with "Pending")

---

### Given a briefing has status "complete"
### When it is displayed on the dashboard
### Then it shows a visual indicator (e.g., green badge with "Complete")

---

### Given a briefing has status "failed"
### When it is displayed on the dashboard
### Then it shows a visual indicator (e.g., red badge with "Failed")

## Affected Files

### New files
- `frontend/app/prep/new/page.tsx` - New briefing form

### Modified files
- `frontend/app/dashboard/page.tsx` - Fetch and display briefing history

## Dependencies
- Backend GET /briefings endpoint (already exists at backend/routers/research.py:99-133)
- Backend POST /briefings endpoint (already exists at backend/routers/research.py:28-96)
- JWT token stored in localStorage (already handled by auth flow)
- API_URL environment variable (already set in callback page, reuse pattern)

## Open Questions
- **Should we display the full resume_text field in the form, or just a file upload?**
  - Decision: Start with textarea. File upload can be added later if needed.

- **Should clicking a briefing in the list navigate somewhere?**
  - Decision: No for this slice. Briefing viewer is Week 2. The list is read-only for now.

- **What date format should interview_date use?**
  - Decision: Use HTML5 date input (YYYY-MM-DD), matches the backend's "2025-06-15" example.

- **Should we show a loading spinner while fetching briefings?**
  - Decision: Yes. Show "Loading briefings..." state before the API response.
