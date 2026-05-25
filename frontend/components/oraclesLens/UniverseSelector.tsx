/**
 * UniverseSelector — chip row + Custom dialog for picking the manager
 * universe that Oracle's Lens scores against.
 *
 * Task doc: docs/tasks/2026-05-24_oracles-lens-universe-selector.md
 *
 * Renders 5 preset chips ([Deep Value] [Activists] [Small-cap Sleuths]
 * [Permanent Capital] [All]) plus a "Custom…" button that opens a
 * dialog with checkboxes for the 8 `style_primary` values. Selection
 * is communicated back to the parent via `onSelect(filters)` where
 * `filters` is `{stylePrimary, capitalStructure, marketCapFocus}` —
 * the parent owns the URL/router sync.
 */
'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { UNIVERSE_PRESETS, matchPreset } from '@/lib/oraclesLens';

// The eight canonical style_primary values (must match
// backend/app/models/institutions.py STYLE_PRIMARY exactly minus
// "unknown" — admin pages still need "unknown" for un-classified rows
// but the Oracle's Lens UI filters on the 8 classified buckets only).
const STYLE_PRIMARY_OPTIONS: { value: string; label: string }[] = [
  { value: 'value_deep', label: 'Value (deep)' },
  { value: 'value_concentrated', label: 'Value (concentrated)' },
  { value: 'quality_compounder', label: 'Quality compounder' },
  { value: 'activist', label: 'Activist' },
  { value: 'growth_long_short', label: 'Growth long/short' },
  { value: 'special_situations', label: 'Special situations' },
  { value: 'multi_strategy_macro', label: 'Multi-strategy / macro' },
  { value: 'endowment_passive', label: 'Endowment / passive' },
];

export type UniverseFilters = {
  stylePrimary: string[];
  capitalStructure: string[];
  marketCapFocus: string[];
};

interface UniverseSelectorProps {
  current: UniverseFilters;
  filteredManagerCount: number | null;
  totalManagerCount: number | null;
  onSelect: (filters: UniverseFilters) => void;
  isLoading?: boolean;
}

export function UniverseSelector({
  current,
  filteredManagerCount,
  totalManagerCount,
  onSelect,
  isLoading = false,
}: UniverseSelectorProps) {
  const [customOpen, setCustomOpen] = useState(false);
  const [customDraft, setCustomDraft] = useState<string[]>(current.stylePrimary);

  const activePresetKey = useMemo(() => matchPreset(current), [current]);

  const openCustom = () => {
    setCustomDraft(current.stylePrimary);
    setCustomOpen(true);
  };

  const applyCustom = () => {
    // Custom only edits style_primary (capital / market_cap filters
    // are deferred to a future iteration — task doc Scope (Out)).
    onSelect({
      stylePrimary: customDraft,
      capitalStructure: [],
      marketCapFocus: [],
    });
    setCustomOpen(false);
  };

  const toggleCustomStyle = (value: string) => {
    setCustomDraft((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase text-muted-foreground">
          Universe
        </span>
        {UNIVERSE_PRESETS.map((preset) => {
          const isActive = activePresetKey === preset.key;
          return (
            <Button
              key={preset.key}
              type="button"
              variant={isActive ? 'default' : 'outline'}
              size="sm"
              className="h-7 text-xs"
              disabled={isLoading}
              onClick={() =>
                onSelect({
                  stylePrimary: preset.filters.stylePrimary ?? [],
                  capitalStructure: preset.filters.capitalStructure ?? [],
                  marketCapFocus: preset.filters.marketCapFocus ?? [],
                })
              }
              title={preset.description}
            >
              {preset.label}
            </Button>
          );
        })}
        <Button
          type="button"
          variant={activePresetKey === null ? 'default' : 'outline'}
          size="sm"
          className="h-7 text-xs"
          onClick={openCustom}
          disabled={isLoading}
        >
          Custom…
          <ChevronDown className="ml-1 h-3 w-3" />
        </Button>
        {isLoading ? (
          <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-muted-foreground" />
        ) : null}
        {filteredManagerCount !== null && totalManagerCount !== null ? (
          <Badge variant="secondary" className="ml-auto">
            {filteredManagerCount} of {totalManagerCount} managers
          </Badge>
        ) : null}
      </div>

      <Dialog open={customOpen} onOpenChange={setCustomOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Custom universe</DialogTitle>
            <DialogDescription>
              Pick which manager styles contribute to the Signal /
              Conviction / Distinctive scores. The selection saves to
              the URL so the choice is shareable and bookmarkable.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {STYLE_PRIMARY_OPTIONS.map((option) => {
              const checked = customDraft.includes(option.value);
              return (
                <label
                  key={option.value}
                  htmlFor={`universe-style-${option.value}`}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-muted/40"
                >
                  <Checkbox
                    id={`universe-style-${option.value}`}
                    checked={checked}
                    onCheckedChange={() => toggleCustomStyle(option.value)}
                  />
                  <span>{option.label}</span>
                </label>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            {customDraft.length === 0
              ? 'No styles selected — equivalent to the "All" preset.'
              : `${customDraft.length} of ${STYLE_PRIMARY_OPTIONS.length} styles selected.`}
          </p>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setCustomOpen(false)}
            >
              Cancel
            </Button>
            <Button type="button" onClick={applyCustom}>
              Apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
