'use client';

import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';

import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from '@/components/ui/toast';
import { type AppToastType, useToast } from '@/components/ui/use-toast';
import { cn } from '@/lib/utils';

const appToastStyles: Record<
  AppToastType,
  {
    accentClassName: string;
    icon: typeof CheckCircle2;
    iconClassName: string;
  }
> = {
  success: {
    accentClassName: 'border-emerald-500/35',
    icon: CheckCircle2,
    iconClassName: 'text-emerald-600',
  },
  error: {
    accentClassName: 'border-destructive/45',
    icon: XCircle,
    iconClassName: 'text-destructive',
  },
  warning: {
    accentClassName: 'border-amber-500/45',
    icon: AlertTriangle,
    iconClassName: 'text-amber-600',
  },
  info: {
    accentClassName: 'border-sky-500/35',
    icon: Info,
    iconClassName: 'text-sky-600',
  },
};

export function Toaster() {
  const { toasts } = useToast();

  return (
    <ToastProvider swipeDirection="right">
      {toasts.map(({ id, title, description, action, appType, className, ...props }) => {
        const presentation = appType ? appToastStyles[appType] : null;
        const Icon = presentation?.icon;

        return (
          <Toast
            key={id}
            className={cn(presentation?.accentClassName, className)}
            {...props}
          >
            {Icon ? (
              <Icon className={cn('mt-0.5 h-5 w-5 shrink-0', presentation.iconClassName)} />
            ) : null}
            <div className="grid gap-1">
              {title ? <ToastTitle>{title}</ToastTitle> : null}
              {description ? (
                <ToastDescription>{description}</ToastDescription>
              ) : null}
            </div>
            {action}
            <ToastClose />
          </Toast>
        );
      })}
      <ToastViewport />
    </ToastProvider>
  );
}
