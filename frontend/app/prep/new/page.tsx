"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function NewBriefing() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState({
    company: "",
    interviewer: "",
    role: "",
    interview_date: "",
    resume_text: "",
  });

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!formData.company.trim()) {
      setError("Company name is required");
      return;
    }

    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }

    setLoading(true);

    try {
      const payload: {
        company: string;
        interviewer?: string;
        role?: string;
        interview_date?: string;
        resume_text?: string;
      } = {
        company: formData.company.trim(),
      };

      if (formData.interviewer.trim()) {
        payload.interviewer = formData.interviewer.trim();
      }
      if (formData.role.trim()) {
        payload.role = formData.role.trim();
      }
      if (formData.interview_date) {
        payload.interview_date = formData.interview_date;
      }
      if (formData.resume_text.trim()) {
        payload.resume_text = formData.resume_text.trim();
      }

      const res = await fetch(`${API_URL}/briefings`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });

      if (res.status === 401) {
        localStorage.removeItem("token");
        localStorage.removeItem("email");
        router.push("/");
        return;
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to create briefing");
      }

      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create briefing");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">New Briefing</h1>
          <p className="text-gray-600">
            Enter interview details to generate a personalized briefing
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label
              htmlFor="company"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Company <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              id="company"
              name="company"
              value={formData.company}
              onChange={handleChange}
              maxLength={200}
              required
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="e.g., Stripe"
            />
          </div>

          <div>
            <label
              htmlFor="role"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Role
            </label>
            <input
              type="text"
              id="role"
              name="role"
              value={formData.role}
              onChange={handleChange}
              maxLength={200}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="e.g., Senior Backend Engineer"
            />
          </div>

          <div>
            <label
              htmlFor="interviewer"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Interviewer
            </label>
            <input
              type="text"
              id="interviewer"
              name="interviewer"
              value={formData.interviewer}
              onChange={handleChange}
              maxLength={200}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="e.g., Jane Smith"
            />
          </div>

          <div>
            <label
              htmlFor="interview_date"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Interview Date
            </label>
            <input
              type="date"
              id="interview_date"
              name="interview_date"
              value={formData.interview_date}
              onChange={handleChange}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label
              htmlFor="resume_text"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Resume (Optional)
            </label>
            <textarea
              id="resume_text"
              name="resume_text"
              value={formData.resume_text}
              onChange={handleChange}
              maxLength={50000}
              rows={10}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent font-mono text-sm"
              placeholder="Paste your resume text here..."
            />
            <p className="text-xs text-gray-500 mt-1">
              Optional. If provided, will be used to personalize your briefing.
            </p>
          </div>

          {error && (
            <div className="border border-red-200 bg-red-50 rounded-lg p-4">
              <p className="text-red-600 text-sm">{error}</p>
            </div>
          )}

          <div className="flex gap-4">
            <button
              type="submit"
              disabled={loading}
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {loading ? "Creating..." : "Create Briefing"}
            </button>
            <button
              type="button"
              onClick={() => router.push("/dashboard")}
              disabled={loading}
              className="px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:bg-gray-100 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}
