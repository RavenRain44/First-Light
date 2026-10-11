import { createContext, useContext, useEffect, useRef } from "react";
import type { Facility } from "./types";

// These profiles keep the selector available while registry metadata loads or the server is offline.
export const FACILITY_OPTIONS: Facility[] = [
  { id: "IA-AMES-SC", name: "USDA Service Center, Ames, IA", city: "Ames", synthetic: true, lat: 42.0308, lon: -93.6319,
    state: "IA", timezone: "America/Chicago", asos_station: "AMW", hours: { open: "07:30", close: "16:30" }, corridors: [], accessibility_notes: [] },
  { id: "NC-WILMINGTON-SC", name: "Wilmington demonstration facility, NC", city: "Wilmington", synthetic: true, lat: 34.2257, lon: -77.875,
    state: "NC", timezone: "America/New_York", asos_station: "ILM", hours: { open: "07:30", close: "16:30" }, corridors: [], accessibility_notes: [] },
];
export const FacilityContext = createContext<Facility>(FACILITY_OPTIONS[0]);
export const useFacility = () => useContext(FacilityContext);
export const facilityLabel = (facility: Facility) => `${facility.city ?? (facility.state === "NC" ? "Wilmington" : "Ames")}, ${facility.state}`;

const drafts = new Set<symbol>();
export const hasUnsavedDraft = () => drafts.size > 0;
/** Warn only after an actual edit, rather than whenever the notification screen is open. */
export function useUnsavedDraft(dirty: boolean) {
  const token = useRef(Symbol("facility draft"));
  useEffect(() => {
    const id = token.current;
    if (dirty) drafts.add(id); else drafts.delete(id);
    return () => { drafts.delete(id); };
  }, [dirty]);
}
