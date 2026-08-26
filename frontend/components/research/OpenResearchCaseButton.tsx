'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, LoaderCircle } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { showAppToast } from '@/lib/appToast';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';

type OriginType =
  | 'manual'
  | 'ticker_search'
  | 'watchlist'
  | 'screener'
  | 'oracle_lens'
  | 'manager_holding'
  | 'manager_change';

export function OpenResearchCaseButton({
  stockId,
  originType,
  originKey,
  sourceVersion,
  sourceRef,
  label = 'Research',
  className,
}: {
  stockId: number;
  originType: OriginType;
  originKey: string;
  sourceVersion: string;
  sourceRef?: Record<string, unknown>;
  label?: string;
  className?: string;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [pending, setPending] = useState(false);

  async function openCase() {
    setPending(true);
    try {
      const response = await apiClient.post('/research/cases', {
        stock_id: stockId,
        origin: {
          origin_type: originType,
          origin_key: originKey,
          source_version: sourceVersion,
          source_ref: sourceRef ?? null,
        },
      });
      const caseId = response.data?.case?.id;
      if (typeof caseId !== 'number') {
        throw new Error('Research case response did not include an ID.');
      }
      showAppToast(toast, {
        type: 'success',
        title: response.data.created ? 'Research case created' : 'Existing case opened',
        description: response.data.origin_created
          ? 'The discovery context was preserved in the case history.'
          : 'This source context was already recorded.',
      });
      router.push(`/research/cases/${caseId}`);
    } catch {
      showAppToast(toast, {
        type: 'error',
        title: 'Unable to open research case',
        description: 'The case was not changed. Retry when the service is available.',
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      disabled={pending}
      onClick={() => void openCase()}
    >
      {pending ? (
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {pending ? 'Opening…' : label}
    </Button>
  );
}
