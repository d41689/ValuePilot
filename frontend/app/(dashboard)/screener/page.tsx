'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import apiClient from '@/lib/api/client';
import { Search, Loader2 } from 'lucide-react';

export default function ScreenerPage() {
  const [results, setResults] = useState<any[]>([]);
  
  // Hardcoded rule for V0.1 demo
  const defaultRule = JSON.stringify({
    type: "AND",
    conditions: [
        {"metric": "pe_ratio", "operator": "<", "value": 25},
        {"metric": "dividend_yield", "operator": ">", "value": 0.01}
    ]
  }, null, 2);

  const [ruleText, setRuleText] = useState(defaultRule);

  const screenMutation = useMutation({
    mutationFn: async () => {
      const rule = JSON.parse(ruleText);
      const res = await apiClient.post('/screener/run', rule);
      return res.data;
    },
    onSuccess: (data) => {
      setResults(data);
    }
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Stock Screener</h1>
      
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
        <label className="block text-sm font-medium text-gray-700 mb-2">Screening Rules (JSON)</label>
        <textarea 
          value={ruleText}
          onChange={(e) => setRuleText(e.target.value)}
          className="w-full h-48 font-mono text-sm p-4 border rounded-md bg-gray-50 focus:ring-2 focus:ring-blue-500 outline-none"
        />
        
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => screenMutation.mutate()}
            disabled={screenMutation.isPending}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {screenMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Run Screen
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="p-4 border-b bg-gray-50 font-semibold text-gray-700">Results ({results.length})</div>
        {results.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No stocks found matching criteria.
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Ticker</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company Name</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {results.map((stock) => (
                <tr key={stock.id}>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{stock.ticker}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{stock.company_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
