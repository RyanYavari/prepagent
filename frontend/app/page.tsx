import Image from "next/image";

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-4">PrepAgent</h1>
        <p className="text-gray-600 mb-8">
          AI-powered interview research. 90 seconds. Every time.
        </p>
        <button className="bg-black text-white px-6 py-3 rounded-lg">
          Sign in with Google
        </button>
      </div>
    </main>
  )
}
