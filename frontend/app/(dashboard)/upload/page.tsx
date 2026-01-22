import UploadZone from "@/features/upload/components/UploadZone";

export default function UploadPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Upload</h1>
      <p className="text-gray-600">Welcome to ValuePilot. Start by uploading a Value Line PDF report.</p>

      <UploadZone />

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-2 text-gray-900">Recent Activity</h2>
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          No recent documents found.
        </div>
      </div>
    </div>
  );
}
