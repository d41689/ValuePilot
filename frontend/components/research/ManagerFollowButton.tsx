'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, BellOff, LoaderCircle } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Button } from '@/components/ui/button';

type ManagerFollow = { id: number; manager_id: number };

export function ManagerFollowButton({ managerId }: { managerId: number }) {
  const queryClient = useQueryClient();
  const followsQuery = useQuery({
    queryKey: ['manager-follows'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/manager-follows');
      return (response.data?.items ?? []) as ManagerFollow[];
    },
  });
  const follow = followsQuery.data?.find((item) => item.manager_id === managerId);
  const mutation = useMutation({
    mutationFn: () =>
      follow
        ? apiClient.delete(`/notifications/manager-follows/${follow.id}`)
        : apiClient.post(`/notifications/manager-follows/${managerId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['manager-follows'] });
    },
  });

  return (
    <Button
      type="button"
      variant={follow ? 'default' : 'outline'}
      disabled={followsQuery.isLoading || mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      {mutation.isPending ? (
        <LoaderCircle className="h-4 w-4 animate-spin" />
      ) : follow ? (
        <Bell className="h-4 w-4" />
      ) : (
        <BellOff className="h-4 w-4" />
      )}
      {follow ? 'Following' : 'Follow manager'}
    </Button>
  );
}
