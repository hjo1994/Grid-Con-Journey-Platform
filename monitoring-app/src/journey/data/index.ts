// Data layer of the evaluation journey. For now it serves the demo data of
// the approved mockup only; there is no backend for the journey yet, and
// nothing here reads real requests or evaluations.
export * from "./demoData";

export const IS_DEMO = true;

// Pass threshold in points (of 11). Placeholder until the evaluation rules
// define it.
export const PASS_THRESHOLD = 6;
