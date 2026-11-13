# Tasks: Dashboard Polish

Spec: `specs/dashboard-polish.md`

## Slice plan

Break the spec into the smallest shippable slices. Each slice should be independently testable.

### Slice 1: Wire up dashboard to fetch and display briefing history
- [ ] Add API call to GET /briefings in dashboard useEffect
- [ ] Display loading state while fetching
- [ ] Display empty state when briefings array is empty
- [ ] Display briefing list when briefings exist (company, role, interviewer, status badge, created_at)
- [ ] Add status badge component with color coding (pending=gray, complete=green, failed=red)
- [ ] Handle API errors (401 redirects to /, other errors show error message)
- [ ] Manual test: Create a briefing via backend, verify it appears on dashboard
- [ ] Manual test: Sign out and back in, verify briefings still load

### Slice 2: Implement /prep/new form page
- [ ] Create frontend/app/prep/new/page.tsx with auth guard
- [ ] Add form with fields: company (required), interviewer, role, interview_date (HTML5 date), resume_text (textarea)
- [ ] Add form validation (company required, max lengths match backend schema)
- [ ] Handle form submission: POST /briefings with Authorization header
- [ ] On success: redirect to /dashboard
- [ ] On error: display error message without navigating away, retain form values
- [ ] Add loading state during submission
- [ ] Manual test: Submit form with only company, verify briefing created
- [ ] Manual test: Submit with all fields, verify all fields saved
- [ ] Manual test: Submit without token, verify 401 handling
- [ ] Manual test: Test backend 503 error (temporarily break OpenAI key), verify error message

## Done checklist
- [ ] All acceptance criteria from spec are met
- [ ] `npm run lint` passes
- [ ] `npm run build` succeeds
- [ ] Manual testing complete for both slices
- [ ] /commit with conventional commit message
