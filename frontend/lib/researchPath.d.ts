export type ResearchNotes = { observation: string; explanations: string; evidenceNeeded: string; falsification: string; judgment: string };
export const RESEARCH_STEPS: ReadonlyArray<{ key: keyof ResearchNotes; title: string; question: string; hint: string }>;
export function emptyResearchNotes(): ResearchNotes;
export function hasResearchNotes(notes?: Partial<ResearchNotes>): boolean;
export function appendResearchNotes(thesis: string, notes?: Partial<ResearchNotes>): string;
