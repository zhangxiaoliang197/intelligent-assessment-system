import { create } from "zustand";
import type { ReasoningError, ReasoningWarning } from "../utils/reasoningTypes";

export interface ShaclResultState {
  errors: ReasoningError[];
  warnings: ReasoningWarning[];
  activeMessageKey: string | null;
  panelOpenRequest: number;
  shaclShapesLoaded: boolean;
  setShaclResults: (errors: ReasoningError[], warnings: ReasoningWarning[]) => void;
  clearShaclResults: () => void;
  highlightMessage: (key: string) => void;
  clearHighlight: () => void;
  requestOpenPanel: () => void;
  setShaclShapesLoaded: (loaded: boolean) => void;
}

export function makeShaclMessageKey(
  severity: string,
  nodeId: string | undefined,
  message: string,
): string {
  return `${severity}::${nodeId ?? ""}::${message}`;
}

export const useShaclResultStore = create<ShaclResultState>((set) => ({
  errors: [],
  warnings: [],
  activeMessageKey: null,
  panelOpenRequest: 0,
  shaclShapesLoaded: false,
  setShaclResults: (errors, warnings) => set({ errors, warnings }),
  clearShaclResults: () => set({ errors: [], warnings: [], activeMessageKey: null }),
  highlightMessage: (key) => set({ activeMessageKey: key }),
  clearHighlight: () => set({ activeMessageKey: null }),
  requestOpenPanel: () => set((s) => ({ panelOpenRequest: s.panelOpenRequest + 1 })),
  setShaclShapesLoaded: (loaded) => set({ shaclShapesLoaded: loaded }),
}));
