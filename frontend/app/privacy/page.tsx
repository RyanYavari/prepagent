import type { Metadata } from "next";
import { LegalPage, LEGAL_CONTACT } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy | PrepAgent",
  description: "How PrepAgent collects, uses, stores and shares your data.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy">
      <p>
        PrepAgent (&ldquo;PrepAgent&rdquo;, &ldquo;we&rdquo;) is an interview
        research tool available at https://useprepagent.app. This policy explains
        what data we collect, how we use it, who we share it with, and the
        choices you have. Contact: <a href={`mailto:${LEGAL_CONTACT}`}>{LEGAL_CONTACT}</a>.
      </p>

      <h2>1. Data we collect</h2>
      <ul>
        <li>
          <strong>Google account basics (sign-in).</strong> When you sign in
          with Google we receive your email address and name. We store your
          email address. Sign-in uses online access: we do not store any Google
          access or refresh token from sign-in.
        </li>
        <li>
          <strong>Resume.</strong> If you provide your resume, we store its text
          and numeric embeddings of its sections so briefings can reference your
          experience.
        </li>
        <li>
          <strong>Briefing inputs and outputs.</strong> The company, role and
          interviewer you enter, and the generated briefing. An optional job
          description you paste is used only to generate that briefing and is
          not stored by us.
        </li>
        <li>
          <strong>Google Calendar (optional).</strong> Only if you choose
          &ldquo;Connect Calendar&rdquo; and approve it. See section 2.
        </li>
      </ul>

      <h2>2. Google user data and Google Calendar</h2>
      <p>
        The calendar feature is a separate, optional consent that requests one
        scope: <code>calendar.events.readonly</code> (view events on your
        calendars). We use it only to find upcoming events that look like job
        interviews and offer to prepare a briefing for them.
      </p>
      <ul>
        <li>
          Event details are read on demand, analysed to extract a company, role
          and interviewer, and are not stored as raw event text. We store only
          the event ID, start time, the extracted fields with a confidence
          score, and the status of the detection.
        </li>
        <li>
          Your Google refresh token is stored encrypted and is used only to
          read your calendar events for this feature. Access tokens are never
          stored. We never create, edit or delete calendar events.
        </li>
        <li>
          Detected interviews are shown to you for confirmation before a
          briefing is created.
        </li>
        <li>
          You can disconnect at any time from the dashboard. Disconnecting
          revokes the token at Google and deletes the stored connection and
          detections. You can also revoke access at{" "}
          <a href="https://myaccount.google.com/permissions">
            myaccount.google.com/permissions
          </a>
          .
        </li>
      </ul>
      <p>
        PrepAgent&rsquo;s use and transfer of information received from Google
        APIs to any other app will adhere to the{" "}
        <a href="https://developers.google.com/terms/api-services-user-data-policy">
          Google API Services User Data Policy
        </a>
        , including the Limited Use requirements. We use Google user data only
        to provide and improve the user-facing features described here. We do
        not sell it, do not use it for advertising, do not allow humans to read
        it except with your consent, for security or abuse investigation, or to
        comply with law, and do not use it to develop or train generalized AI
        or machine-learning models.
      </p>

      <h2>3. How we use data</h2>
      <ul>
        <li>To sign you in and keep your session.</li>
        <li>To generate and display your interview briefings.</li>
        <li>To detect interviews on your calendar, if you enable that.</li>
        <li>To protect the service from abuse and enforce usage limits.</li>
      </ul>

      <h2>4. Who we share data with</h2>
      <p>
        We do not sell your data. To operate the service we send data to these
        providers, only as needed:
      </p>
      <ul>
        <li>
          <strong>Anthropic</strong>: text of your briefing inputs, resume
          excerpts and, if you enter one, job description, to generate briefings
          and to analyse calendar event text.
        </li>
        <li>
          <strong>OpenAI</strong>: resume and briefing text, to compute
          embeddings.
        </li>
        <li>
          <strong>Tavily</strong>: company and interviewer search queries.
        </li>
        <li>
          <strong>Supabase</strong>: database hosting for stored data.
        </li>
        <li>
          <strong>Amazon Web Services and Vercel</strong>: application hosting.
        </li>
        <li>
          <strong>Google</strong>: authentication and Calendar API access.
        </li>
      </ul>
      <p>
        Data from your Google account sent to Anthropic for calendar analysis
        is not used by us to train models. We may also disclose information
        where required by law.
      </p>

      <h2>5. Retention and deletion</h2>
      <p>
        We keep your data while your account is active. To delete your account
        and all associated data (resume, embeddings, briefings, calendar
        connection), email {LEGAL_CONTACT} from the address you signed in with;
        we will delete it within 30 days. Calendar data can be removed
        immediately by disconnecting in the dashboard.
      </p>

      <h2>6. Security</h2>
      <p>
        Data is transmitted over HTTPS, access is scoped to your account, and
        calendar refresh tokens are encrypted at rest. No system is perfectly
        secure, and we cannot guarantee absolute security.
      </p>

      <h2>7. Children</h2>
      <p>PrepAgent is not directed to anyone under 16 and we do not knowingly collect their data.</p>

      <h2>8. Changes</h2>
      <p>
        We may update this policy. The date above shows the latest revision;
        material changes will be noted on this page.
      </p>

      <h2>9. Contact</h2>
      <p>
        Questions or requests: <a href={`mailto:${LEGAL_CONTACT}`}>{LEGAL_CONTACT}</a>.
      </p>
    </LegalPage>
  );
}
