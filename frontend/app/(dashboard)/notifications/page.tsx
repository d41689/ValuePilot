'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  Bell,
  CheckCircle2,
  ExternalLink,
  LoaderCircle,
  Mail,
  MessageSquare,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type NotificationItem = {
  id: number;
  event_family: string;
  correction_type: string;
  title: string;
  body: string;
  evidence_route: string;
  severity: 'info' | 'warning' | 'error';
  read_at: string | null;
  created_at: string;
};

type Destination = {
  id: number;
  channel: 'slack' | 'email';
  label: string;
  destination_hint: string;
  status: string;
  verified_at: string | null;
  last_error_class: string | null;
};

type Subscription = {
  id: number;
  event_family: string;
  destination_id: number | null;
  frequency: string;
  timezone: string;
  quiet_start_local: string | null;
  quiet_end_local: string | null;
  cooldown_minutes: number;
  threshold_ratio: string | null;
  hysteresis_ratio: string;
  is_enabled: boolean;
};

type DeliveryAttempt = {
  id: number;
  notification_title: string;
  evidence_route: string;
  event_family: string;
  destination_label: string;
  destination_hint: string;
  channel: string;
  status: string;
  attempt_count: number;
  provider_response_class: string | null;
  last_attempt_at: string | null;
  succeeded_at: string | null;
  created_at: string;
};

const eventFamilies = [
  'followed_manager_filed',
  'followed_manager_position_changed',
  'intrinsic_value_threshold_crossed',
  'research_review_due',
  'research_coverage_changed',
  'filing_season_digest',
];

function label(value: string) {
  return value.replaceAll('_', ' ');
}

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const [slackLabel, setSlackLabel] = useState('Research Slack');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [slackConsent, setSlackConsent] = useState(false);
  const [emailLabel, setEmailLabel] = useState('Research email');
  const [email, setEmail] = useState('');
  const [emailConsent, setEmailConsent] = useState(false);
  const [verificationDestinationId, setVerificationDestinationId] = useState('');
  const [verificationToken, setVerificationToken] = useState('');
  const [testConsent, setTestConsent] = useState<Record<number, boolean>>({});
  const [eventFamily, setEventFamily] = useState('research_review_due');
  const [destinationChoice, setDestinationChoice] = useState('in_app');
  const [frequency, setFrequency] = useState('immediate');
  const [timezoneName, setTimezoneName] = useState('America/Chicago');
  const [quietStart, setQuietStart] = useState('22:00');
  const [quietEnd, setQuietEnd] = useState('07:00');
  const [cooldown, setCooldown] = useState('60');
  const [thresholdRatio, setThresholdRatio] = useState('0.20');
  const [hysteresisRatio, setHysteresisRatio] = useState('0.02');

  const inboxQuery = useQuery({
    queryKey: ['notification-inbox'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/inbox');
      return (response.data?.items ?? []) as NotificationItem[];
    },
  });
  const destinationsQuery = useQuery({
    queryKey: ['notification-destinations'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/destinations');
      return (response.data?.items ?? []) as Destination[];
    },
  });
  const subscriptionsQuery = useQuery({
    queryKey: ['notification-subscriptions'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/subscriptions');
      return (response.data?.items ?? []) as Subscription[];
    },
  });
  const deliveryQuery = useQuery({
    queryKey: ['notification-delivery-attempts'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/delivery-attempts?limit=25');
      return (response.data?.items ?? []) as DeliveryAttempt[];
    },
  });

  useEffect(() => {
    const selectedDestinationId = destinationChoice === 'in_app'
      ? null
      : Number(destinationChoice);
    const matchingSubscription = subscriptionsQuery.data?.find((item) => (
      item.event_family === eventFamily
      && item.destination_id === selectedDestinationId
    ));
    if (!matchingSubscription) return;
    setFrequency(matchingSubscription.frequency);
    setTimezoneName(matchingSubscription.timezone);
    setQuietStart(matchingSubscription.quiet_start_local ?? '');
    setQuietEnd(matchingSubscription.quiet_end_local ?? '');
    setCooldown(String(matchingSubscription.cooldown_minutes));
    if (matchingSubscription.threshold_ratio !== null) {
      setThresholdRatio(matchingSubscription.threshold_ratio);
    }
    setHysteresisRatio(matchingSubscription.hysteresis_ratio);
  }, [destinationChoice, eventFamily, subscriptionsQuery.data]);

  const stateMutation = useMutation({
    mutationFn: ({ id, operation }: { id: number; operation: 'read' | 'dismiss' }) =>
      apiClient.post(`/notifications/inbox/${id}/${operation}`),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['notification-inbox'] }),
  });
  const slackMutation = useMutation({
    mutationFn: () => apiClient.post('/notifications/destinations/slack', {
      label: slackLabel,
      webhook_url: webhookUrl,
      consent: slackConsent,
    }),
    onSuccess: async () => {
      setWebhookUrl('');
      setSlackConsent(false);
      await queryClient.invalidateQueries({ queryKey: ['notification-destinations'] });
    },
  });
  const emailMutation = useMutation({
    mutationFn: () => apiClient.post('/notifications/destinations/email', {
      label: emailLabel,
      email,
      consent: emailConsent,
    }),
    onSuccess: async (response) => {
      setVerificationDestinationId(String(response.data?.destination?.id ?? ''));
      setEmail('');
      setEmailConsent(false);
      await queryClient.invalidateQueries({ queryKey: ['notification-destinations'] });
    },
  });
  const verifyMutation = useMutation({
    mutationFn: () => apiClient.post(
      `/notifications/destinations/${verificationDestinationId}/verify-email`,
      { token: verificationToken },
    ),
    onSuccess: async () => {
      setVerificationToken('');
      await queryClient.invalidateQueries({ queryKey: ['notification-destinations'] });
    },
  });
  const testMutation = useMutation({
    mutationFn: (destinationId: number) =>
      apiClient.post(`/notifications/destinations/${destinationId}/test`, { confirm_send: true }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['notification-delivery-attempts'] }),
  });
  const revokeMutation = useMutation({
    mutationFn: (destinationId: number) => apiClient.delete(`/notifications/destinations/${destinationId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notification-destinations'] });
      await queryClient.invalidateQueries({ queryKey: ['notification-subscriptions'] });
    },
  });
  const subscriptionMutation = useMutation({
    mutationFn: () => apiClient.put('/notifications/subscriptions', {
      event_family: eventFamily,
      destination_id: destinationChoice === 'in_app' ? null : Number(destinationChoice),
      frequency: destinationChoice === 'in_app' ? 'immediate' : frequency,
      timezone: timezoneName,
      quiet_start_local: quietStart || null,
      quiet_end_local: quietEnd || null,
      cooldown_minutes: Number(cooldown),
      threshold_ratio: eventFamily === 'intrinsic_value_threshold_crossed' ? Number(thresholdRatio) : null,
      hysteresis_ratio: Number(hysteresisRatio),
      is_enabled: true,
    }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['notification-subscriptions'] }),
  });

  const destinations = destinationsQuery.data ?? [];
  const enabledDestinations = destinations.filter((item) => item.status === 'enabled');
  const mutationError = slackMutation.isError || emailMutation.isError || verifyMutation.isError || subscriptionMutation.isError || testMutation.isError;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm font-medium text-primary"><Bell className="h-4 w-4" /> Notifications</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Research events, with noise controls</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          In-app history is durable. External delivery is opt-in, fail-closed, and never turns a delayed 13F filing into a buy signal.
        </p>
      </div>

      {mutationError ? <div className="flex gap-2 rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-950"><AlertCircle className="mt-0.5 h-4 w-4" /> The requested notification change did not complete. Existing history and settings were preserved.</div> : null}

      <Card>
        <CardHeader><CardTitle>In-app inbox</CardTitle><CardDescription>Corrections remain linked to the original event; dismissing hides an item but does not delete evidence.</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          {inboxQuery.isLoading ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading notifications…</div> : inboxQuery.isError ? <div className="text-sm text-rose-700">Unable to load notification history.</div> : (inboxQuery.data?.length ?? 0) === 0 ? <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">No notifications yet. Follow a manager or schedule a research review.</div> : inboxQuery.data?.map((item) => (
            <div key={item.id} className={`rounded-lg border p-4 ${item.read_at ? 'bg-muted/20' : 'border-primary/30'}`}>
              <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
                <div><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.title}</span>{item.correction_type === 'correction' ? <Badge variant="warning">Correction</Badge> : null}<Badge variant="outline">{label(item.event_family)}</Badge></div><p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p><div className="mt-2 text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString()}</div></div>
                <div className="flex shrink-0 gap-2"><Button asChild size="sm"><Link href={item.evidence_route} onClick={() => stateMutation.mutate({ id: item.id, operation: 'read' })}>Open evidence <ExternalLink className="h-3.5 w-3.5" /></Link></Button><Button type="button" size="sm" variant="ghost" onClick={() => stateMutation.mutate({ id: item.id, operation: 'dismiss' })}><X className="h-3.5 w-3.5" /> Dismiss</Button></div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Delivery audit</CardTitle><CardDescription>External attempts, retries, failures, and ambiguous outcomes are visible without exposing destination secrets.</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          {deliveryQuery.isLoading ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading delivery audit…</div> : deliveryQuery.isError ? <div className="text-sm text-rose-700">Unable to load delivery audit.</div> : (deliveryQuery.data?.length ?? 0) === 0 ? <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">No external delivery attempts yet.</div> : deliveryQuery.data?.map((attempt) => (
            <div key={attempt.id} className="flex flex-col justify-between gap-3 rounded-lg border p-4 text-sm md:flex-row md:items-start">
              <div><Link href={attempt.evidence_route} className="font-medium text-primary hover:underline">{attempt.notification_title}</Link><div className="mt-1 text-xs text-muted-foreground">{attempt.destination_label} · {attempt.destination_hint} · {label(attempt.event_family)}</div><div className="mt-1 text-xs text-muted-foreground">Attempts {attempt.attempt_count} · {attempt.last_attempt_at ? new Date(attempt.last_attempt_at).toLocaleString() : 'not attempted'}</div>{attempt.provider_response_class ? <div className="mt-1 text-xs text-rose-700">{label(attempt.provider_response_class)}</div> : null}</div>
              <Badge variant={attempt.status === 'succeeded' ? 'success' : attempt.status === 'queued' || attempt.status === 'retry_scheduled' ? 'warning' : 'danger'}>{label(attempt.status)}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Destinations</CardTitle><CardDescription>Secrets are encrypted at rest and responses contain only masked labels. Setup never sends a Slack test automatically.</CardDescription></CardHeader>
          <CardContent className="space-y-5">
            {destinationsQuery.isLoading ? <div className="text-sm text-muted-foreground">Loading destinations…</div> : destinations.map((destination) => (
              <div key={destination.id} className="rounded-lg border p-4 text-sm">
                <div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 font-medium">{destination.channel === 'slack' ? <MessageSquare className="h-4 w-4" /> : <Mail className="h-4 w-4" />}{destination.label}</div><div className="mt-1 text-xs text-muted-foreground">{destination.destination_hint}</div></div><Badge variant={destination.status === 'enabled' ? 'success' : destination.status === 'configuration_blocked' ? 'danger' : 'warning'}>{label(destination.status)}</Badge></div>
                {destination.last_error_class ? <div className="mt-2 text-xs text-rose-700">{label(destination.last_error_class)}</div> : null}
                {destination.status === 'enabled' ? <div className="mt-3 space-y-2"><label className="flex items-center gap-2 text-xs"><Checkbox checked={Boolean(testConsent[destination.id])} onCheckedChange={(checked) => setTestConsent((current) => ({ ...current, [destination.id]: checked === true }))} /> I explicitly authorize one test message.</label><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!testConsent[destination.id] || testMutation.isPending} onClick={() => testMutation.mutate(destination.id)}><Send className="h-3.5 w-3.5" /> Send test</Button><Button type="button" size="sm" variant="ghost" onClick={() => revokeMutation.mutate(destination.id)}>Revoke</Button></div></div> : null}
              </div>
            ))}

            <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
              <div className="font-medium">Slack Incoming Webhook</div>
              <Input aria-label="Slack destination label" value={slackLabel} onChange={(event) => setSlackLabel(event.target.value)} />
              <Input aria-label="Slack Incoming Webhook URL" type="password" placeholder="https://hooks.slack.com/services/…" value={webhookUrl} onChange={(event) => setWebhookUrl(event.target.value)} />
              <label className="flex items-start gap-2 text-xs text-muted-foreground"><Checkbox checked={slackConsent} onCheckedChange={(checked) => setSlackConsent(checked === true)} /> I authorize ValuePilot to store this destination encrypted and send only the subscribed events.</label>
              <Button type="button" disabled={!slackConsent || !webhookUrl || slackMutation.isPending} onClick={() => slackMutation.mutate()}>{slackMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} Save Slack destination</Button>
            </div>

            <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
              <div className="font-medium">Verified email</div>
              <Input aria-label="Email destination label" value={emailLabel} onChange={(event) => setEmailLabel(event.target.value)} />
              <Input aria-label="Email destination" type="email" placeholder="investor@example.com" value={email} onChange={(event) => setEmail(event.target.value)} />
              <label className="flex items-start gap-2 text-xs text-muted-foreground"><Checkbox checked={emailConsent} onCheckedChange={(checked) => setEmailConsent(checked === true)} /> I authorize a single verification email and later subscribed delivery.</label>
              <Button type="button" variant="outline" disabled={!emailConsent || !email || emailMutation.isPending} onClick={() => emailMutation.mutate()}><Mail className="h-4 w-4" /> Send verification</Button>
              {verificationDestinationId ? <div className="flex gap-2"><Input aria-label="Email verification token" placeholder="One-time verification code" value={verificationToken} onChange={(event) => setVerificationToken(event.target.value)} /><Button type="button" disabled={!verificationToken || verifyMutation.isPending} onClick={() => verifyMutation.mutate()}>Verify</Button></div> : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Subscriptions & quiet hours</CardTitle><CardDescription>In-app history is always immediate. External channels can deliver immediately or as a timezone-aware daily or weekly digest. Intrinsic-value threshold, hysteresis, and cooldown policy are shared across every destination.</CardDescription></CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-3">
              <Select value={eventFamily} onValueChange={setEventFamily}><SelectTrigger aria-label="Event family"><SelectValue /></SelectTrigger><SelectContent>{eventFamilies.map((family) => <SelectItem key={family} value={family}>{label(family)}</SelectItem>)}</SelectContent></Select>
              <Select value={destinationChoice} onValueChange={setDestinationChoice}><SelectTrigger aria-label="Delivery destination"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="in_app">In-app only</SelectItem>{enabledDestinations.map((destination) => <SelectItem key={destination.id} value={String(destination.id)}>{destination.label} · {destination.destination_hint}</SelectItem>)}</SelectContent></Select>
              <Select value={destinationChoice === 'in_app' ? 'immediate' : frequency} onValueChange={setFrequency} disabled={destinationChoice === 'in_app'}><SelectTrigger aria-label="Delivery frequency"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="immediate">Immediate</SelectItem><SelectItem value="daily_digest">Daily digest</SelectItem><SelectItem value="weekly_digest">Weekly digest</SelectItem></SelectContent></Select>
              <Input aria-label="IANA timezone" value={timezoneName} onChange={(event) => setTimezoneName(event.target.value)} />
              <div className="grid grid-cols-2 gap-2"><Input aria-label="Quiet hours start" type="time" value={quietStart} onChange={(event) => setQuietStart(event.target.value)} /><Input aria-label="Quiet hours end" type="time" value={quietEnd} onChange={(event) => setQuietEnd(event.target.value)} /></div>
              <Input aria-label="Cooldown minutes" type="number" min="0" max="43200" value={cooldown} onChange={(event) => setCooldown(event.target.value)} />
              {eventFamily === 'intrinsic_value_threshold_crossed' ? <div className="grid grid-cols-2 gap-2"><Input aria-label="Margin of safety threshold ratio" type="number" min="0" max="0.95" step="0.01" value={thresholdRatio} onChange={(event) => setThresholdRatio(event.target.value)} /><Input aria-label="Threshold hysteresis ratio" type="number" min="0" max="0.25" step="0.01" value={hysteresisRatio} onChange={(event) => setHysteresisRatio(event.target.value)} /></div> : null}
              <Button type="button" disabled={subscriptionMutation.isPending} onClick={() => subscriptionMutation.mutate()}><CheckCircle2 className="h-4 w-4" /> Save subscription</Button>
            </div>

            <div className="space-y-2 border-t pt-4">
              <div className="text-sm font-medium">Current subscriptions</div>
              {subscriptionsQuery.isLoading ? <div className="text-sm text-muted-foreground">Loading subscriptions…</div> : (subscriptionsQuery.data?.length ?? 0) === 0 ? <div className="text-sm text-muted-foreground">No explicit subscriptions. In-app notification history remains available when relevant events are generated.</div> : subscriptionsQuery.data?.map((subscription) => (
                <div key={subscription.id} className="rounded-lg border p-3 text-xs"><div className="font-medium">{label(subscription.event_family)}</div><div className="mt-1 text-muted-foreground">{subscription.destination_id ? `Destination #${subscription.destination_id}` : 'In-app'} · {label(subscription.frequency)} · {subscription.timezone} · {subscription.cooldown_minutes}m cooldown</div></div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
