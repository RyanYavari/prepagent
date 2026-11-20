import Image from "next/image";
import Link from "next/link";

export const LEGAL_CONTACT = "prepagent.app@gmail.com";
export const LEGAL_UPDATED = "November 19, 2026";

export function LegalPage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <main className="max-w-3xl mx-auto px-6 py-12 text-foreground">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-foreground/70 hover:underline"
      >
        <Image src="/logo.png" alt="" width={28} height={28} />
        PrepAgent
      </Link>
      <h1 className="text-3xl font-bold mt-4 mb-1">{title}</h1>
      <p className="text-sm text-foreground/70 mb-8">Last updated {LEGAL_UPDATED}</p>
      <div className="space-y-4 leading-relaxed [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-8 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1 [&_a]:underline">
        {children}
      </div>
      <p className="text-sm text-foreground/70 mt-12">
        <Link href="/privacy">Privacy Policy</Link> &middot;{" "}
        <Link href="/tos">Terms of Service</Link> &middot;{" "}
        <a
          href="https://github.com/RyanYavari/prepagent"
          target="_blank"
          rel="noopener noreferrer"
        >
          GitHub
        </a>
      </p>
    </main>
  );
}
