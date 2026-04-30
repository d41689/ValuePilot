'use client';

import { useState, useRef } from 'react';
import { Upload, File, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import apiClient from '@/lib/api/client';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function UploadZone() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiClient.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      uploadMutation.reset();
    }
  };

  const handleUpload = () => {
    if (selectedFile) {
      uploadMutation.mutate(selectedFile);
    }
  };

  return (
    <div className="max-w-xl mx-auto mt-10 p-6 bg-white rounded-lg shadow-sm border border-gray-200">
      <h2 className="text-lg font-semibold mb-4 text-gray-900">Upload Report</h2>
      
      <div 
        className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:bg-gray-50 transition-colors cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
      >
        <Input
          type="file" 
          ref={fileInputRef} 
          className="hidden" 
          accept=".pdf"
          onChange={handleFileChange}
        />
        <div className="flex flex-col items-center">
          <Upload className="h-10 w-10 text-gray-400 mb-2" />
          <p className="text-sm text-gray-600 font-medium">
            {selectedFile ? selectedFile.name : "Click to select PDF"}
          </p>
          <p className="text-xs text-gray-400 mt-1">Value Line Equity Reports (PDF)</p>
        </div>
      </div>

      {selectedFile && (
        <div className="mt-4 flex justify-end">
          <Button
            onClick={handleUpload}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {uploadMutation.isPending ? 'Uploading...' : 'Process Document'}
          </Button>
        </div>
      )}

      {uploadMutation.isSuccess && (
        <div className="mt-4 p-3 bg-green-50 text-green-700 rounded-md flex items-center gap-2 text-sm">
          <CheckCircle className="h-4 w-4" />
          <span>Upload successful! Document ID: {uploadMutation.data.id}</span>
        </div>
      )}

      {uploadMutation.isError && (
        <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-md flex items-center gap-2 text-sm">
          <AlertCircle className="h-4 w-4" />
          <span>Upload failed: {uploadMutation.error.message}</span>
        </div>
      )}
    </div>
  );
}
